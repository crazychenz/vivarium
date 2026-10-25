#!/usr/bin/env bash
# Start mitmproxy in WireGuard mode.
#
#   MITM_BIN=mitmdump ./scripts/start-mitmproxy.sh     # terminal output only
#   ./scripts/start-mitmproxy.sh                       # mitmweb: UI on http://127.0.0.1:8081
#
# The first run creates <MITM_CONFDIR>/wireguard.conf (the WireGuard keys) and
# the mitmproxy CA (mitmproxy-ca-cert.pem). Extra arguments are passed on to mitmproxy.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MITM_BIN=${MITM_BIN:-mitmweb}
need "$MITM_BIN"

mkdir -p "$MITM_CONFDIR"
[ -e "$MITM_CONFDIR/config.yaml" ] || cp "$ROOT/mitmproxy/config.yaml" "$MITM_CONFDIR/config.yaml"

args=(--set "confdir=$MITM_CONFDIR"
      --mode "wireguard:$MITM_CONFDIR/wireguard.conf@$WG_LISTEN")
case "$(basename "$MITM_BIN")" in
  mitmweb) args+=(--set web_open_browser=false) ;;
esac

echo "mitmproxy: WireGuard listener $WG_LISTEN, confdir $MITM_CONFDIR" >&2
echo "           guest CA to trust: $MITM_CONFDIR/mitmproxy-ca-cert.pem" >&2
exec "$MITM_BIN" "${args[@]}" "$@"
