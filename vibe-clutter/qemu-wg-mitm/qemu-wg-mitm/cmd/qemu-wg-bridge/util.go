package main

import (
	"fmt"
	"net/netip"
)

func parseAddr(s string) (netip.Addr, error) {
	a, err := netip.ParseAddr(s)
	if err != nil {
		return a, err
	}
	if !a.Is4() {
		return a, fmt.Errorf("%s is not an IPv4 address", s)
	}
	return a, nil
}
