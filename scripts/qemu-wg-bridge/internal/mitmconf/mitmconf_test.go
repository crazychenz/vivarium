package mitmconf

import (
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// RFC 7748 section 6.1 test vectors (X25519 base point multiplication).
func TestPublicRFC7748(t *testing.T) {
	for _, v := range []struct{ priv, pub string }{
		{"77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a", "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"},
		{"5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb", "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"},
	} {
		pb, _ := hex.DecodeString(v.priv)
		var priv Key
		copy(priv[:], pb)
		pub, err := Public(priv)
		if err != nil {
			t.Fatal(err)
		}
		if pub.Hex() != v.pub {
			t.Fatalf("Public(%s) = %s, want %s", v.priv, pub.Hex(), v.pub)
		}
	}
}

func TestLoad(t *testing.T) {
	dir := t.TempDir()
	// Same shape as the file mitmproxy writes.
	good := `{
    "server_key": "P2wJ7oQY0w0k0b1dXWmVn9x8wG3m7pXKQ5mP2t2h1Wk=",
    "client_key": "zVVBUWRFm+4aj8WccQws3T+YlZ5Nl2vz01KPdAVMEs0="
}`
	p := filepath.Join(dir, "wireguard.conf")
	os.WriteFile(p, []byte(good), 0o600)
	k, err := Load(p)
	if err != nil {
		t.Fatal(err)
	}
	if k.ClientPrivate.Base64() != "zVVBUWRFm+4aj8WccQws3T+YlZ5Nl2vz01KPdAVMEs0=" {
		t.Fatal("client key mangled")
	}
	if k.ServerPublic == (Key{}) || k.ServerPublic == k.ServerPrivate || k.ClientPublic == k.ServerPublic {
		t.Fatal("public keys not derived")
	}
	if len(k.ServerPublic.Hex()) != 64 {
		t.Fatalf("hex length %d", len(k.ServerPublic.Hex()))
	}
}

func TestLoadErrors(t *testing.T) {
	dir := t.TempDir()
	cases := map[string]string{
		"not json":       `nope`,
		"missing client": `{"server_key": "P2wJ7oQY0w0k0b1dXWmVn9x8wG3m7pXKQ5mP2t2h1Wk="}`,
		"bad base64":     `{"server_key": "!!!", "client_key": "!!!"}`,
		"short key":      `{"server_key": "AAAA", "client_key": "AAAA"}`,
	}
	for name, body := range cases {
		p := filepath.Join(dir, strings.ReplaceAll(name, " ", "_"))
		os.WriteFile(p, []byte(body), 0o600)
		if _, err := Load(p); err == nil {
			t.Errorf("%s: expected error", name)
		}
	}
	if _, err := Load(filepath.Join(dir, "missing")); err == nil {
		t.Error("expected error for missing file")
	}
}
