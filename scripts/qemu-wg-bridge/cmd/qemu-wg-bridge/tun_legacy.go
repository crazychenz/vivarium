//go:build wgoldapi

package main

// This is the pre-batching tun.Device API (wireguard-go up to early 2023),
// which is what Debian's and Ubuntu's golang-golang-zx2c4-wireguard-dev
// package ships. Build with: go build -tags wgoldapi  (see `make build-apt`).

// Read returns one IP packet from the guest, placed at buf[offset:].
func (t *qemuTUN) Read(buf []byte, offset int) (int, error) {
	return t.br.ReadIPv4(buf[offset:])
}

// Flush is part of the old interface; every Write is already sent immediately.
func (t *qemuTUN) Flush() error { return nil }

// Write sends one decrypted IP packet (found at buf[offset:]) to the guest.
func (t *qemuTUN) Write(buf []byte, offset int) (int, error) {
	if err := t.br.WriteIP(buf[offset:]); err != nil {
		return 0, err
	}
	return len(buf), nil
}
