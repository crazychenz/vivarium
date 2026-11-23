// Package ethbridge turns the Ethernet frames of a QEMU "-netdev dgram" unix
// socket into plain IP packets, and back again.
//
// It is the piece that lets wireguard-go (which wants a layer-3 TUN device)
// be plugged into a virtual NIC (which speaks layer-2) without a kernel TUN
// device, root, or a TCP/IP stack in between:
//
//	guest NIC --Ethernet--> [ethbridge] --IPv4 packets--> wireguard-go --UDP--> mitmproxy
//
// What it does:
//   - answers ARP for every address (proxy ARP), so the guest can use any
//     default gateway and DNS address it likes; every frame the guest routes
//     to the gateway MAC is forwarded
//   - strips the Ethernet header from IPv4 frames addressed to the gateway MAC
//     (and trims Ethernet padding using the IPv4 total length)
//   - wraps IPv4 packets coming back from the tunnel in Ethernet frames
//     addressed to the guest MAC (learned from the guest's own frames)
//   - drops everything else (IPv6, broadcasts, multicast, VLAN, ...), so the
//     guest has no way out except through the tunnel
//
// The package depends only on the standard library.
package ethbridge

import (
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"sync"
	"sync/atomic"

	"qemu-wg-mitm/internal/pkt"
)

// DefaultGatewayMAC is the MAC address the bridge answers ARP with.
var DefaultGatewayMAC = pkt.MAC{0x52, 0x54, 0x00, 0x00, 0x00, 0xfe}

// Config configures a Bridge.
type Config struct {
	// GatewayMAC is the hardware address the guest sees for every IP address
	// it ARPs for. Zero means DefaultGatewayMAC.
	GatewayMAC pkt.MAC

	// GuestIP, if valid, is the guest's own address. The bridge never answers
	// ARP requests for it (that would look like an address conflict).
	GuestIP netip.Addr

	// PeerPath is the unix socket path QEMU binds ("local.path" of its dgram
	// netdev). It is used to reach QEMU until the first frame from QEMU tells
	// the bridge the real return address. May be empty.
	PeerPath string

	// Logf receives diagnostic messages. May be nil.
	Logf func(format string, args ...any)

	// Verbose logs every dropped frame.
	Verbose bool
}

// Stats is a snapshot of the bridge counters.
type Stats struct {
	FromGuestFrames  uint64 // frames received from QEMU
	ForwardedToTun   uint64 // IPv4 packets handed to the tunnel
	ToGuestFrames    uint64 // IPv4 packets sent to the guest
	ARPReplies       uint64
	DroppedIPv6      uint64 // outbound or inbound IPv6
	DroppedNotForUs  uint64 // IPv4 frames not addressed to the gateway MAC
	DroppedMalformed uint64
	DroppedOther     uint64 // unknown EtherTypes (VLAN, LLDP, ...)
	DroppedNoGuest   uint64 // tunnel packets before the guest MAC was known
	SendErrors       uint64
}

func (s Stats) String() string {
	return fmt.Sprintf("guest->tun %d pkts (of %d frames), tun->guest %d pkts, arp replies %d, "+
		"dropped: ipv6 %d, not-for-gateway %d, malformed %d, other %d, no-guest %d, send errors %d",
		s.ForwardedToTun, s.FromGuestFrames, s.ToGuestFrames, s.ARPReplies,
		s.DroppedIPv6, s.DroppedNotForUs, s.DroppedMalformed, s.DroppedOther, s.DroppedNoGuest, s.SendErrors)
}

type counters struct {
	fromGuest, forwarded, toGuest, arpReplies      atomic.Uint64
	droppedIPv6, droppedNotForUs, droppedMalformed atomic.Uint64
	droppedOther, droppedNoGuest, sendErrors       atomic.Uint64
}

// Bridge converts between Ethernet frames on a unix datagram socket and IPv4
// packets. ReadIPv4 must be called from a single goroutine; WriteIP may be
// called concurrently with it.
type Bridge struct {
	conn     *net.UnixConn
	cfg      Config
	sockPath string // removed on Close when the bridge created it

	cfgPeer *net.UnixAddr
	peer    atomic.Pointer[net.UnixAddr]
	guest   atomic.Pointer[pkt.MAC]
	closed  atomic.Bool

	rbuf  []byte
	wpool sync.Pool
	st    counters
}

// Listen binds a unix datagram socket at path (replacing a stale socket file)
// and returns a Bridge using it. The socket is accessible to the owner only.
func Listen(path string, cfg Config) (*Bridge, error) {
	if fi, err := os.Lstat(path); err == nil {
		if fi.Mode()&os.ModeSocket == 0 {
			return nil, fmt.Errorf("%s exists and is not a socket", path)
		}
		if err := os.Remove(path); err != nil {
			return nil, err
		}
	}
	addr, err := net.ResolveUnixAddr("unixgram", path)
	if err != nil {
		return nil, err
	}
	conn, err := net.ListenUnixgram("unixgram", addr)
	if err != nil {
		return nil, err
	}
	if err := os.Chmod(path, 0o600); err != nil {
		conn.Close()
		return nil, err
	}
	b, err := New(conn, cfg)
	if err != nil {
		conn.Close()
		return nil, err
	}
	b.sockPath = path
	return b, nil
}

// New wraps an existing unix datagram socket.
func New(conn *net.UnixConn, cfg Config) (*Bridge, error) {
	if cfg.GatewayMAC.IsZero() {
		cfg.GatewayMAC = DefaultGatewayMAC
	}
	if cfg.GatewayMAC.IsMulticast() {
		return nil, fmt.Errorf("gateway MAC %s must be a unicast address", cfg.GatewayMAC)
	}
	b := &Bridge{conn: conn, cfg: cfg, rbuf: make([]byte, 65536)}
	b.wpool.New = func() any { s := make([]byte, 0, 2048); return &s }
	if cfg.PeerPath != "" {
		a, err := net.ResolveUnixAddr("unixgram", cfg.PeerPath)
		if err != nil {
			return nil, err
		}
		b.cfgPeer = a
	}
	// Frames are small, but bursts (TCP windows, QUIC) should not be dropped
	// by the kernel while wireguard-go is busy encrypting.
	_ = conn.SetReadBuffer(4 << 20)
	_ = conn.SetWriteBuffer(4 << 20)
	return b, nil
}

// GatewayMAC returns the MAC address the bridge presents to the guest.
func (b *Bridge) GatewayMAC() pkt.MAC { return b.cfg.GatewayMAC }

// GuestMAC returns the guest MAC learned so far.
func (b *Bridge) GuestMAC() (pkt.MAC, bool) {
	if m := b.guest.Load(); m != nil {
		return *m, true
	}
	return pkt.MAC{}, false
}

func (b *Bridge) logf(format string, args ...any) {
	if b.cfg.Logf != nil {
		b.cfg.Logf(format, args...)
	}
}

func (b *Bridge) debugf(format string, args ...any) {
	if b.cfg.Verbose {
		b.logf(format, args...)
	}
}

// Stats returns a snapshot of the counters.
func (b *Bridge) Stats() Stats {
	return Stats{
		FromGuestFrames:  b.st.fromGuest.Load(),
		ForwardedToTun:   b.st.forwarded.Load(),
		ToGuestFrames:    b.st.toGuest.Load(),
		ARPReplies:       b.st.arpReplies.Load(),
		DroppedIPv6:      b.st.droppedIPv6.Load(),
		DroppedNotForUs:  b.st.droppedNotForUs.Load(),
		DroppedMalformed: b.st.droppedMalformed.Load(),
		DroppedOther:     b.st.droppedOther.Load(),
		DroppedNoGuest:   b.st.droppedNoGuest.Load(),
		SendErrors:       b.st.sendErrors.Load(),
	}
}

// ReadIPv4 blocks until the guest sends an IPv4 packet addressed to the
// gateway, copies it into dst and returns its length. ARP is answered
// internally. After Close it returns os.ErrClosed.
func (b *Bridge) ReadIPv4(dst []byte) (int, error) {
	for {
		n, from, err := b.conn.ReadFromUnix(b.rbuf)
		if err != nil {
			if b.closed.Load() || errors.Is(err, net.ErrClosed) {
				return 0, os.ErrClosed
			}
			return 0, err
		}
		b.st.fromGuest.Add(1)
		if from != nil && from.Name != "" && from.Name != "@" {
			if cur := b.peer.Load(); cur == nil || cur.Name != from.Name {
				b.peer.Store(&net.UnixAddr{Name: from.Name, Net: "unixgram"})
				b.debugf("QEMU peer socket: %s", from.Name)
			}
		}
		if m := b.handleFrame(b.rbuf[:n], dst); m > 0 {
			return m, nil
		}
	}
}

// handleFrame processes one frame from the guest. It returns the number of
// bytes copied to dst when the frame carried an IPv4 packet to forward.
func (b *Bridge) handleFrame(frame, dst []byte) int {
	eth, ok := pkt.ParseEthernet(frame)
	if !ok {
		b.st.droppedMalformed.Add(1)
		b.debugf("drop: runt frame (%d bytes)", len(frame))
		return 0
	}
	switch eth.Type {
	case pkt.EtherTypeARP:
		b.handleARP(eth)
		return 0

	case pkt.EtherTypeIPv4:
		if eth.Dst != b.cfg.GatewayMAC {
			b.st.droppedNotForUs.Add(1)
			b.debugf("drop: IPv4 frame to %s (not the gateway MAC)", eth.Dst)
			return 0
		}
		total, ok := pkt.IPv4Len(eth.Payload)
		if !ok || total > len(dst) {
			b.st.droppedMalformed.Add(1)
			b.debugf("drop: malformed or oversized IPv4 packet (%d bytes)", len(eth.Payload))
			return 0
		}
		b.learnGuest(eth.Src)
		copy(dst, eth.Payload[:total])
		b.st.forwarded.Add(1)
		return total

	case pkt.EtherTypeIPv6:
		b.st.droppedIPv6.Add(1)
		b.debugf("drop: IPv6 frame from %s", eth.Src)
		return 0

	default:
		b.st.droppedOther.Add(1)
		b.debugf("drop: ethertype 0x%04x from %s", eth.Type, eth.Src)
		return 0
	}
}

func (b *Bridge) handleARP(eth pkt.Ethernet) {
	a, ok := pkt.ParseARP(eth.Payload)
	if !ok {
		b.st.droppedMalformed.Add(1)
		return
	}
	b.learnGuest(a.SenderMAC)
	switch {
	case a.Op != pkt.ARPRequest:
		return // replies and gratuitous announcements need no answer
	case a.SenderIP.IsUnspecified():
		return // address conflict probe: never claim anything
	case a.TargetIP == a.SenderIP:
		return // gratuitous request
	case b.cfg.GuestIP.IsValid() && a.TargetIP == b.cfg.GuestIP:
		return // that is the guest itself
	}
	reply := pkt.ARP{
		Op:        pkt.ARPReply,
		SenderMAC: b.cfg.GatewayMAC,
		SenderIP:  a.TargetIP,
		TargetMAC: a.SenderMAC,
		TargetIP:  a.SenderIP,
	}
	frame := pkt.AppendEthernet(nil, a.SenderMAC, b.cfg.GatewayMAC, pkt.EtherTypeARP, reply.Marshal())
	if err := b.send(frame); err == nil {
		b.st.arpReplies.Add(1)
		b.debugf("ARP: %s is-at %s (asked by %s)", a.TargetIP, b.cfg.GatewayMAC, a.SenderIP)
	}
}

func (b *Bridge) learnGuest(m pkt.MAC) {
	if m.IsZero() || m.IsMulticast() {
		return
	}
	if cur := b.guest.Load(); cur == nil || *cur != m {
		b.guest.Store(&m)
		b.logf("guest MAC: %s", m)
	}
}

// WriteIP wraps an IP packet from the tunnel in an Ethernet frame and sends it
// to the guest. IPv6 and unusable packets are dropped silently (returning nil)
// so that they cannot take the tunnel down; only a closed bridge is an error.
func (b *Bridge) WriteIP(p []byte) error {
	if b.closed.Load() {
		return os.ErrClosed
	}
	if len(p) < 20 {
		b.st.droppedMalformed.Add(1)
		return nil
	}
	switch p[0] >> 4 {
	case 4:
	case 6:
		b.st.droppedIPv6.Add(1)
		return nil
	default:
		b.st.droppedMalformed.Add(1)
		return nil
	}
	g := b.guest.Load()
	if g == nil {
		b.st.droppedNoGuest.Add(1)
		b.debugf("drop: tunnel packet but guest MAC not known yet")
		return nil
	}
	bp := b.wpool.Get().(*[]byte)
	frame := pkt.AppendEthernet((*bp)[:0], *g, b.cfg.GatewayMAC, pkt.EtherTypeIPv4, p)
	err := b.send(frame)
	*bp = frame[:0]
	b.wpool.Put(bp)
	if err == nil {
		b.st.toGuest.Add(1)
	} else if b.closed.Load() {
		return os.ErrClosed
	}
	return nil
}

func (b *Bridge) send(frame []byte) error {
	to := b.peer.Load()
	if to == nil {
		to = b.cfgPeer
	}
	if to == nil {
		b.st.sendErrors.Add(1)
		return errors.New("no QEMU peer address known yet")
	}
	if _, err := b.conn.WriteToUnix(frame, to); err != nil {
		b.st.sendErrors.Add(1)
		b.debugf("send to %s failed: %v", to.Name, err)
		return err
	}
	return nil
}

// Close closes the socket (unblocking ReadIPv4) and removes the socket file if
// the bridge created it. It is safe to call more than once.
func (b *Bridge) Close() error {
	if !b.closed.CompareAndSwap(false, true) {
		return nil
	}
	err := b.conn.Close()
	if b.sockPath != "" {
		_ = os.Remove(b.sockPath)
	}
	return err
}
