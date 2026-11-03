#!/usr/bin/env bash
# Developed and iterated on with LLM: "Audie"
#
# virtcheck.sh - report what this account can do with podman and
# qemu-system-x86_64 by inspecting their prerequisites. Neither podman nor
# qemu is executed. The script only reads /proc, /sys, /etc, PATH and file
# metadata, and briefly opens a few /dev nodes to confirm access. It changes
# nothing.
#
# Usage: virtcheck.sh [--no-color] [--podman-only | --qemu-only]
#
# Exit status (bitmask): 0 = both usable, 1 = rootless podman blocked,
#                        2 = qemu blocked, 3 = both blocked.

set -u
export LC_ALL=C

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

USE_COLOR=1; DO_PODMAN=1; DO_QEMU=1
[ -t 1 ] || USE_COLOR=0
[ -n "${NO_COLOR:-}" ] && USE_COLOR=0
for arg in "$@"; do
  case $arg in
    --no-color)    USE_COLOR=0 ;;
    --podman-only) DO_QEMU=0 ;;
    --qemu-only)   DO_PODMAN=0 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 64 ;;
  esac
done

if [ "$USE_COLOR" = 1 ]; then
  C_OK=$'\e[32m' C_WARN=$'\e[33m' C_BAD=$'\e[31m' C_INFO=$'\e[36m' C_HDR=$'\e[1m' C_OFF=$'\e[0m'
else
  C_OK='' C_WARN='' C_BAD='' C_INFO='' C_HDR='' C_OFF=''
fi

ok()   { printf '  %s[ OK ]%s %s\n' "$C_OK"   "$C_OFF" "$*"; }
warn() { printf '  %s[WARN]%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
bad()  { printf '  %s[FAIL]%s %s\n' "$C_BAD"  "$C_OFF" "$*"; }
info() { printf '  %s[INFO]%s %s\n' "$C_INFO" "$C_OFF" "$*"; }
hint() { printf '         -> %s\n' "$*"; }
hdr()  { printf '\n%s== %s ==%s\n' "$C_HDR" "$*" "$C_OFF"; }

have()  { command -v "$1" >/dev/null 2>&1; }
readf() { cat "$1" 2>/dev/null; }
# ver_ge A B : true if version A >= B
ver_ge() { printf '%s\n%s\n' "$2" "$1" | sort -V -C; }

USER_NAME=$(id -un); USER_ID=$(id -u); USER_GID=$(id -g)
ARCH=$(uname -m); KREL=$(uname -r); KVER=${KREL%%[-+_]*}

EXTRA_DIRS="/usr/libexec/podman /usr/lib/podman /usr/local/libexec/podman /usr/local/lib/podman
/usr/libexec /usr/lib/qemu /usr/libexec/qemu /usr/local/libexec /usr/lib/cni /opt/cni/bin
/usr/libexec/cni /usr/sbin /sbin"

# find_bin name... : print path of the first name found in PATH or helper dirs
find_bin() {
  local n d
  for n in "$@"; do
    if have "$n"; then command -v "$n"; return 0; fi
    for d in $EXTRA_DIRS; do
      [ -x "$d/$n" ] && [ ! -d "$d/$n" ] && { echo "$d/$n"; return 0; }
    done
  done
  return 1
}

# priv_status file : "setuid", "caps:<caps>", "none", or "unknown"
priv_status() {
  local f=$1 caps
  if [ -u "$f" ] && [ "$(stat -Lc %u "$f" 2>/dev/null)" = 0 ]; then echo setuid; return; fi
  if have getcap; then
    caps=$(getcap "$(readlink -f "$f")" 2>/dev/null | sed 's/^[^ ]* //; s/^= *//')
    if [ -n "$caps" ]; then echo "caps:$caps"; else echo none; fi
  else
    echo unknown
  fi
}

# dev_state path : missing | rw | partial | denied | blocked
# "blocked" = permission bits allow it but open() fails (device cgroup, LSM,
# or a container). Opening these nodes and closing them again has no effect.
dev_state() {
  local p=$1
  if [ ! -e "$p" ]; then echo missing
  elif [ -r "$p" ] && [ -w "$p" ]; then
    if ( exec 3<>"$p" ) 2>/dev/null; then echo rw; else echo blocked; fi
  elif [ -r "$p" ] || [ -w "$p" ]; then echo partial
  else echo denied; fi
}
dev_meta() { stat -c '%U:%G mode %a' "$1" 2>/dev/null; }

group_members() {
  if have getent; then getent group "$1"; else grep "^$1:" /etc/group 2>/dev/null; fi \
    | cut -d: -f4 | tr ',' '\n'
}

# group_hint path : explain why a group-owned device is not accessible
group_hint() {
  local g; g=$(stat -c %G "$1" 2>/dev/null) || return 0
  if [ "$2" = blocked ]; then
    hint "permissions allow it but open() failed: device cgroup, SELinux/AppArmor, or running in a container"
    return 0
  fi
  [ "$g" = root ] && { hint "owned by root:root - needs a udev rule or ACL from an admin"; return 0; }
  if id -nG | tr ' ' '\n' | grep -qx "$g"; then
    hint "you are in group '$g' but access is still denied (ACL or LSM policy?)"
  elif group_members "$g" | grep -qx "$USER_NAME"; then
    hint "you were added to group '$g' after this session started - log out and back in (or 'newgrp $g')"
  else
    hint "owned by group '$g' - an admin can run: usermod -aG $g $USER_NAME"
  fi
}

# report_dev path label severity(warn|bad|info) : prints result, returns 0 if usable
report_dev() {
  local p=$1 label=$2 sev=$3 st
  st=$(dev_state "$p")
  case $st in
    rw)      ok "$label: $p is accessible"; return 0 ;;
    missing) $sev "$label: $p does not exist"; return 1 ;;
    *)       $sev "$label: $p not usable ($st; $(dev_meta "$p"))"; group_hint "$p" "$st"; return 1 ;;
  esac
}

P_BLOCK=(); P_DEGRADE=(); P_CAPS=()
Q_BLOCK=(); Q_DEGRADE=(); Q_CAPS=()

# ---------------------------------------------------------------- system ----
hdr "System"
if [ "$(uname -s)" != Linux ]; then
  bad "this is $(uname -s), not Linux: podman needs a Linux VM here ('podman machine')"
  exit 3
fi
info "user: $USER_NAME (uid $USER_ID, gid $USER_GID), groups: $(id -nG)"
info "kernel $KREL on $ARCH"
[ -r /etc/os-release ] && info "distro: $( . /etc/os-release; echo "${PRETTY_NAME:-${NAME:-unknown}}")"
[ "$USER_ID" = 0 ] && warn "running as root: results describe root's capabilities, not a normal user's"

VIRT_C=none; VIRT_VM=none
if have systemd-detect-virt; then
  VIRT_C=$(systemd-detect-virt --container 2>/dev/null) || VIRT_C=none
  VIRT_VM=$(systemd-detect-virt --vm 2>/dev/null) || VIRT_VM=none
fi
[ "$VIRT_C" = none ] && [ -e /run/.containerenv ] && VIRT_C=podman
[ "$VIRT_C" = none ] && [ -e /.dockerenv ] && VIRT_C=docker
[ "$VIRT_VM" = none ] && grep -qw hypervisor /proc/cpuinfo 2>/dev/null && VIRT_VM=unknown-hypervisor
IS_WSL=0; grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null && IS_WSL=1
[ "$VIRT_C" != none ] && warn "running inside a container ($VIRT_C): nested podman/KVM needs extra privileges from the outer runtime"
[ "$VIRT_VM" != none ] && info "running inside a virtual machine ($VIRT_VM)"
[ "$IS_WSL" = 1 ] && info "running under WSL2"

if [ -r /sys/kernel/security/lsm ]; then info "security modules: $(readf /sys/kernel/security/lsm)"; fi
if [ -r /sys/fs/selinux/enforce ]; then
  [ "$(readf /sys/fs/selinux/enforce)" = 1 ] && info "SELinux: enforcing" || info "SELinux: permissive"
fi

# ---------------------------------------------------------------- podman ----
check_podman() {
  local p f n v

  hdr "Podman: binaries"
  if p=$(find_bin podman); then ok "podman: $p"
  else bad "podman is not installed"; P_BLOCK+=("podman binary missing"); fi

  f=0
  for n in crun runc youki krun; do
    if p=$(find_bin "$n"); then ok "OCI runtime: $p"; f=1; fi
  done
  [ $f = 0 ] && { bad "no OCI runtime (crun or runc)"; P_BLOCK+=("no OCI runtime"); }

  if p=$(find_bin conmon conmon-rs); then ok "container monitor: $p"
  else bad "conmon not found"; P_BLOCK+=("conmon missing"); fi

  local net=""
  if p=$(find_bin pasta); then ok "rootless networking: pasta ($p)"; net=pasta; fi
  if p=$(find_bin slirp4netns); then ok "rootless networking: slirp4netns ($p)"; net=${net:-slirp4netns}; fi
  [ -z "$net" ] && { warn "neither pasta nor slirp4netns: rootless containers limited to --network=none/host"
                     P_DEGRADE+=("no rootless network stack (pasta/slirp4netns)"); }
  if p=$(find_bin netavark); then info "netavark: $p (custom networks, rootful bridge)"
  elif [ -d /usr/lib/cni ] || [ -d /opt/cni/bin ]; then info "CNI plugins present (legacy network backend)"
  else info "netavark not found: 'podman network create' bridges unavailable"; fi
  find_bin aardvark-dns >/dev/null && info "aardvark-dns present: container name resolution on custom networks"
  p=$(find_bin fuse-overlayfs) && info "fuse-overlayfs: $p"
  p=$(find_bin catatonit tini) && info "init helper for --init: $p"

  hdr "Podman: user namespaces"
  if [ -e /proc/self/ns/user ]; then ok "kernel supports user namespaces"
  else bad "kernel lacks user namespaces (CONFIG_USER_NS)"; P_BLOCK+=("no user namespace support"); fi

  v=$(readf /proc/sys/user/max_user_namespaces)
  if [ -n "$v" ]; then
    if [ "$v" -gt 0 ] 2>/dev/null; then ok "user.max_user_namespaces = $v"
    else bad "user.max_user_namespaces = 0"; P_BLOCK+=("user namespaces disabled by sysctl"); fi
  fi
  v=$(readf /proc/sys/kernel/unprivileged_userns_clone)
  if [ -n "$v" ]; then
    if [ "$v" = 1 ]; then ok "kernel.unprivileged_userns_clone = 1"
    else bad "kernel.unprivileged_userns_clone = 0"; P_BLOCK+=("unprivileged user namespaces disabled"); fi
  fi
  v=$(readf /proc/sys/kernel/apparmor_restrict_unprivileged_userns)
  if [ "$v" = 1 ]; then
    warn "AppArmor restricts unprivileged user namespaces; podman needs its AppArmor profile (shipped with distro packages)"
    hint "if rootless podman fails with 'permission denied' on uid_map, the profile is missing"
  fi
  if [ -r /proc/self/uid_map ] && ! grep -Eq '^ *0 +0 +4294967295' /proc/self/uid_map; then
    info "already inside a user namespace (uid_map: $(head -1 /proc/self/uid_map | tr -s ' '))"
  fi

  local su sg
  subcount() {
    [ -r "$1" ] || { echo -1; return; }
    awk -F: -v u="$USER_NAME" -v id="$USER_ID" '($1==u||$1==id){s+=$3} END{print s+0}' "$1"
  }
  su=$(subcount /etc/subuid); sg=$(subcount /etc/subgid)
  for pair in "subuid:$su" "subgid:$sg"; do
    n=${pair%%:*}; v=${pair#*:}
    if [ "$v" -ge 65536 ]; then ok "/etc/$n: $v IDs allocated to $USER_NAME"
    elif [ "$v" -gt 0 ]; then warn "/etc/$n: only $v IDs (65536 recommended); images using high UIDs will fail"
         P_DEGRADE+=("small $n range")
    else
      if grep -q '^subid:' /etc/nsswitch.conf 2>/dev/null; then
        info "no /etc/$n entry, but nsswitch has 'subid:' (IDs may come from LDAP/SSSD)"
      else
        warn "no /etc/$n entry for $USER_NAME: only a single UID is mappable"
        [ "$n" = subuid ] && hint "most multi-user images fail to unpack; admin fix: usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER_NAME"
        P_DEGRADE+=("no subordinate $n range")
      fi
    fi
  done

  for n in newuidmap newgidmap; do
    if p=$(find_bin "$n"); then
      v=$(priv_status "$p")
      case $v in
        setuid|caps:*cap_set[ug]id*) ok "$n: $p ($v)" ;;
        unknown) info "$n: $p (not setuid; getcap unavailable to check file capabilities)" ;;
        *) warn "$n: $p has neither setuid nor cap_set${n:3:1}id"; P_DEGRADE+=("$n not privileged") ;;
      esac
    else
      warn "$n missing (uidmap / shadow-utils package): subordinate IDs cannot be used"
      P_DEGRADE+=("$n missing")
    fi
  done

  hdr "Podman: cgroups"
  local cgfs own ctrls dfile missing c
  cgfs=$(stat -fc %T /sys/fs/cgroup 2>/dev/null)
  if [ "$cgfs" = cgroup2fs ]; then
    ok "cgroup v2 (unified hierarchy)"
    own=$(awk -F: '$1=="0"{print $3}' /proc/self/cgroup 2>/dev/null)
    info "current cgroup: ${own:-?}"
    dfile="/sys/fs/cgroup/user.slice/user-$USER_ID.slice/user@$USER_ID.service/cgroup.controllers"
    if [ "$USER_ID" = 0 ]; then dfile=/sys/fs/cgroup/cgroup.controllers; fi
    [ -r "$dfile" ] || dfile="/sys/fs/cgroup${own}/cgroup.controllers"
    ctrls=$(readf "$dfile")
    if [ -n "$ctrls" ]; then
      info "controllers delegated to you: $ctrls"
      missing=""
      for c in cpu memory pids io cpuset; do
        case " $ctrls " in *" $c "*) ;; *) missing="$missing $c" ;; esac
      done
      if [ -z "$missing" ]; then
        ok "all common controllers delegated: --memory, --cpus, --pids-limit, --cpuset-cpus, --device-*-bps work"
        P_CAPS+=("resource limits (cgroup controllers delegated)")
      else
        warn "not delegated:$missing - matching resource-limit flags will be ignored or fail"
        hint "admin fix: /etc/systemd/system/user@.service.d/delegate.conf with [Service] Delegate=cpu cpuset io memory pids"
        P_DEGRADE+=("cgroup controllers not delegated:$missing")
      fi
    else
      warn "could not read delegated controllers"
    fi
  elif [ "$cgfs" = tmpfs ]; then
    if [ -d /sys/fs/cgroup/unified ]; then warn "cgroup v1/v2 hybrid"; else warn "cgroup v1"; fi
    hint "rootless containers cannot use resource limits; podman 5 deprecates cgroup v1"
    P_DEGRADE+=("cgroup v1: no rootless resource limits")
  else
    bad "no cgroup filesystem mounted at /sys/fs/cgroup"; P_BLOCK+=("no cgroups mounted")
  fi

  hdr "Podman: session, runtime dir and systemd"
  local rd=${XDG_RUNTIME_DIR:-}
  if [ -z "$rd" ]; then
    warn "XDG_RUNTIME_DIR unset: podman falls back to /tmp/podman-run-$USER_ID (common after 'su' or 'sudo -u')"
    hint "log in directly (ssh/console) or use 'machinectl shell $USER_NAME@' to get a proper session"
    P_DEGRADE+=("no XDG_RUNTIME_DIR (no login session)")
  elif [ ! -d "$rd" ]; then bad "XDG_RUNTIME_DIR=$rd does not exist"; P_DEGRADE+=("XDG_RUNTIME_DIR missing")
  elif [ "$(stat -c %u "$rd")" != "$USER_ID" ] || [ ! -w "$rd" ]; then
    bad "XDG_RUNTIME_DIR=$rd not owned/writable by you"; P_DEGRADE+=("XDG_RUNTIME_DIR not yours")
  else ok "XDG_RUNTIME_DIR=$rd ($(stat -c %a "$rd"))"; fi

  if [ -d /run/systemd/system ]; then
    ok "systemd is the init system"
    if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] || { [ -n "$rd" ] && [ -S "$rd/bus" ]; }; then
      ok "user D-Bus session bus reachable: systemd cgroup manager, quadlet and 'podman generate systemd' usable"
      P_CAPS+=("systemd integration (quadlet, user units)")
    else
      warn "no user D-Bus session bus: podman falls back to the cgroupfs manager; quadlet/user units unavailable"
      P_DEGRADE+=("no user D-Bus session")
    fi
    if [ -e "/var/lib/systemd/linger/$USER_NAME" ]; then
      ok "lingering enabled: containers and user services survive logout"
      P_CAPS+=("containers persist after logout (linger)")
    else
      info "lingering off: your containers stop when your last session ends ('loginctl enable-linger' to change)"
    fi
  else
    info "not running systemd: podman uses the cgroupfs manager; no quadlet"
  fi

  hdr "Podman: storage"
  local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/containers" groot d fs avail drv=""
  groot="${XDG_DATA_HOME:-$HOME/.local/share}/containers/storage"
  if [ -r "$cfg/storage.conf" ]; then
    v=$(sed -n 's/^[[:space:]]*graphroot[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' "$cfg/storage.conf" | head -1)
    [ -n "$v" ] && groot=$v
    drv=$(sed -n 's/^[[:space:]]*driver[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' "$cfg/storage.conf" | head -1)
    info "user storage.conf found: $cfg/storage.conf"
  elif [ -r /etc/containers/storage.conf ]; then
    v=$(sed -n 's/^[[:space:]]*rootless_storage_path[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' /etc/containers/storage.conf | head -1)
    [ -n "$v" ] && groot=$(printf '%s' "$v" | sed "s|\$HOME|$HOME|g; s|\$USER|$USER_NAME|g; s|\$UID|$USER_ID|g")
    drv=$(sed -n 's/^[[:space:]]*driver[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' /etc/containers/storage.conf | head -1)
  fi
  [ "$USER_ID" = 0 ] && groot=/var/lib/containers/storage
  info "image storage: $groot${drv:+ (configured driver: $drv)}"
  d=$groot; while [ ! -e "$d" ] && [ "$d" != / ]; do d=$(dirname "$d"); done
  fs=$(stat -fc %T "$d" 2>/dev/null)
  avail=$(df -Pk "$d" 2>/dev/null | awk 'NR==2{print int($4/1048576)}')
  if [ ! -w "$d" ]; then bad "$d is not writable"; P_BLOCK+=("storage location not writable")
  else
    case $fs in
      nfs*|cifs|smb*|fuse.sshfs|9p|v9fs)
        warn "storage is on $fs: overlay and xattrs are unreliable here; set graphroot to a local disk"
        P_DEGRADE+=("storage on network filesystem ($fs)") ;;
      overlayfs|overlay) warn "storage is on overlayfs (nested container?): needs fuse-overlayfs or vfs"
        P_DEGRADE+=("storage on overlayfs") ;;
      tmpfs) info "storage is on tmpfs: images are lost at reboot and consume RAM" ;;
      *) ok "storage filesystem: $fs" ;;
    esac
    if [ -n "$avail" ]; then
      if [ "$avail" -lt 5 ]; then warn "only ${avail} GiB free for images"; else ok "${avail} GiB free for images"; fi
    fi
  fi

  local overlay=0 fuse=0
  if grep -qw overlay /proc/filesystems 2>/dev/null || \
     ls /lib/modules/"$KREL"/kernel/fs/overlayfs/overlay.ko* >/dev/null 2>&1; then overlay=1; fi
  report_dev /dev/fuse "FUSE" info && fuse=1
  if [ $overlay = 1 ] && ver_ge "$KVER" 5.11; then
    ok "native rootless overlay storage (kernel $KVER >= 5.11)"
    P_CAPS+=("fast overlay storage")
  elif [ $fuse = 1 ] && find_bin fuse-overlayfs >/dev/null; then
    ok "rootless overlay via fuse-overlayfs"
    P_CAPS+=("overlay storage via fuse-overlayfs")
  else
    warn "no native rootless overlay and no fuse-overlayfs: podman will use the slow 'vfs' driver"
    P_DEGRADE+=("vfs storage only (slow, disk-hungry)")
  fi

  hdr "Podman: networking and security"
  if report_dev /dev/net/tun "TUN" warn; then :
  else [ -n "$net" ] && P_DEGRADE+=("/dev/net/tun unusable: pasta/slirp4netns won't work"); fi
  v=$(readf /proc/sys/net/ipv4/ip_unprivileged_port_start)
  [ -n "$v" ] && info "lowest port you can publish without root: $v (net.ipv4.ip_unprivileged_port_start)"
  v=$(readf /proc/sys/net/ipv4/ping_group_range | tr -s '\t ' ' ')
  if [ -n "$v" ]; then
    set -- $v
    if [ "$USER_GID" -ge "$1" ] 2>/dev/null && [ "$USER_GID" -le "$2" ] 2>/dev/null; then
      info "unprivileged ICMP allowed (ping works in rootless containers)"
    else info "ping_group_range '$v' excludes your gid: ping inside containers may fail"; fi
  fi
  if grep -q '^Seccomp:' /proc/self/status 2>/dev/null; then ok "seccomp filtering supported"
  else warn "kernel lacks seccomp: containers run without syscall filtering"; fi

  if [ -r "$cfg/policy.json" ] || [ -r /etc/containers/policy.json ]; then ok "image signature policy (policy.json) present"
  else bad "no containers policy.json: image pulls will be refused"; P_BLOCK+=("policy.json missing (cannot pull images)"); fi
  if [ -r "$cfg/registries.conf" ] || [ -r /etc/containers/registries.conf ]; then
    v=$(grep -h '^[[:space:]]*unqualified-search-registries' "$cfg/registries.conf" /etc/containers/registries.conf 2>/dev/null | head -1 | sed 's/.*=[[:space:]]*//')
    info "registries.conf present${v:+; short names search $v}"
  else info "no registries.conf: use fully-qualified image names (docker.io/library/alpine)"; fi
}

# ------------------------------------------------------------------ qemu ----
check_qemu() {
  local q p v n kvm=1 st

  hdr "QEMU: binaries"
  if q=$(find_bin qemu-system-x86_64 qemu-kvm); then ok "emulator: $q"
  else bad "qemu-system-x86_64 not installed"; Q_BLOCK+=("qemu-system-x86_64 missing"); q=""; fi
  p=$(find_bin qemu-img) && info "qemu-img: $p (disk image tools)"
  if [ -n "$q" ]; then
    if have readelf; then v=$(readelf -d "$q" 2>/dev/null | grep -c 'libslirp'); else v=$(grep -c libslirp "$q" 2>/dev/null); fi
    if [ "${v:-0}" -gt 0 ]; then ok "linked against libslirp: user-mode NAT networking (-nic user) available"
                               Q_CAPS+=("user-mode NAT networking")
    else warn "no libslirp linkage found: on QEMU >= 7.2 '-nic user' is unavailable (use passt or tap)"; fi
  fi

  hdr "QEMU: KVM acceleration"
  case $ARCH in
    x86_64|i?86) ;;
    *) warn "host is $ARCH: x86_64 guests can only run under TCG emulation (slow)"
       Q_DEGRADE+=("no KVM for x86 guests on $ARCH host (TCG only)"); kvm=0 ;;
  esac
  if [ $kvm = 1 ]; then
    if grep -qw vmx /proc/cpuinfo; then ok "CPU supports Intel VT-x (vmx)"
    elif grep -qw svm /proc/cpuinfo; then ok "CPU supports AMD-V (svm)"
    else
      kvm=0
      if [ "$VIRT_VM" != none ]; then bad "no vmx/svm: the outer hypervisor ($VIRT_VM) does not expose nested virtualization"
        [ "$IS_WSL" = 1 ] && hint "WSL2: set nestedVirtualization=true in %UserProfile%\\.wslconfig"
      else bad "no vmx/svm: virtualization unsupported or disabled in BIOS/UEFI firmware"; fi
    fi
    for n in kvm kvm_intel kvm_amd; do [ -d /sys/module/$n ] && info "kernel module loaded: $n"; done
    if [ -d /sys/module/kvm ] && [ ! -d /sys/module/kvm_intel ] && [ ! -d /sys/module/kvm_amd ] && [ $kvm = 1 ]; then
      warn "kvm loaded but no vendor module (kvm_intel/kvm_amd): often means VT-x/AMD-V disabled in firmware"
    fi
    if report_dev /dev/kvm "KVM" bad; then
      [ $kvm = 1 ] && { Q_CAPS+=("KVM hardware acceleration (-accel kvm)"); }
    else kvm=0; fi
    [ $kvm = 0 ] && Q_DEGRADE+=("no KVM: TCG emulation only (10-50x slower)")
    for n in kvm_intel kvm_amd; do
      v=$(readf /sys/module/$n/parameters/nested)
      case $v in Y|1) info "nested virtualization enabled ($n): guests can run their own VMs" ;;
                 N|0) info "nested virtualization disabled ($n)" ;; esac
    done
  fi

  hdr "QEMU: networking"
  report_dev /dev/net/tun "TUN/TAP" info >/dev/null; st=$(dev_state /dev/net/tun)
  local mytaps=""
  for p in /sys/class/net/*/tun_flags; do
    [ -e "$p" ] || continue
    n=$(basename "$(dirname "$p")")
    [ "$(readf /sys/class/net/$n/owner)" = "$USER_ID" ] && mytaps="$mytaps $n"
  done
  if [ -n "$mytaps" ] && [ "$st" = rw ]; then ok "persistent tap devices you own:$mytaps (-netdev tap,ifname=...,script=no)"
    Q_CAPS+=("tap networking on pre-made taps:$mytaps")
  else info "no tap device owned by you: creating taps needs root or CAP_NET_ADMIN"; fi
  if p=$(find_bin qemu-bridge-helper); then
    v=$(priv_status "$p")
    case $v in
      setuid|caps:*cap_net_admin*)
        if [ -r /etc/qemu/bridge.conf ]; then
          n=$(grep -E '^[[:space:]]*allow' /etc/qemu/bridge.conf | awk '{print $2}' | tr '\n' ' ')
          if [ -n "$n" ]; then ok "qemu-bridge-helper ($v) may attach you to bridge(s): $n"
            Q_CAPS+=("bridged networking via qemu-bridge-helper ($n)")
          else info "qemu-bridge-helper is privileged but /etc/qemu/bridge.conf allows no bridges"; fi
        else info "qemu-bridge-helper is privileged; /etc/qemu/bridge.conf missing or unreadable (allowed bridges unknown)"; fi ;;
      *) info "qemu-bridge-helper at $p is not privileged ($v): bridged networking needs root" ;;
    esac
  fi
  p=$(find_bin passt) && { info "passt available: unprivileged networking via -netdev stream/passt"; Q_CAPS+=("passt networking"); }
  report_dev /dev/vhost-net "vhost-net" info && Q_CAPS+=("vhost-net accelerated virtio networking")
  report_dev /dev/vhost-vsock "vhost-vsock" info && Q_CAPS+=("host<->guest vsock")

  hdr "QEMU: firmware and devices"
  local fwdirs="/usr/share/qemu /usr/share/seabios /usr/share/OVMF /usr/share/ovmf /usr/share/edk2
/usr/share/edk2-ovmf /usr/share/edk2/ovmf /usr/share/edk2/x64 /usr/local/share/qemu /usr/share/qemu-efi"
  # shellcheck disable=SC2086
  p=$(find $fwdirs -maxdepth 2 \( -name 'bios-256k.bin' -o -name 'bios.bin' \) 2>/dev/null | head -1)
  if [ -n "$p" ]; then ok "SeaBIOS (legacy BIOS boot): $p"
  else warn "SeaBIOS bios-256k.bin not found in usual places (QEMU may use a custom datadir)"; Q_DEGRADE+=("SeaBIOS not found"); fi
  # shellcheck disable=SC2086
  p=$(find $fwdirs -maxdepth 3 \( -iname 'OVMF_CODE*.fd' -o -iname 'OVMF.fd' -o -name 'edk2-x86_64-code.fd' -o -iname 'OVMF_CODE*.4m.fd' \) 2>/dev/null | head -1)
  if [ -n "$p" ]; then ok "UEFI firmware (OVMF): $p"; Q_CAPS+=("UEFI boot (OVMF)")
    # shellcheck disable=SC2086
    find $fwdirs -maxdepth 3 \( -iname '*secboot*.fd' -o -iname '*.ms.fd' -o -iname '*secure*code*.fd' \) 2>/dev/null | grep -q . \
      && { info "Secure Boot-capable OVMF build present"; Q_CAPS+=("UEFI Secure Boot"); }
  else info "no OVMF found: UEFI guests unavailable (install ovmf / edk2-ovmf)"; fi
  if p=$(find_bin swtpm); then ok "swtpm: $p (virtual TPM 2.0, e.g. for Windows 11)"; Q_CAPS+=("emulated TPM 2.0")
  else info "swtpm not installed: no virtual TPM"; fi

  local memt mema hp hpsz lim
  memt=$(awk '/^MemTotal/{print int($2/1048576)}' /proc/meminfo)
  mema=$(awk '/^MemAvailable/{print int($2/1048576)}' /proc/meminfo)
  info "memory: ${mema:-?} GiB available of ${memt:-?} GiB"
  hp=$(awk '/^HugePages_Free/{print $2}' /proc/meminfo); hpsz=$(awk '/^Hugepagesize/{print $2}' /proc/meminfo)
  if [ "${hp:-0}" -gt 0 ]; then
    if [ -d /dev/hugepages ] && [ -w /dev/hugepages ]; then ok "$hp free hugepages (${hpsz} kB) and /dev/hugepages writable"
      Q_CAPS+=("hugepage-backed guest RAM")
    else info "$hp hugepages reserved but /dev/hugepages not writable by you"; fi
  fi
  v=$(readf /sys/kernel/mm/transparent_hugepage/enabled | sed 's/.*\[\(.*\)\].*/\1/')
  [ -n "$v" ] && info "transparent hugepages: $v"
  lim=$(ulimit -l)
  info "locked-memory limit (ulimit -l): $lim kB$([ "$lim" != unlimited ] && echo ' - too low for VFIO passthrough or -overcommit mem-lock')"

  hdr "QEMU: device passthrough and graphics"
  n=$(find /sys/kernel/iommu_groups -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
  if [ "$n" -gt 0 ]; then
    info "IOMMU active: $n groups"
    v=""
    for p in /dev/vfio/[0-9]*; do [ -e "$p" ] && [ -r "$p" ] && [ -w "$p" ] && v="$v ${p##*/}"; done
    if [ -n "$v" ] && [ "$(dev_state /dev/vfio/vfio)" = rw ]; then ok "VFIO groups accessible to you:$v"
      Q_CAPS+=("PCI passthrough (VFIO groups$v)")
    else info "no VFIO group accessible to you: PCI passthrough needs admin setup"; fi
  else info "IOMMU not active: no PCI passthrough (enable intel_iommu=on / amd_iommu in firmware+kernel)"; fi

  if [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]; then
    ok "graphical session (${WAYLAND_DISPLAY:+Wayland }${DISPLAY:+X11 $DISPLAY}): GTK/SDL display windows possible"
    Q_CAPS+=("local display window")
  else info "no DISPLAY/WAYLAND_DISPLAY: use -display none, -vnc or -spice"; fi
  v=""
  for p in /dev/dri/renderD*; do [ "$(dev_state "$p")" = rw ] && v="$v ${p##*/}"; done
  if [ -n "$v" ]; then ok "GPU render node(s) accessible:$v (virtio-gpu-gl / virgl)"; Q_CAPS+=("3D acceleration via virgl")
  elif ls /dev/dri/renderD* >/dev/null 2>&1; then
    info "GPU render nodes exist but aren't accessible"; group_hint "$(ls /dev/dri/renderD* | head -1)" denied
  fi
}

[ $DO_PODMAN = 1 ] && check_podman
[ $DO_QEMU = 1 ] && check_qemu

# --------------------------------------------------------------- summary ----
list() { local x; for x in "$@"; do printf '       - %s\n' "$x"; done; }
verdict() { # title blocked-array degraded-array caps-array
  local -n blk=$2 deg=$3 cap=$4
  if [ ${#blk[@]} -gt 0 ]; then printf '  %s%s: NOT USABLE%s\n' "$C_BAD" "$1" "$C_OFF"; list "${blk[@]}"
  elif [ ${#deg[@]} -gt 0 ]; then printf '  %s%s: USABLE WITH LIMITATIONS%s\n' "$C_WARN" "$1" "$C_OFF"; list "${deg[@]}"
  else printf '  %s%s: READY%s\n' "$C_OK" "$1" "$C_OFF"; fi
  if [ ${#blk[@]} -eq 0 ] && [ ${#cap[@]} -gt 0 ]; then printf '     available:\n'; list "${cap[@]}"; fi
}

hdr "Summary for $USER_NAME"
rc=0
if [ $DO_PODMAN = 1 ]; then
  t="Rootless podman"; [ "$USER_ID" = 0 ] && t="Podman (as root)"
  verdict "$t" P_BLOCK P_DEGRADE P_CAPS
  [ ${#P_BLOCK[@]} -gt 0 ] && rc=$((rc | 1))
fi
if [ $DO_QEMU = 1 ]; then
  verdict "qemu-system-x86_64" Q_BLOCK Q_DEGRADE Q_CAPS
  [ ${#Q_BLOCK[@]} -gt 0 ] && rc=$((rc | 2))
fi
echo
exit $rc