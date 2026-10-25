// Command fakeguest is a smoke test for the whole path
//
//	fakeguest ─Ethernet─▶ qemu-wg-bridge ─WireGuard─▶ mitmproxy ─▶ DNS ─▶ and back
//
// without a VM, root, or any network device. It plays the part QEMU plays:
// it binds a unix datagram socket, sends Ethernet frames to the bridge's
// socket, does ARP for the gateway, and then sends a DNS query to mitmproxy's
// WireGuard DNS address (10.0.0.53) and prints the answer.
//
// Start mitmproxy and the bridge first, then run it.
package main

import (
	"flag"
	"fmt"
	"log"
	"math/rand"
	"net"
	"net/netip"
	"os"
	"strings"
	"time"

	"qemu-wg-mitm/internal/pkt"
)

var rcodes = []string{"NOERROR", "FORMERR", "SERVFAIL", "NXDOMAIN", "NOTIMP", "REFUSED"}

func main() {
	var (
		sock    = flag.String("socket", "run/fakeguest.sock", "socket this tool binds (stands in for QEMU's local.path)")
		bridge  = flag.String("bridge", "run/bridge.sock", "the bridge's socket")
		macStr  = flag.String("guest-mac", "52:54:00:aa:00:99", "MAC address to use")
		ipStr   = flag.String("guest-ip", "10.0.0.1", "guest IPv4 address (mitmproxy's WireGuard client address)")
		gwStr   = flag.String("gw-ip", "10.0.0.254", "gateway address to ARP for")
		dnsStr  = flag.String("dns", "10.0.0.53", "DNS server to query (mitmproxy's WireGuard DNS address)")
		name    = flag.String("name", "example.com", "name to resolve")
		qtype   = flag.String("type", "A", "record type: A or AAAA")
		timeout = flag.Duration("timeout", 20*time.Second, "give up after this long")
	)
	flag.Parse()
	log.SetFlags(log.Ltime | log.Lmicroseconds)

	mac, err := pkt.ParseMAC(*macStr)
	check(err)
	guestIP, gwIP, dnsIP := netip.MustParseAddr(*ipStr), netip.MustParseAddr(*gwStr), netip.MustParseAddr(*dnsStr)
	qt := pkt.TypeA
	if strings.EqualFold(*qtype, "AAAA") {
		qt = pkt.TypeAAAA
	}

	_ = os.Remove(*sock)
	conn, err := net.ListenUnixgram("unixgram", &net.UnixAddr{Name: *sock, Net: "unixgram"})
	check(err)
	defer os.Remove(*sock)
	defer conn.Close()
	to := &net.UnixAddr{Name: *bridge, Net: "unixgram"}
	deadline := time.Now().Add(*timeout)

	// 1. ARP for the gateway.
	var gwMAC pkt.MAC
	for gwMAC.IsZero() {
		if time.Now().After(deadline) {
			log.Fatalf("FAIL: no ARP reply from the bridge at %s (is qemu-wg-bridge running?)", *bridge)
		}
		req := pkt.ARP{Op: pkt.ARPRequest, SenderMAC: mac, SenderIP: guestIP, TargetIP: gwIP}
		send(conn, to, pkt.AppendEthernet(nil, pkt.Broadcast, mac, pkt.EtherTypeARP, req.Marshal()))
		waitFor(conn, time.Now().Add(time.Second), func(e pkt.Ethernet) bool {
			if a, ok := pkt.ParseARP(e.Payload); ok && e.Type == pkt.EtherTypeARP && a.Op == pkt.ARPReply && a.SenderIP == gwIP {
				gwMAC = a.SenderMAC
				return true
			}
			return false
		})
	}
	fmt.Printf("ARP  %s is-at %s\n", gwIP, gwMAC)

	// 2. DNS query through the tunnel. The first packets can be lost while the
	//    WireGuard handshake completes, so retry until the deadline.
	srcPort := uint16(20000 + rand.Intn(20000))
	id := uint16(rand.Intn(65536))
	query, err := pkt.BuildDNSQuery(id, *name, qt)
	check(err)
	var resp *pkt.DNSResponse
	start := time.Now()
	for resp == nil {
		if time.Now().After(deadline) {
			log.Fatalf("FAIL: no DNS answer from %s within %v.\n"+
				"  Is mitmproxy running in WireGuard mode, and does the bridge log show matching keys / endpoint?", dnsIP, *timeout)
		}
		ip := pkt.BuildIPv4UDP(guestIP, dnsIP, srcPort, 53, uint16(rand.Intn(65536)), query)
		send(conn, to, pkt.AppendEthernet(nil, gwMAC, mac, pkt.EtherTypeIPv4, ip))
		waitFor(conn, time.Now().Add(3*time.Second), func(e pkt.Ethernet) bool {
			if e.Type != pkt.EtherTypeIPv4 {
				return false
			}
			total, ok := pkt.IPv4Len(e.Payload)
			if !ok {
				return false
			}
			u, ok := pkt.ParseIPv4UDP(e.Payload[:total])
			if !ok || u.SrcPort != 53 || u.DstPort != srcPort {
				return false
			}
			r, err := pkt.ParseDNSResponse(u.Payload)
			if err != nil || r.ID != id {
				return false
			}
			resp = &r
			return true
		})
	}

	rc := fmt.Sprintf("rcode %d", resp.RCode)
	if resp.RCode < len(rcodes) {
		rc = rcodes[resp.RCode]
	}
	fmt.Printf("DNS  %s %s via %s -> %s, %d answer(s) in %v\n", *name, *qtype, dnsIP, rc, len(resp.Answers), time.Since(start).Round(time.Millisecond))
	for _, a := range resp.Answers {
		fmt.Printf("       %s  type %d  ttl %d  %s\n", a.Name, a.Type, a.TTL, a.Data)
	}
	fmt.Println("OK   guest -> bridge -> WireGuard -> mitmproxy -> and back")
}

func send(c *net.UnixConn, to *net.UnixAddr, frame []byte) {
	if _, err := c.WriteToUnix(frame, to); err != nil {
		log.Fatalf("cannot send to %s: %v (is qemu-wg-bridge running?)", to.Name, err)
	}
}

// waitFor reads frames until match returns true or the deadline passes.
func waitFor(c *net.UnixConn, deadline time.Time, match func(pkt.Ethernet) bool) {
	buf := make([]byte, 65536)
	for {
		_ = c.SetReadDeadline(deadline)
		n, err := c.Read(buf)
		if err != nil {
			return
		}
		if e, ok := pkt.ParseEthernet(buf[:n]); ok && match(e) {
			return
		}
	}
}

func check(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
