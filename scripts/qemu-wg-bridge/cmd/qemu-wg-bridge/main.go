// Command qemu-wg-bridge connects a QEMU virtual NIC to mitmproxy's WireGuard
// mode without a TAP device, root, or a hypervisor-side network stack.
//
//	guest NIC ──Ethernet frames──▶ unix socket ──▶ qemu-wg-bridge ──▶ wireguard-go
//	                                                                       │ UDP (WireGuard)
//	                                                                       ▼
//	                                                              mitmproxy --mode wireguard
//
// wireguard-go is used as a library: the "TUN device" it reads packets from
// and writes packets to is the QEMU socket (see tun.go and internal/ethbridge).
package main

import (
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	"golang.zx2c4.com/wireguard/conn"
	"golang.zx2c4.com/wireguard/device"

	"qemu-wg-mitm/internal/ethbridge"
	"qemu-wg-mitm/internal/mitmconf"
	"qemu-wg-mitm/internal/pkt"
)

func main() {
	var (
		sockPath   = flag.String("socket", "run/bridge.sock", "unix datagram socket to create (QEMU's remote.path)")
		peerPath   = flag.String("peer", "run/qemu.sock", "QEMU's own socket (its local.path); used until the first frame arrives")
		confPath   = flag.String("conf", "mitm-conf/wireguard.conf", "mitmproxy's WireGuard key file")
		endpoint   = flag.String("endpoint", "127.0.0.1:51820", "mitmproxy's WireGuard listener (host:port)")
		guestIP    = flag.String("guest-ip", "10.0.0.1", "the guest's IPv4 address (the bridge never answers ARP for it)")
		gwMAC      = flag.String("gateway-mac", ethbridge.DefaultGatewayMAC.String(), "MAC address the guest sees for its gateway")
		mtu        = flag.Int("mtu", 1420, "tunnel MTU (the guest NIC MTU must not exceed this)")
		keepalive  = flag.Int("keepalive", 25, "WireGuard persistent keepalive in seconds (0 = off)")
		verbose    = flag.Bool("v", false, "log every dropped frame and ARP reply")
		wgDebug    = flag.Bool("wg-debug", false, "verbose wireguard-go logging")
		statsEvery = flag.Duration("stats", 0, "log packet counters at this interval (0 = only at exit)")
	)
	flag.Parse()
	log.SetFlags(log.Ltime | log.Lmicroseconds)

	keys, err := mitmconf.Load(*confPath)
	if err != nil {
		log.Fatalf("cannot read mitmproxy's key file: %v\n(start mitmproxy once so it creates it, or pass -conf)", err)
	}
	ep, err := net.ResolveUDPAddr("udp4", *endpoint)
	if err != nil {
		log.Fatalf("bad -endpoint: %v", err)
	}
	cfg := ethbridge.Config{PeerPath: *peerPath, Logf: log.Printf, Verbose: *verbose}
	if cfg.GatewayMAC, err = pkt.ParseMAC(*gwMAC); err != nil {
		log.Fatalf("bad -gateway-mac: %v", err)
	}
	if cfg.GuestIP, err = parseAddr(*guestIP); err != nil {
		log.Fatalf("bad -guest-ip: %v", err)
	}

	br, err := ethbridge.Listen(*sockPath, cfg)
	if err != nil {
		log.Fatalf("cannot create %s: %v", *sockPath, err)
	}

	level := device.LogLevelError
	if *wgDebug {
		level = device.LogLevelVerbose
	}
	dev := device.NewDevice(newQemuTUN(br, *mtu), conn.NewDefaultBind(), device.NewLogger(level, "(wireguard) "))

	// The bridge is a WireGuard *client* of mitmproxy: it uses mitmproxy's
	// "client_key" as its own identity and trusts the public half of "server_key".
	// AllowedIPs 0.0.0.0/0 sends every IPv4 packet from the guest into the tunnel.
	ipc := fmt.Sprintf("private_key=%s\nreplace_peers=true\npublic_key=%s\nendpoint=%s\n"+
		"persistent_keepalive_interval=%d\nreplace_allowed_ips=true\nallowed_ip=0.0.0.0/0\n",
		keys.ClientPrivate.Hex(), keys.ServerPublic.Hex(), ep.String(), *keepalive)
	if err := dev.IpcSet(ipc); err != nil {
		log.Fatalf("configuring wireguard-go: %v", err)
	}
	if err := dev.Up(); err != nil {
		log.Fatalf("bringing wireguard-go up: %v", err)
	}

	log.Printf("bridge socket   %s   (QEMU: remote.path=%s)", *sockPath, *sockPath)
	log.Printf("gateway MAC     %s   (answers ARP for every address except %s)", cfg.GatewayMAC, cfg.GuestIP)
	log.Printf("WireGuard peer  %s   (mitmproxy server key %s)", ep, keys.ServerPublic.Base64())
	log.Printf("ready; waiting for the guest")

	if *statsEvery > 0 {
		go func() {
			for range time.Tick(*statsEvery) {
				log.Printf("counters: %s", br.Stats())
			}
		}()
	}

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	select {
	case s := <-sigs:
		log.Printf("%v: shutting down", s)
	case <-dev.Wait():
		log.Printf("wireguard-go stopped")
	}
	dev.Close()
	log.Printf("final counters: %s", br.Stats())
}
