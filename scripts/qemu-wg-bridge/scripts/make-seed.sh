#!/usr/bin/env bash
# Build the cloud-init "NoCloud" seed ISO (vm/seed.iso) for the guest.
#
# What it configures inside the guest:
#   * the tunnel NIC (MAC $TUNNEL_MAC): static 10.0.0.1/24, default route via the
#     bridge, DNS = mitmproxy's 10.0.0.53, MTU 1420, no IPv6
#   * optionally a management NIC (MAC $MGMT_MAC) used only for SSH from the host
#   * the mitmproxy CA in the system trust store, plus env vars for runtimes that
#     bring their own (Python requests, Node, curl) in /etc/profile.d
#   * a user (default dev/dev) with passwordless sudo and your SSH public key
#
# Environment: VM_USER, VM_PASSWORD (empty = no password login), SSH_PUBKEY_FILE,
# MGMT (1/0), MITM_CONFDIR, VM_DIR ... (see lib.sh)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

VM_USER=${VM_USER:-dev}
VM_PASSWORD=${VM_PASSWORD-dev}
MGMT=${MGMT:-1}
CA=$MITM_CONFDIR/mitmproxy-ca-cert.pem
[ -f "$CA" ] || die "$CA not found; start ./scripts/start-mitmproxy.sh once so it creates its CA"

pubkey=${SSH_PUBKEY_FILE:-}
if [ -z "$pubkey" ]; then
  for f in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_ecdsa.pub" "$HOME/.ssh/id_rsa.pub"; do
    [ -f "$f" ] && { pubkey=$f; break; }
  done
fi
[ -z "$pubkey" ] || [ -f "$pubkey" ] || die "SSH_PUBKEY_FILE=$pubkey does not exist"
[ -n "$pubkey" ] || [ -n "$VM_PASSWORD" ] || die "no SSH public key found and VM_PASSWORD is empty: you would have no way to log in"

work=$VM_DIR/seed
rm -rf "$work"; mkdir -p "$work"

# ---- user-data ------------------------------------------------------------
{
  echo "#cloud-config"
  echo "hostname: mitm-guest"
  echo "manage_etc_hosts: true"
  echo "users:"
  echo "  - name: $VM_USER"
  echo "    groups: [sudo]"
  echo "    shell: /bin/bash"
  echo "    sudo: ALL=(ALL) NOPASSWD:ALL"
  if [ -n "$VM_PASSWORD" ]; then
    echo "    lock_passwd: false"
  else
    echo "    lock_passwd: true"
  fi
  if [ -n "$pubkey" ]; then
    echo "    ssh_authorized_keys:"
    echo "      - $(cat "$pubkey")"
  fi
  if [ -n "$VM_PASSWORD" ]; then
    echo "ssh_pwauth: true"
    echo "chpasswd:"
    echo "  expire: false"
    echo "  users:"
    echo "    - {name: $VM_USER, password: \"$VM_PASSWORD\", type: text}"
  else
    echo "ssh_pwauth: false"
  fi
  cat <<EOF
package_update: false
package_upgrade: false
write_files:
  - path: /usr/local/share/ca-certificates/mitmproxy.crt
    permissions: "0644"
    encoding: b64
    content: $(b64 "$CA")
  - path: /etc/profile.d/mitmproxy-ca.sh
    permissions: "0644"
    content: |
      # Runtimes that do not use the system trust store: point them at the bundle
      # that includes the mitmproxy CA (login shells only).
      export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
      export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
      export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
      export NODE_EXTRA_CA_CERTS=/usr/local/share/ca-certificates/mitmproxy.crt
  - path: /etc/sysctl.d/99-no-ipv6.conf
    permissions: "0644"
    content: |
      net.ipv6.conf.all.disable_ipv6 = 1
      net.ipv6.conf.default.disable_ipv6 = 1
runcmd:
  - [update-ca-certificates]
  - [sysctl, -p, /etc/sysctl.d/99-no-ipv6.conf]
EOF
} > "$work/user-data"

# ---- network-config (netplan v2) -----------------------------------------------
{
  cat <<EOF
version: 2
ethernets:
  tunnel:
    match: {macaddress: "$TUNNEL_MAC"}
    set-name: tunnel0
    dhcp4: false
    dhcp6: false
    accept-ra: false
    link-local: []
    addresses: [$GUEST_IP/24]
    mtu: $TUNNEL_MTU
    routes:
      - {to: default, via: $GATEWAY_IP}
    nameservers:
      addresses: [$DNS_IP]
EOF
  if [ "$MGMT" = 1 ]; then
    cat <<EOF
  mgmt:
    match: {macaddress: "$MGMT_MAC"}
    set-name: mgmt0
    dhcp4: true
    dhcp4-overrides: {use-routes: false, use-dns: false, use-ntp: false, use-hostname: false}
    dhcp6: false
    accept-ra: false
    link-local: []
EOF
  fi
} > "$work/network-config"

# A new instance-id makes cloud-init apply changed config on an existing disk.
iid="iid-$(cat "$work/user-data" "$work/network-config" | { sha256sum 2>/dev/null || shasum -a 256; } | cut -c1-12)"
printf 'instance-id: %s\nlocal-hostname: mitm-guest\n' "$iid" > "$work/meta-data"

# ---- ISO ---------------------------------------------------------------------------
out=$VM_DIR/seed.iso
rm -f "$out"
if command -v cloud-localds >/dev/null 2>&1; then
  cloud-localds -N "$work/network-config" "$out" "$work/user-data" "$work/meta-data"
else
  mk=""
  for c in genisoimage mkisofs; do command -v "$c" >/dev/null 2>&1 && { mk=$c; break; }; done
  if [ -n "$mk" ]; then
    "$mk" -quiet -output "$out" -volid cidata -joliet -rock "$work/user-data" "$work/meta-data" "$work/network-config"
  elif command -v xorriso >/dev/null 2>&1; then
    xorriso -as mkisofs -quiet -o "$out" -V cidata -J -r "$work/user-data" "$work/meta-data" "$work/network-config"
  else
    die "need one of: cloud-localds (cloud-image-utils), genisoimage, mkisofs (cdrtools), xorriso"
  fi
fi
echo "seed: $out (instance-id $iid, user $VM_USER${VM_PASSWORD:+, password login on}${pubkey:+, key $pubkey})" >&2
