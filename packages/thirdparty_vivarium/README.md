# Vivarium

vivarium - a terrarium used for animals

vivarium exists as a tool to implement a well defined architecture for sandboxing agents for safe agentic development.

vivarium is a higher level compilation of a number of over libraries:

- thirdparty.dockerfile - (_wip_) For construction of container definitions.
- thirdparty.qemu - (_wip_) For construction of different qemu driving configurations.
  - thirdparty.qemu.dgram.wireguard - (**to be implemented**)
  - thirdparty.qemu.dgram.pcap - (**to be implemented**)
- thirdparty.mitmproxy - (**to be implemented**) For managing user mode mitmproxy.
  - thirdparty.mitmproxy.addon.* - (**to be implemented**) namespace for mitmproxy addon entrypoints
- thirdparty.pupa - (_wip_) For managing well-defined user-mode only VMs.
  - thirdparty.pupa.virtiofsd - (**to be implemented**) For driving virtiofsd daemon
- - thirdparty.pupa.profile.pupa - (**to be implemented**) Library of entrypoints for Pupa VM profiles
  - thirdparty.pupa.profile.vivarium - (**to be implemented**) Library of entrypoints for Vivarium VM profiles
- thirdparty.vivarium - (_wip_) For managing the agentic "sandbox".
  - thirdparty.vivarium.mcpg - (**to be implemented**)Vivarium's MCP gateway
  - thirdparty.vivarium.mcpg.tool.* - (**to be implemented**) namespace for vivarium tool entrypoints

## CLI

```text
# When positional and arg are explicit and do not match, throw error. (For better UX.)
viv [--deployment <name>] deployment ls [deployment-name]       # List existing deployments
viv [--deployment <name>] deployment create [deployment-name]   # Create new deployment
viv [--deployment <name>] deployment inspect [deployment-name]  # Print info on deployment
viv [--deployment <name>] deployment rm [deployment-name]       # Remove deployment
viv [--deployment <name>] deployment up [deployment-name]       # Ensure all VMs and services running
viv [--deployment <name>] deployment down [deployment-name]     # Ensure all VMs and services shut down

# Note: pupa should manage a virtiofsd per VM
viv [--deployment <name>] vm|pupa <subcmd> [opts] <profile> [<name>]
viv vm exec agent -- ls -l /mnt/host
viv vm exec enclosure -- ls -l /mnt/host

# We run a single mitmproxy per deployment.
viv [--deployment <name>] mitm <subcmd>
viv [--deployment <name>] mitm ls                        # list tracked listeners
viv [--deployment <name>] mitm certs init [-f]           # create certs
viv [--deployment <name>] mitm certs inspect             # parse certs
viv [--deployment <name>] mitm wireguard add <port>      # add wireguard listener
viv [--deployment <name>] mitm wireguard rm <port>       # rm wireguard listener
viv [--deployment <name>] mitm wireguard inspect <port>  # print wireguard listener info

# TODO: Reconsider these.
viv [--deployment <name>] mcpg <subcmd>
viv [--deployment <name>] mcpg tool ls
viv [--deployment <name>] mcpg tool enable <name>
viv [--deployment <name>] mcpg tool disable <name>
viv [--deployment <name>] mcpg tool setup <name>
```

## API

```text
from thirdparty.vivarium.deployment import Deployment

deployment = Deployment()
deployment.ls(): []
deployment.create(): None
deployment.inspect(): {}
deployment.rm(): None
deployment.up(): None
deployment.down(): None

vm = deployment.get_machine('agent'): PupaVm
vm.exec('agent', args)

mitm = deployment.get_mitmproxy(): MitmProxy
mitm.ls() # list listeners
mitm.priv_ca_cert() / mitm.pub_ca_cert() ...
wg_mgr = mitm.wireguard_manager(): WireguardManager
wg_mgr.ls(): []
wg_mgr.add(port)
wg_mgr.rm(port)
wg_mgr.inspect(port): WireguardListener(MitmproxyListener)

# TODO: Reconsider these.
mcpg = deployment.get_mcpg()
mcpg.tools(name): []
tool = mcpg.tool(name)
tool.enable()
tool.disable()
tool.set(**opts)
```
