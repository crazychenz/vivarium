//go:build !wgoldapi

package main

// This is the tun.Device API of current wireguard-go (the batched one, as
// fetched by `go get golang.zx2c4.com/wireguard@latest`).

// BatchSize is 1: the QEMU socket delivers one frame per datagram.
func (t *qemuTUN) BatchSize() int { return 1 }

// Read returns one IP packet from the guest, placed at bufs[0][offset:].
func (t *qemuTUN) Read(bufs [][]byte, sizes []int, offset int) (int, error) {
	n, err := t.br.ReadIPv4(bufs[0][offset:])
	if err != nil {
		return 0, err
	}
	sizes[0] = n
	return 1, nil
}

// Write sends decrypted IP packets (found at b[offset:]) to the guest.
func (t *qemuTUN) Write(bufs [][]byte, offset int) (int, error) {
	for i, b := range bufs {
		if err := t.br.WriteIP(b[offset:]); err != nil {
			return i, err
		}
	}
	return len(bufs), nil
}
