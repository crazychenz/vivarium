package main

import (
	"os"
	"sync"

	"golang.zx2c4.com/wireguard/tun"

	"qemu-wg-mitm/internal/ethbridge"
)

// qemuTUN makes an ethbridge.Bridge look like a wireguard-go tun.Device, so
// wireguard-go reads the guest's IP packets from, and writes decrypted tunnel
// packets to, QEMU's network socket instead of a kernel TUN interface.
//
// The version-specific Read/Write methods live in tun_batch.go (current
// wireguard-go) and tun_legacy.go (-tags wgoldapi, for the pre-2023 API that
// Debian/Ubuntu package).
type qemuTUN struct {
	br     *ethbridge.Bridge
	mtu    int
	events chan tun.Event
	once   sync.Once
}

func newQemuTUN(br *ethbridge.Bridge, mtu int) *qemuTUN {
	return &qemuTUN{br: br, mtu: mtu, events: make(chan tun.Event, 1)}
}

// File returns nil: there is no file descriptor behind this device.
// (wireguard-go only uses it in its own main(), never in the library.)
func (t *qemuTUN) File() *os.File { return nil }

func (t *qemuTUN) MTU() (int, error)     { return t.mtu, nil }
func (t *qemuTUN) Name() (string, error) { return "qemu-bridge", nil }

// Events is a channel that is closed on Close; wireguard-go's event worker
// exits when it is closed. We never send events: main calls Device.Up itself.
func (t *qemuTUN) Events() <-chan tun.Event { return t.events }

// Close stops the device. Closing the bridge unblocks a pending Read, which
// then returns os.ErrClosed, which is how wireguard-go knows to stop quietly.
func (t *qemuTUN) Close() error {
	var err error
	t.once.Do(func() {
		close(t.events)
		err = t.br.Close()
	})
	return err
}
