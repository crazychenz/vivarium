# Agent sandbox

Claude Code runs in a container inside a locked-down microvm (the **agent VM**). It has no built-in
tools. Its only tools are MCP tools from a gateway on the host, and the gateway runs everything in a
second microvm (the **exec VM**). The agent sees an ordinary local toolset and never learns that the
work happens elsewhere.

```
host ── gateway.py (MCP, 127.0.0.1:9000) ──SSH/SFTP──► exec VM  (no network at all)
  │  └─ api_proxy.py (127.0.0.1:3128, holds the API key) ──TLS──► api.anthropic.com
  └─ agent VM (restrict=on; sees only 10.0.2.100:9000 and 10.0.2.101:3128)
        └─ container: claude, built-in tools removed, MCP server "workspace"
```

## Host requirements
`qemu-system-x86_64`, `qemu-img`, `socat`, `mtools`, `dosfstools`, `curl`, `ssh`, `python3-venv`,
and access to `/dev/kvm` (user in the `kvm` group). Run as an unprivileged user.

## Use
```bash
./create-vms.sh                      # once: download image, provision both VMs (needs internet, ~10 min)
export ANTHROPIC_API_KEY=sk-ant-...  # stays on the host
./start-vms.sh
./run-agent.sh                       # interactive Claude Code; extra args go to `claude`
./stop-vms.sh
./reset-vm.sh exec                   # wipe the exec VM back to its provisioned state (also: agent, all)
python3 tests/test_gateway.py        # gateway test, no VMs needed (use state/venv/bin/python)
```
Per-VM settings (memory, CPUs, ports, release) are in `config.env`; override them in `config.local.env`.

## How the isolation works
- **Two-layer disks.** pristine Ubuntu image → `*-golden.qcow2` (provisioned once, with network) →
  `*.qcow2` session overlay. Runtime boots use only the overlay, so a reset is just a new overlay.
- **No network at runtime.** Both VMs boot with QEMU `restrict=on`. The exec VM has only an SSH
  forward to host loopback. The agent VM has two forwards: the gateway and the API forwarder.
- **The key never enters a VM.** The gateway's SSH key and the Anthropic key are host-only. The container
  gets a dummy token; `api_proxy.py` swaps in the real key and only forwards `/v1/*`.
- **Built-in tools are removed three ways:** `--tools ""`, `--disallowedTools`, and managed settings
  inside the image that the agent can't edit. `--strict-mcp-config` allows only the `workspace` server.
- **The exec VM pins its SSH host key** (generated on the host, injected via cloud-init) and runs
  sshd with forwarding disabled. The `agent` user has no sudo.

## What the agent can and can't infer
Tool names, descriptions, results and error messages never mention SSH, a VM or a host, and infrastructure
failures are reported as a generic "could not be completed" (details go to `state/logs/gateway-audit.jsonl`).
The container's working directory is `/workspace`, the same path the tools use, so Claude Code's own
environment summary matches what the tools show. This is consistency, not secrecy: the agent can still
notice things like a missing `claude` binary or QEMU hardware in `dmesg`. Don't rely on it for security.

## Files and getting work out
All agent work lives in `/workspace` in the exec VM (overlay, lost on `reset-vm.sh exec`). You can reach
it with your own key: `ssh -p 2222 agent@127.0.0.1` / `scp -P 2222 ...`. That is the intended export path.
Exec VM packages are fixed at provisioning; edit the package list in `create-vms.sh` before first run.

## Not verified here
The sandbox this was written in has no KVM or QEMU, so these pieces are **untested on real VMs**:
- Booting Ubuntu's generic kernel under `-M microvm` (virtio-mmio discovery). If the guest doesn't
  see its disk, check `state/logs/*.console.log`; the usual fix is a kernel built with virtio-mmio.
- Ubuntu's `unpacked/` kernel/initrd URLs (override `KERNEL_URL` / `INITRD_URL`) and the QEMU
  `guestfwd=...-cmd:` syntax. If a forward doesn't work, run `qemu-system-x86_64 -netdev help`.
- `-sandbox on` (seccomp). If QEMU dies with "Bad system call", set `QEMU_SANDBOX=off`.
- `ANTHROPIC_AUTH_TOKEN=unused` skipping Claude Code's login flow, and the managed-settings keys
  `allowManagedHooksOnly` and `permissions.disableBypassPermissionsMode`. Check `claude doctor` in the container.

The gateway and API forwarder **were** tested: `tests/test_gateway.py` passes all 15 checks against a stand-in
SSH server, and the forwarder was checked for key swapping, streaming and path blocking.
Subscription (OAuth) logins don't work with the forwarder, which needs an API key.
