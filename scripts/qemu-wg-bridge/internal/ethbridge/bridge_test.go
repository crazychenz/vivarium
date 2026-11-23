package ethbridge

import (
	"errors"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"testing"
	"time"

	"qemu-wg-mitm/internal/pkt"
)

var (
	guestMAC = pkt.MAC{0x52, 0x54, 0x00, 0xaa, 0x00, 0x01}
	guestIP  = netip.MustParseAddr("10.0.0.1")
)

// fakeQEMU is the guest side: a unix datagram socket bound like QEMU's
// "local.path" that exchanges frames with the bridge.
type fakeQEMU struct {
	t    *testing.T
	conn *net.UnixConn
	to   *net.UnixAddr
}

type harness struct {
	t      *testing.T
	br     *Bridge
	guest  *fakeQEMU
	packet chan []byte // packets ReadIPv4 handed up
	done   chan error
}

func newHarness(t *testing.T, cfg Config) *harness {
	t.Helper()
	dir := t.TempDir()
	bridgePath := filepath.Join(dir, "b.sock")
	guestPath := filepath.Join(dir, "q.sock")
	cfg.PeerPath = guestPath
	cfg.GuestIP = guestIP
	cfg.Logf = t.Logf
	cfg.Verbose = true

	br, err := Listen(bridgePath, cfg)
	if err != nil {
		t.Fatal(err)
	}
	ga, _ := net.ResolveUnixAddr("unixgram", guestPath)
	gc, err := net.ListenUnixgram("unixgram", ga)
	if err != nil {
		t.Fatal(err)
	}
	ba, _ := net.ResolveUnixAddr("unixgram", bridgePath)
	h := &harness{t: t, br: br, guest: &fakeQEMU{t: t, conn: gc, to: ba}, packet: make(chan []byte, 16), done: make(chan error, 1)}
	t.Cleanup(func() { gc.Close(); br.Close() })

	go func() {
		buf := make([]byte, 65536)
		for {
			n, err := br.ReadIPv4(buf)
			if err != nil {
				h.done <- err
				return
			}
			h.packet <- append([]byte(nil), buf[:n]...)
		}
	}()
	return h
}

func (g *fakeQEMU) send(frame []byte) {
	g.t.Helper()
	if _, err := g.conn.WriteToUnix(frame, g.to); err != nil {
		g.t.Fatal(err)
	}
}

func (g *fakeQEMU) recv(timeout time.Duration) ([]byte, bool) {
	g.t.Helper()
	buf := make([]byte, 65536)
	g.conn.SetReadDeadline(time.Now().Add(timeout))
	n, err := g.conn.Read(buf)
	if err != nil {
		return nil, false
	}
	return buf[:n], true
}

func arpRequest(senderIP, targetIP netip.Addr) []byte {
	a := pkt.ARP{Op: pkt.ARPRequest, SenderMAC: guestMAC, SenderIP: senderIP, TargetIP: targetIP}
	return pkt.AppendEthernet(nil, pkt.Broadcast, guestMAC, pkt.EtherTypeARP, a.Marshal())
}

func TestARPAnsweredForAnyAddress(t *testing.T) {
	h := newHarness(t, Config{})
	for _, target := range []string{"10.0.0.254", "10.0.0.53", "192.0.2.77"} {
		tip := netip.MustParseAddr(target)
		h.guest.send(arpRequest(guestIP, tip))
		f, ok := h.guest.recv(2 * time.Second)
		if !ok {
			t.Fatalf("no ARP reply for %s", target)
		}
		eth, _ := pkt.ParseEthernet(f)
		a, ok := pkt.ParseARP(eth.Payload)
		if eth.Type != pkt.EtherTypeARP || !ok || a.Op != pkt.ARPReply ||
			a.SenderIP != tip || a.SenderMAC != DefaultGatewayMAC || a.TargetMAC != guestMAC || a.TargetIP != guestIP ||
			eth.Dst != guestMAC || eth.Src != DefaultGatewayMAC {
			t.Fatalf("bad reply for %s: eth=%+v arp=%+v", target, eth, a)
		}
	}
	// The counter is bumped just after the reply is sent, so the test can see
	// the third reply a moment before the third increment: wait for it.
	eventually(t, "3 ARP replies to be counted", func() bool { return h.br.Stats().ARPReplies == 3 })
}

// eventually polls cond for up to two seconds.
func eventually(t *testing.T, what string, cond func() bool) {
	t.Helper()
	for deadline := time.Now().Add(2 * time.Second); time.Now().Before(deadline); time.Sleep(2 * time.Millisecond) {
		if cond() {
			return
		}
	}
	t.Fatalf("timed out waiting for %s", what)
}

func TestARPIgnored(t *testing.T) {
	h := newHarness(t, Config{})
	probes := [][]byte{
		arpRequest(netip.IPv4Unspecified(), netip.MustParseAddr("10.0.0.254")), // conflict probe
		arpRequest(guestIP, guestIP),                         // gratuitous
		arpRequest(netip.MustParseAddr("10.0.0.9"), guestIP), // someone asking for the guest itself
	}
	for _, f := range probes {
		h.guest.send(f)
	}
	if f, ok := h.guest.recv(300 * time.Millisecond); ok {
		t.Fatalf("unexpected reply: %x", f)
	}
}

func TestIPv4GuestToTunnel(t *testing.T) {
	h := newHarness(t, Config{})
	ip := pkt.BuildIPv4UDP(guestIP, netip.MustParseAddr("10.0.0.53"), 4000, 53, 1, []byte("q"))

	// Ethernet pads short frames: trailing zeros must be trimmed.
	frame := pkt.AppendEthernet(nil, DefaultGatewayMAC, guestMAC, pkt.EtherTypeIPv4, append(append([]byte{}, ip...), make([]byte, 20)...))
	h.guest.send(frame)
	select {
	case got := <-h.packet:
		if string(got) != string(ip) {
			t.Fatalf("got %x want %x", got, ip)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("packet not forwarded")
	}
	if m, ok := h.br.GuestMAC(); !ok || m != guestMAC {
		t.Fatalf("guest MAC not learned: %v %v", m, ok)
	}
}

func TestDropsEverythingElse(t *testing.T) {
	h := newHarness(t, Config{})
	ip := pkt.BuildIPv4UDP(guestIP, netip.MustParseAddr("10.0.0.53"), 4000, 53, 1, []byte("q"))
	bad := [][]byte{
		pkt.AppendEthernet(nil, pkt.Broadcast, guestMAC, pkt.EtherTypeIPv4, ip),                   // broadcast
		pkt.AppendEthernet(nil, pkt.MAC{1, 2, 3, 4, 5, 6}, guestMAC, pkt.EtherTypeIPv4, ip),       // some other host
		pkt.AppendEthernet(nil, DefaultGatewayMAC, guestMAC, pkt.EtherTypeIPv6, make([]byte, 60)), // IPv6
		pkt.AppendEthernet(nil, DefaultGatewayMAC, guestMAC, 0x8100, make([]byte, 60)),            // VLAN
		pkt.AppendEthernet(nil, DefaultGatewayMAC, guestMAC, pkt.EtherTypeIPv4, ip[:10]),          // truncated IP
		{1, 2, 3}, // runt
	}
	for _, f := range bad {
		h.guest.send(f)
	}
	h.guest.send(pkt.AppendEthernet(nil, DefaultGatewayMAC, guestMAC, pkt.EtherTypeIPv4, ip)) // sentinel
	select {
	case got := <-h.packet:
		if string(got) != string(ip) {
			t.Fatalf("wrong packet forwarded")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("sentinel not forwarded")
	}
	select {
	case extra := <-h.packet:
		t.Fatalf("a frame that should have been dropped was forwarded: %x", extra)
	case <-time.After(200 * time.Millisecond):
	}
	s := h.br.Stats()
	if s.ForwardedToTun != 1 || s.DroppedIPv6 != 1 || s.DroppedNotForUs != 2 || s.DroppedOther != 1 || s.DroppedMalformed != 2 {
		t.Fatalf("unexpected stats: %s", s)
	}
}

func TestTunnelToGuest(t *testing.T) {
	h := newHarness(t, Config{})
	ip := pkt.BuildIPv4UDP(netip.MustParseAddr("10.0.0.53"), guestIP, 53, 4000, 9, []byte("answer"))

	// Before the guest MAC is known the packet cannot be delivered.
	if err := h.br.WriteIP(ip); err != nil {
		t.Fatal(err)
	}
	if _, ok := h.guest.recv(200 * time.Millisecond); ok {
		t.Fatal("delivered a packet before learning the guest MAC")
	}
	if h.br.Stats().DroppedNoGuest != 1 {
		t.Fatalf("DroppedNoGuest = %d", h.br.Stats().DroppedNoGuest)
	}

	// Learn the MAC (ARP is enough) and try again, using the QEMU return address
	// learned from the frame rather than the configured one.
	h.guest.send(arpRequest(guestIP, netip.MustParseAddr("10.0.0.254")))
	if _, ok := h.guest.recv(2 * time.Second); !ok {
		t.Fatal("no ARP reply")
	}
	if err := h.br.WriteIP(ip); err != nil {
		t.Fatal(err)
	}
	f, ok := h.guest.recv(2 * time.Second)
	if !ok {
		t.Fatal("packet not delivered to guest")
	}
	eth, _ := pkt.ParseEthernet(f)
	if eth.Dst != guestMAC || eth.Src != DefaultGatewayMAC || eth.Type != pkt.EtherTypeIPv4 || string(eth.Payload) != string(ip) {
		t.Fatalf("bad frame: %+v", eth)
	}

	// IPv6 from the tunnel is dropped without error.
	v6 := append([]byte{0x60}, make([]byte, 60)...)
	if err := h.br.WriteIP(v6); err != nil {
		t.Fatal(err)
	}
	if _, ok := h.guest.recv(200 * time.Millisecond); ok {
		t.Fatal("IPv6 was delivered")
	}
}

func TestSendErrorsDoNotBreakTunnel(t *testing.T) {
	h := newHarness(t, Config{})
	h.guest.send(arpRequest(guestIP, netip.MustParseAddr("10.0.0.254")))
	if _, ok := h.guest.recv(2 * time.Second); !ok {
		t.Fatal("no ARP reply")
	}
	h.guest.conn.Close() // QEMU goes away
	os.Remove(h.guest.conn.LocalAddr().String())
	ip := pkt.BuildIPv4UDP(netip.MustParseAddr("10.0.0.53"), guestIP, 53, 4000, 9, []byte("x"))
	if err := h.br.WriteIP(ip); err != nil {
		t.Fatalf("WriteIP must swallow transient send errors, got %v", err)
	}
	if h.br.Stats().SendErrors == 0 {
		t.Fatal("send error not counted")
	}
}

func TestCloseUnblocksReadAndRemovesSocket(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "b.sock")
	br, err := Listen(path, Config{})
	if err != nil {
		t.Fatal(err)
	}
	res := make(chan error, 1)
	go func() { _, err := br.ReadIPv4(make([]byte, 2048)); res <- err }()
	time.Sleep(50 * time.Millisecond)
	if err := br.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-res:
		if !errors.Is(err, os.ErrClosed) {
			t.Fatalf("ReadIPv4 error = %v, want os.ErrClosed", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("ReadIPv4 did not unblock")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("socket file still present: %v", err)
	}
	if err := br.WriteIP(make([]byte, 40)); !errors.Is(err, os.ErrClosed) {
		t.Fatalf("WriteIP after Close = %v", err)
	}
	if err := br.Close(); err != nil {
		t.Fatalf("second Close: %v", err)
	}
}

func TestListenReplacesStaleSocketButNotOtherFiles(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "b.sock")
	br1, err := Listen(path, Config{})
	if err != nil {
		t.Fatal(err)
	}
	// Simulate a crash: the socket file stays behind, nobody is listening.
	br1.sockPath = ""
	br1.Close()
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("expected stale socket file: %v", err)
	}
	br2, err := Listen(path, Config{})
	if err != nil {
		t.Fatalf("stale socket not replaced: %v", err)
	}
	br2.Close()

	regular := filepath.Join(dir, "regular")
	os.WriteFile(regular, []byte("x"), 0o600)
	if _, err := Listen(regular, Config{}); err == nil {
		t.Fatal("clobbered a regular file")
	}
}

func TestRejectsMulticastGatewayMAC(t *testing.T) {
	_, err := Listen(filepath.Join(t.TempDir(), "b.sock"), Config{GatewayMAC: pkt.Broadcast})
	if err == nil {
		t.Fatal("accepted broadcast gateway MAC")
	}
}
