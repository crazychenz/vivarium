// Package pkt holds the small amount of Ethernet / ARP / IPv4 / UDP / DNS
// packet handling that the bridge and the fake guest need.
//
// Standard library only, so it builds and tests without any module downloads.
package pkt

import (
	"encoding/binary"
	"fmt"
	"net"
	"net/netip"
)

const (
	EtherTypeIPv4 uint16 = 0x0800
	EtherTypeARP  uint16 = 0x0806
	EtherTypeIPv6 uint16 = 0x86dd

	EthernetHeaderLen = 14
	ARPLen            = 28

	ARPRequest uint16 = 1
	ARPReply   uint16 = 2
)

// MAC is an Ethernet hardware address.
type MAC [6]byte

// Broadcast is ff:ff:ff:ff:ff:ff.
var Broadcast = MAC{0xff, 0xff, 0xff, 0xff, 0xff, 0xff}

// ParseMAC parses "aa:bb:cc:dd:ee:ff" style addresses.
func ParseMAC(s string) (MAC, error) {
	hw, err := net.ParseMAC(s)
	if err != nil {
		return MAC{}, err
	}
	if len(hw) != 6 {
		return MAC{}, fmt.Errorf("%q is not a 6-byte MAC address", s)
	}
	var m MAC
	copy(m[:], hw)
	return m, nil
}

func (m MAC) String() string { return net.HardwareAddr(m[:]).String() }

// IsZero reports whether m is 00:00:00:00:00:00.
func (m MAC) IsZero() bool { return m == MAC{} }

// IsMulticast reports whether the group bit is set (this includes broadcast).
func (m MAC) IsMulticast() bool { return m[0]&1 != 0 }

// Ethernet is a parsed Ethernet II header plus payload. Payload aliases the
// frame it was parsed from.
type Ethernet struct {
	Dst, Src MAC
	Type     uint16
	Payload  []byte
}

// ParseEthernet parses an Ethernet II frame (no VLAN tag handling: a tagged
// frame simply shows up with Type 0x8100).
func ParseEthernet(frame []byte) (Ethernet, bool) {
	if len(frame) < EthernetHeaderLen {
		return Ethernet{}, false
	}
	var e Ethernet
	copy(e.Dst[:], frame[0:6])
	copy(e.Src[:], frame[6:12])
	e.Type = binary.BigEndian.Uint16(frame[12:14])
	e.Payload = frame[EthernetHeaderLen:]
	return e, true
}

// AppendEthernet appends an Ethernet II header followed by payload to b.
func AppendEthernet(b []byte, dst, src MAC, etherType uint16, payload []byte) []byte {
	b = append(b, dst[:]...)
	b = append(b, src[:]...)
	b = append(b, byte(etherType>>8), byte(etherType))
	return append(b, payload...)
}

// ARP is an Ethernet/IPv4 ARP message.
type ARP struct {
	Op        uint16
	SenderMAC MAC
	SenderIP  netip.Addr
	TargetMAC MAC
	TargetIP  netip.Addr
}

// ParseARP parses an Ethernet/IPv4 ARP message (anything else is rejected).
func ParseARP(b []byte) (ARP, bool) {
	if len(b) < ARPLen {
		return ARP{}, false
	}
	if binary.BigEndian.Uint16(b[0:2]) != 1 || // hardware type: Ethernet
		binary.BigEndian.Uint16(b[2:4]) != EtherTypeIPv4 ||
		b[4] != 6 || b[5] != 4 {
		return ARP{}, false
	}
	var a ARP
	a.Op = binary.BigEndian.Uint16(b[6:8])
	copy(a.SenderMAC[:], b[8:14])
	a.SenderIP = netip.AddrFrom4([4]byte(b[14:18]))
	copy(a.TargetMAC[:], b[18:24])
	a.TargetIP = netip.AddrFrom4([4]byte(b[24:28]))
	return a, true
}

// Marshal encodes the ARP message (28 bytes).
func (a ARP) Marshal() []byte {
	b := make([]byte, ARPLen)
	binary.BigEndian.PutUint16(b[0:2], 1)
	binary.BigEndian.PutUint16(b[2:4], EtherTypeIPv4)
	b[4], b[5] = 6, 4
	binary.BigEndian.PutUint16(b[6:8], a.Op)
	copy(b[8:14], a.SenderMAC[:])
	s := a.SenderIP.As4()
	copy(b[14:18], s[:])
	copy(b[18:24], a.TargetMAC[:])
	t := a.TargetIP.As4()
	copy(b[24:28], t[:])
	return b
}

// IPv4Len validates the IPv4 header at the start of b and returns the total
// length of the IP packet. Ethernet pads short frames to 60 bytes, so b may
// be longer than the packet; callers should trim to the returned length.
func IPv4Len(b []byte) (int, bool) {
	if len(b) < 20 || b[0]>>4 != 4 {
		return 0, false
	}
	ihl := int(b[0]&0x0f) * 4
	if ihl < 20 || len(b) < ihl {
		return 0, false
	}
	total := int(binary.BigEndian.Uint16(b[2:4]))
	if total < ihl || total > len(b) {
		return 0, false
	}
	return total, true
}

// Checksum returns the Internet checksum (RFC 1071) of b. Computed over data
// that already contains a correct checksum it returns 0.
func Checksum(b []byte) uint16 {
	return finish(sum(0, b))
}

func sum(acc uint32, b []byte) uint32 {
	for i := 0; i+1 < len(b); i += 2 {
		acc += uint32(binary.BigEndian.Uint16(b[i:]))
	}
	if len(b)%2 == 1 {
		acc += uint32(b[len(b)-1]) << 8
	}
	return acc
}

func finish(acc uint32) uint16 {
	for acc>>16 != 0 {
		acc = acc&0xffff + acc>>16
	}
	return ^uint16(acc)
}

func udpChecksum(src, dst [4]byte, udp []byte) uint16 {
	var ph [12]byte
	copy(ph[0:4], src[:])
	copy(ph[4:8], dst[:])
	ph[9] = 17
	binary.BigEndian.PutUint16(ph[10:12], uint16(len(udp)))
	c := finish(sum(sum(0, ph[:]), udp))
	if c == 0 {
		c = 0xffff
	}
	return c
}

// BuildIPv4UDP builds a complete IPv4+UDP packet with valid checksums.
func BuildIPv4UDP(src, dst netip.Addr, sport, dport, id uint16, payload []byte) []byte {
	total := 20 + 8 + len(payload)
	p := make([]byte, total)
	p[0] = 0x45
	binary.BigEndian.PutUint16(p[2:4], uint16(total))
	binary.BigEndian.PutUint16(p[4:6], id)
	binary.BigEndian.PutUint16(p[6:8], 0x4000) // DF
	p[8] = 64                                  // TTL
	p[9] = 17                                  // UDP
	s, d := src.As4(), dst.As4()
	copy(p[12:16], s[:])
	copy(p[16:20], d[:])
	binary.BigEndian.PutUint16(p[10:12], Checksum(p[:20]))

	u := p[20:]
	binary.BigEndian.PutUint16(u[0:2], sport)
	binary.BigEndian.PutUint16(u[2:4], dport)
	binary.BigEndian.PutUint16(u[4:6], uint16(8+len(payload)))
	copy(u[8:], payload)
	binary.BigEndian.PutUint16(u[6:8], udpChecksum(s, d, u))
	return p
}

// UDPv4 is a parsed IPv4/UDP packet. Payload aliases the packet.
type UDPv4 struct {
	Src, Dst         netip.Addr
	SrcPort, DstPort uint16
	Payload          []byte
}

// ParseIPv4UDP parses an unfragmented IPv4/UDP packet and verifies the IP
// header checksum.
func ParseIPv4UDP(p []byte) (UDPv4, bool) {
	total, ok := IPv4Len(p)
	if !ok || p[9] != 17 {
		return UDPv4{}, false
	}
	ihl := int(p[0]&0x0f) * 4
	if Checksum(p[:ihl]) != 0 {
		return UDPv4{}, false
	}
	if binary.BigEndian.Uint16(p[6:8])&0x3fff != 0 { // MF flag or fragment offset
		return UDPv4{}, false
	}
	u := p[ihl:total]
	if len(u) < 8 {
		return UDPv4{}, false
	}
	ulen := int(binary.BigEndian.Uint16(u[4:6]))
	if ulen < 8 || ulen > len(u) {
		return UDPv4{}, false
	}
	return UDPv4{
		Src:     netip.AddrFrom4([4]byte(p[12:16])),
		Dst:     netip.AddrFrom4([4]byte(p[16:20])),
		SrcPort: binary.BigEndian.Uint16(u[0:2]),
		DstPort: binary.BigEndian.Uint16(u[2:4]),
		Payload: u[8:ulen],
	}, true
}
