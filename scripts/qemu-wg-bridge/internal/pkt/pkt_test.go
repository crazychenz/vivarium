package pkt

import (
	"bytes"
	"encoding/hex"
	"net/netip"
	"testing"
)

func TestARPRoundTrip(t *testing.T) {
	in := ARP{
		Op:        ARPRequest,
		SenderMAC: MAC{0x52, 0x54, 0, 0xaa, 0, 1},
		SenderIP:  netip.MustParseAddr("10.0.0.1"),
		TargetIP:  netip.MustParseAddr("10.0.0.254"),
	}
	b := in.Marshal()
	if len(b) != ARPLen {
		t.Fatalf("len = %d, want %d", len(b), ARPLen)
	}
	out, ok := ParseARP(b)
	if !ok || out != in {
		t.Fatalf("round trip mismatch: ok=%v got %+v want %+v", ok, out, in)
	}
	b[4] = 8 // bogus hardware address length
	if _, ok := ParseARP(b); ok {
		t.Fatal("accepted ARP with hlen=8")
	}
	if _, ok := ParseARP(b[:20]); ok {
		t.Fatal("accepted truncated ARP")
	}
}

func TestEthernet(t *testing.T) {
	dst, src := MAC{1, 2, 3, 4, 5, 6}, MAC{7, 8, 9, 10, 11, 12}
	f := AppendEthernet(nil, dst, src, EtherTypeIPv4, []byte{0xde, 0xad})
	e, ok := ParseEthernet(f)
	if !ok || e.Dst != dst || e.Src != src || e.Type != EtherTypeIPv4 || !bytes.Equal(e.Payload, []byte{0xde, 0xad}) {
		t.Fatalf("bad parse: %+v", e)
	}
	if _, ok := ParseEthernet(f[:13]); ok {
		t.Fatal("accepted runt frame")
	}
}

func TestMAC(t *testing.T) {
	m, err := ParseMAC("52:54:00:aa:00:01")
	if err != nil || m != (MAC{0x52, 0x54, 0, 0xaa, 0, 1}) {
		t.Fatalf("ParseMAC: %v %v", m, err)
	}
	if m.IsMulticast() || m.IsZero() {
		t.Fatal("unicast MAC misclassified")
	}
	if !Broadcast.IsMulticast() {
		t.Fatal("broadcast must be multicast-class")
	}
	if _, err := ParseMAC("00:11:22:33:44:55:66:77"); err == nil {
		t.Fatal("accepted 8-byte MAC")
	}
}

// RFC 1071 / well-known IPv4 header example.
func TestChecksumKnownVector(t *testing.T) {
	hdr, _ := hex.DecodeString("45000073000040004011" + "0000" + "c0a80001c0a800c7")
	if got := Checksum(hdr); got != 0xb861 {
		t.Fatalf("checksum = %#04x, want 0xb861", got)
	}
	hdr[10], hdr[11] = 0xb8, 0x61
	if got := Checksum(hdr); got != 0 {
		t.Fatalf("checksum over valid header = %#04x, want 0", got)
	}
}

func TestUDPBuildParse(t *testing.T) {
	src, dst := netip.MustParseAddr("10.0.0.1"), netip.MustParseAddr("10.0.0.53")
	for _, size := range []int{0, 1, 33, 1300} { // odd and even payload lengths
		payload := bytes.Repeat([]byte{0xab}, size)
		p := BuildIPv4UDP(src, dst, 40000, 53, 7, payload)
		if n, ok := IPv4Len(p); !ok || n != len(p) {
			t.Fatalf("size %d: IPv4Len = %d,%v want %d", size, n, ok, len(p))
		}
		u, ok := ParseIPv4UDP(p)
		if !ok || u.Src != src || u.Dst != dst || u.SrcPort != 40000 || u.DstPort != 53 || !bytes.Equal(u.Payload, payload) {
			t.Fatalf("size %d: bad parse %+v ok=%v", size, u, ok)
		}
		// Ethernet padding after the packet must be ignored.
		padded := append(append([]byte{}, p...), 0, 0, 0, 0)
		if n, ok := IPv4Len(padded); !ok || n != len(p) {
			t.Fatalf("size %d: padded IPv4Len = %d,%v want %d", size, n, ok, len(p))
		}
	}
	// A verified UDP checksum: pseudo-header + segment sums to zero.
	p := BuildIPv4UDP(src, dst, 1, 2, 3, []byte("hello"))
	s, d := src.As4(), dst.As4()
	var ph []byte
	ph = append(ph, s[:]...)
	ph = append(ph, d[:]...)
	ph = append(ph, 0, 17, 0, byte(len(p)-20))
	if got := Checksum(append(ph, p[20:]...)); got != 0 {
		t.Fatalf("UDP checksum does not verify: %#04x", got)
	}
}

func TestIPv4LenRejects(t *testing.T) {
	good := BuildIPv4UDP(netip.MustParseAddr("1.2.3.4"), netip.MustParseAddr("5.6.7.8"), 1, 2, 0, []byte("x"))
	cases := map[string][]byte{
		"empty":     nil,
		"short":     good[:19],
		"truncated": good[:len(good)-1], // total length > buffer
		"v6":        append([]byte{0x60}, good[1:]...),
		"ihl<5":     append([]byte{0x44}, good[1:]...),
	}
	for name, b := range cases {
		if _, ok := IPv4Len(b); ok {
			t.Errorf("%s: accepted", name)
		}
	}
}

func TestDNSQueryAndResponse(t *testing.T) {
	q, err := BuildDNSQuery(0x1234, "example.com.", TypeA)
	if err != nil {
		t.Fatal(err)
	}
	want, _ := hex.DecodeString("1234010000010000000000000765" + "78616d706c6503636f6d0000010001")
	if !bytes.Equal(q, want) {
		t.Fatalf("query = %x\nwant    %x", q, want)
	}
	if _, err := BuildDNSQuery(1, "bad..name", TypeA); err == nil {
		t.Fatal("accepted empty label")
	}

	// Response: question + CNAME www.example.com -> example.com (compressed),
	// then an A record for example.com using a compression pointer to offset 12.
	var r []byte
	r = append(r, 0x12, 0x34, 0x81, 0x80, 0, 1, 0, 2, 0, 0, 0, 0)
	r = append(r, q[12:]...)                                             // question section
	r = append(r, 0xc0, 0x0c, 0, 5, 0, 1, 0, 0, 0, 60, 0, 2, 0xc0, 0x0c) // CNAME -> pointer to example.com
	r = append(r, 0xc0, 0x0c, 0, 1, 0, 1, 0, 0, 1, 0, 0, 4, 93, 184, 216, 34)
	resp, err := ParseDNSResponse(r)
	if err != nil {
		t.Fatal(err)
	}
	if resp.ID != 0x1234 || resp.RCode != 0 || len(resp.Answers) != 2 {
		t.Fatalf("bad response: %+v", resp)
	}
	if a := resp.Answers[0]; a.Type != TypeCNAME || a.Data != "example.com" || a.Name != "example.com" {
		t.Fatalf("answer 0: %+v", a)
	}
	if a := resp.Answers[1]; a.Type != TypeA || a.Data != "93.184.216.34" || a.TTL != 256 {
		t.Fatalf("answer 1: %+v", a)
	}
}

func TestDNSParseRejectsGarbage(t *testing.T) {
	if _, err := ParseDNSResponse([]byte{1, 2, 3}); err == nil {
		t.Fatal("accepted 3 bytes")
	}
	q, _ := BuildDNSQuery(1, "a.b", TypeA)
	if _, err := ParseDNSResponse(q); err == nil {
		t.Fatal("accepted a query as a response")
	}
	// Pointer loop must not hang.
	loop := []byte{0, 1, 0x81, 0x80, 0, 1, 0, 0, 0, 0, 0, 0, 0xc0, 0x0c, 0, 1, 0, 1}
	if _, err := ParseDNSResponse(loop); err == nil {
		t.Fatal("accepted compression loop")
	}
}
