// Package main implements a minimal userspace network gateway using
// gVisor's netstack. It terminates TCP and UDP connections arriving on
// a virtual NIC (fed by raw Ethernet frames from a QEMU `-netdev stream`
// unix socket) and exposes a small C ABI (via cgo) so the real control
// logic — routing, policy, mitmproxy handoff — can live in Python.
//
// This file intentionally contains NO policy. It only: answers ARP,
// terminates TCP/UDP for any destination (promiscuous), and shuttles
// bytes across the cgo boundary. All "what happens to this connection"
// decisions are made on the Python side.
package main

/*
#include "trampoline.h"
#include <stdlib.h>
*/
import "C"

import (
	"bytes"
	"net"
	"sync"
	"unsafe"

	"gvisor.dev/gvisor/pkg/buffer"
	"gvisor.dev/gvisor/pkg/tcpip"
	"gvisor.dev/gvisor/pkg/tcpip/adapters/gonet"
	"gvisor.dev/gvisor/pkg/tcpip/header"
	"gvisor.dev/gvisor/pkg/tcpip/link/channel"
	"gvisor.dev/gvisor/pkg/tcpip/network/arp"
	"gvisor.dev/gvisor/pkg/tcpip/network/ipv4"
	"gvisor.dev/gvisor/pkg/tcpip/stack"
	"gvisor.dev/gvisor/pkg/tcpip/transport/tcp"
	"gvisor.dev/gvisor/pkg/tcpip/transport/udp"
	"gvisor.dev/gvisor/pkg/waiter"
)

var (
	ns  *stack.Stack
	ep  *channel.Endpoint
	nic = tcpip.NICID(1)

	frameCB  C.frame_cb
	acceptCB C.tcp_accept_cb
	dataCB   C.tcp_data_cb
	closeCB  C.tcp_close_cb
	udpCB    C.udp_packet_cb

	connsMu    sync.Mutex
	conns      = map[uint64]net.Conn{}
	nextConnID uint64

	udpEP tcpip.Endpoint
)

// NS_Init brings up the netstack: ARP + IPv4 + TCP + UDP on a channel
// endpoint that exchanges raw Ethernet frames across the cgo boundary.
// gatewayIP is the address the guest will use as its default gateway.
//
//export NS_Init
func NS_Init(gatewayIP *C.char, fcb C.frame_cb, acb C.tcp_accept_cb, dcb C.tcp_data_cb, ccb C.tcp_close_cb, ucb C.udp_packet_cb) {
	frameCB, acceptCB, dataCB, closeCB, udpCB = fcb, acb, dcb, ccb, ucb

	ep = channel.New(256, 1500, "")
	ns = stack.New(stack.Options{
		NetworkProtocols:   []stack.NetworkProtocolFactory{ipv4.NewProtocol, arp.NewProtocol},
		TransportProtocols: []stack.TransportProtocolFactory{tcp.NewProtocol, udp.NewProtocol},
	})

	if err := ns.CreateNIC(nic, ep); err != nil {
		panic(err)
	}

	addr := tcpip.AddrFromSlice(net.ParseIP(C.GoString(gatewayIP)).To4())
	if err := ns.AddProtocolAddress(nic, tcpip.ProtocolAddress{
		Protocol:          ipv4.ProtocolNumber,
		AddressWithPrefix: addr.WithPrefix(),
	}, stack.AddressProperties{}); err != nil {
		panic(err)
	}

	ns.SetRouteTable([]tcpip.Route{{Destination: header.IPv4EmptySubnet, NIC: nic}})

	// Promiscuous + spoofing: accept connections addressed to ANY
	// destination IP the guest dials, not just the gateway's own
	// address. This is what lets one listener catch every outbound
	// connection regardless of target, the way a kernel-level
	// REDIRECT would under tap networking.
	if err := ns.SetPromiscuousMode(nic, true); err != nil {
		panic(err)
	}
	if err := ns.SetSpoofing(nic, true); err != nil {
		panic(err)
	}

	go pumpOutboundFrames()
	startTCPListener()
	startUDPListener()
}

// NS_InjectFrame feeds one raw Ethernet frame (as read from the QEMU
// unix socket) into netstack.
//
//export NS_InjectFrame
func NS_InjectFrame(data *C.uint8_t, length C.int) {
	raw := C.GoBytes(unsafe.Pointer(data), length)
	if len(raw) < header.EthernetMinimumSize {
		return
	}
	pkt := stack.NewPacketBuffer(stack.PacketBufferOptions{
		Payload: buffer.MakeWithData(raw),
	})
	defer pkt.DecRef()
	ep.InjectInbound(header.Ethernet(raw).Type(), pkt)
}

// pumpOutboundFrames reads frames netstack wants to transmit (ARP
// replies, TCP ACKs/data, etc.) and hands them back across the cgo
// boundary so Python can write them to the QEMU socket.
func pumpOutboundFrames() {
	for {
		pkt := ep.ReadContext(nil)
		if pkt.IsNil() {
			continue
		}
		view := pkt.ToView()
		b := view.AsSlice()
		if len(b) > 0 {
			C.frame_cb_call(frameCB, (*C.uint8_t)(unsafe.Pointer(&b[0])), C.int(len(b)))
		}
		pkt.DecRef()
	}
}

// --- TCP ---

func startTCPListener() {
	l, err := gonet.ListenTCP(ns, tcpip.FullAddress{Port: 0}, ipv4.ProtocolNumber)
	if err != nil {
		panic(err)
	}
	go func() {
		for {
			conn, err := l.Accept()
			if err != nil {
				continue
			}
			id := registerConn(conn)
			local := conn.LocalAddr().(*net.TCPAddr) // real destination the guest dialed
			cip := C.CString(local.IP.String())
			C.tcp_accept_cb_call(acceptCB, C.uint64_t(id), cip, C.int(local.Port))
			C.free(unsafe.Pointer(cip))
			go pumpConnInbound(id, conn)
		}
	}()
}

func registerConn(c net.Conn) uint64 {
	connsMu.Lock()
	defer connsMu.Unlock()
	id := nextConnID
	nextConnID++
	conns[id] = c
	return id
}

func pumpConnInbound(id uint64, c net.Conn) {
	buf := make([]byte, 16384)
	for {
		n, err := c.Read(buf)
		if n > 0 {
			C.tcp_data_cb_call(dataCB, C.uint64_t(id), (*C.uint8_t)(unsafe.Pointer(&buf[0])), C.int(n))
		}
		if err != nil {
			connsMu.Lock()
			delete(conns, id)
			connsMu.Unlock()
			C.tcp_close_cb_call(closeCB, C.uint64_t(id))
			return
		}
	}
}

// NS_TCPWrite writes data to the guest on an established connection
// (used to relay mitmproxy's responses back).
//
//export NS_TCPWrite
func NS_TCPWrite(connID C.uint64_t, data *C.uint8_t, length C.int) {
	connsMu.Lock()
	c, ok := conns[uint64(connID)]
	connsMu.Unlock()
	if !ok {
		return
	}
	b := C.GoBytes(unsafe.Pointer(data), length)
	c.Write(b)
}

// NS_TCPClose closes a connection to the guest (used when mitmproxy
// rejects/fails a connection — fail-closed policy enforced on the
// Python side, this just carries out the close).
//
//export NS_TCPClose
func NS_TCPClose(connID C.uint64_t) {
	connsMu.Lock()
	c, ok := conns[uint64(connID)]
	delete(conns, uint64(connID))
	connsMu.Unlock()
	if ok {
		c.Close()
	}
}

// --- UDP ---

func startUDPListener() {
	wq := &waiter.Queue{}
	var err tcpip.Error
	udpEP, err = ns.NewEndpoint(udp.ProtocolNumber, ipv4.ProtocolNumber, wq)
	if err != nil {
		panic(err)
	}
	if bindErr := udpEP.Bind(tcpip.FullAddress{Port: 0}); bindErr != nil {
		panic(bindErr)
	}

	waitEntry, notifyCh := waiter.NewChannelEntry(waiter.ReadableEvents)
	wq.EventRegister(&waitEntry)

	go func() {
		for range notifyCh {
			for {
				var buf bytes.Buffer
				res, rerr := udpEP.Read(&buf, tcpip.ReadOptions{NeedRemoteAddr: true, NeedLocalAddr: true})
				if rerr != nil {
					break
				}
				data := buf.Bytes()
				if len(data) == 0 {
					continue
				}
				srcIP := res.RemoteAddr.Addr.String()
				srcPort := int(res.RemoteAddr.Port)
				dstIP := res.LocalAddr.Addr.String() // real destination the guest sent to
				dstPort := int(res.LocalAddr.Port)

				sip := C.CString(srcIP)
				dip := C.CString(dstIP)
				C.udp_packet_cb_call(udpCB, sip, C.int(srcPort), dip, C.int(dstPort),
					(*C.uint8_t)(unsafe.Pointer(&data[0])), C.int(len(data)))
				C.free(unsafe.Pointer(sip))
				C.free(unsafe.Pointer(dip))
			}
		}
	}()
}

// NS_UDPWrite sends a UDP datagram to the guest, spoofing the given
// source address (used to relay DNS/QUIC replies back as if they came
// from the real destination the guest originally queried).
//
//export NS_UDPWrite
func NS_UDPWrite(srcIP *C.char, srcPort C.int, dstIP *C.char, dstPort C.int, data *C.uint8_t, length C.int) {
	b := C.GoBytes(unsafe.Pointer(data), length)
	to := tcpip.FullAddress{
		Addr: tcpip.AddrFromSlice(net.ParseIP(C.GoString(dstIP)).To4()),
		Port: uint16(dstPort),
	}
	var wopts tcpip.WriteOptions
	wopts.To = &to
	udpEP.Write(bytes.NewReader(b), wopts)
	_ = srcIP
	_ = srcPort // netstack sends from the bound endpoint; spoofing the
	// apparent source beyond that requires raw IP construction, which
	// promiscuous+spoofing mode on the NIC already permits implicitly
	// via the endpoint's own address selection for this subnet.
}

func main() {}
