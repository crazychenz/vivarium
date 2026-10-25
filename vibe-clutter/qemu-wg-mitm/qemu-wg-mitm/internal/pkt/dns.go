package pkt

import (
	"encoding/binary"
	"errors"
	"fmt"
	"net/netip"
	"strings"
)

// DNS record types used by the fake guest.
const (
	TypeA     uint16 = 1
	TypeCNAME uint16 = 5
	TypeAAAA  uint16 = 28
)

// BuildDNSQuery builds a standard recursive query for name/qtype.
func BuildDNSQuery(id uint16, name string, qtype uint16) ([]byte, error) {
	b := make([]byte, 12, 12+len(name)+6)
	binary.BigEndian.PutUint16(b[0:2], id)
	binary.BigEndian.PutUint16(b[2:4], 0x0100) // RD
	binary.BigEndian.PutUint16(b[4:6], 1)      // QDCOUNT
	for _, label := range strings.Split(strings.TrimSuffix(name, "."), ".") {
		if len(label) == 0 || len(label) > 63 {
			return nil, fmt.Errorf("invalid DNS name %q", name)
		}
		b = append(b, byte(len(label)))
		b = append(b, label...)
	}
	b = append(b, 0, byte(qtype>>8), byte(qtype), 0, 1) // root, QTYPE, QCLASS=IN
	return b, nil
}

// DNSAnswer is one resource record from a response.
type DNSAnswer struct {
	Name string
	Type uint16
	TTL  uint32
	Data string // dotted/colon form for A/AAAA, target name for CNAME, hex otherwise
}

// DNSResponse is the part of a DNS response the smoke test cares about.
type DNSResponse struct {
	ID      uint16
	RCode   int
	Answers []DNSAnswer
}

var errTruncated = errors.New("truncated DNS message")

// ParseDNSResponse parses a DNS response, following name compression.
func ParseDNSResponse(msg []byte) (DNSResponse, error) {
	if len(msg) < 12 {
		return DNSResponse{}, errTruncated
	}
	var r DNSResponse
	r.ID = binary.BigEndian.Uint16(msg[0:2])
	flags := binary.BigEndian.Uint16(msg[2:4])
	if flags&0x8000 == 0 {
		return r, errors.New("not a response")
	}
	r.RCode = int(flags & 0x000f)
	qd := int(binary.BigEndian.Uint16(msg[4:6]))
	an := int(binary.BigEndian.Uint16(msg[6:8]))

	off := 12
	for i := 0; i < qd; i++ {
		_, n, err := readName(msg, off)
		if err != nil {
			return r, err
		}
		off = n + 4
		if off > len(msg) {
			return r, errTruncated
		}
	}
	for i := 0; i < an; i++ {
		name, n, err := readName(msg, off)
		if err != nil {
			return r, err
		}
		off = n
		if off+10 > len(msg) {
			return r, errTruncated
		}
		a := DNSAnswer{
			Name: name,
			Type: binary.BigEndian.Uint16(msg[off : off+2]),
			TTL:  binary.BigEndian.Uint32(msg[off+4 : off+8]),
		}
		rdlen := int(binary.BigEndian.Uint16(msg[off+8 : off+10]))
		off += 10
		if off+rdlen > len(msg) {
			return r, errTruncated
		}
		rd := msg[off : off+rdlen]
		switch {
		case a.Type == TypeA && rdlen == 4:
			a.Data = netip.AddrFrom4([4]byte(rd)).String()
		case a.Type == TypeAAAA && rdlen == 16:
			a.Data = netip.AddrFrom16([16]byte(rd)).String()
		case a.Type == TypeCNAME:
			a.Data, _, _ = readName(msg, off)
		default:
			a.Data = fmt.Sprintf("%x", rd)
		}
		off += rdlen
		r.Answers = append(r.Answers, a)
	}
	return r, nil
}

// readName decodes a possibly compressed name starting at off and returns it
// together with the offset of the first byte after the name in the original
// (uncompressed) position.
func readName(msg []byte, off int) (string, int, error) {
	var labels []string
	end, jumped, jumps := 0, false, 0
	for {
		if off >= len(msg) {
			return "", 0, errTruncated
		}
		c := int(msg[off])
		switch c & 0xc0 {
		case 0x00:
			off++
			if c == 0 {
				if !jumped {
					end = off
				}
				name := strings.Join(labels, ".")
				if name == "" {
					name = "."
				}
				return name, end, nil
			}
			if off+c > len(msg) {
				return "", 0, errTruncated
			}
			labels = append(labels, string(msg[off:off+c]))
			off += c
		case 0xc0:
			if off+1 >= len(msg) {
				return "", 0, errTruncated
			}
			if !jumped {
				end = off + 2
				jumped = true
			}
			if jumps++; jumps > 16 {
				return "", 0, errors.New("DNS compression loop")
			}
			off = (c&0x3f)<<8 | int(msg[off+1])
		default:
			return "", 0, errors.New("invalid DNS label")
		}
	}
}
