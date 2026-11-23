// Package mitmconf reads the key file mitmproxy writes for its WireGuard mode
// (<confdir>/wireguard.conf) and derives the public keys from it.
package mitmconf

import (
	"crypto/ecdh"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
)

// Key is a 32-byte Curve25519 key.
type Key [32]byte

// Keys are the two key pairs in mitmproxy's wireguard.conf.
//
// mitmproxy plays the WireGuard *server*; whoever connects (our bridge) is the
// *client*. The bridge therefore needs ClientPrivate for itself and
// ServerPublic to authenticate mitmproxy.
type Keys struct {
	ServerPrivate, ServerPublic Key
	ClientPrivate, ClientPublic Key
}

// Load parses a wireguard.conf written by mitmproxy:
//
//	{"server_key": "<base64 private key>", "client_key": "<base64 private key>"}
func Load(path string) (*Keys, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f struct {
		ServerKey string `json:"server_key"`
		ClientKey string `json:"client_key"`
	}
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if f.ServerKey == "" || f.ClientKey == "" {
		return nil, fmt.Errorf("%s: expected both server_key and client_key", path)
	}
	var k Keys
	if k.ServerPrivate, err = ParseKey(f.ServerKey); err != nil {
		return nil, fmt.Errorf("%s: server_key: %w", path, err)
	}
	if k.ClientPrivate, err = ParseKey(f.ClientKey); err != nil {
		return nil, fmt.Errorf("%s: client_key: %w", path, err)
	}
	if k.ServerPublic, err = Public(k.ServerPrivate); err != nil {
		return nil, err
	}
	if k.ClientPublic, err = Public(k.ClientPrivate); err != nil {
		return nil, err
	}
	return &k, nil
}

// ParseKey decodes a base64 WireGuard key.
func ParseKey(s string) (Key, error) {
	var k Key
	b, err := base64.StdEncoding.DecodeString(s)
	if err != nil {
		return k, fmt.Errorf("invalid base64: %w", err)
	}
	if len(b) != len(k) {
		return k, errors.New("key must be 32 bytes")
	}
	copy(k[:], b)
	return k, nil
}

// Public derives the X25519 public key for a private key.
func Public(priv Key) (Key, error) {
	var pub Key
	sk, err := ecdh.X25519().NewPrivateKey(priv[:])
	if err != nil {
		return pub, err
	}
	copy(pub[:], sk.PublicKey().Bytes())
	return pub, nil
}

// Hex returns the lower-case hex form wireguard-go's configuration protocol uses.
func (k Key) Hex() string { return hex.EncodeToString(k[:]) }

// Base64 returns the form `wg` and mitmproxy print.
func (k Key) Base64() string { return base64.StdEncoding.EncodeToString(k[:]) }
