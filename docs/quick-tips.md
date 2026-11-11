# Quick Tips

```sh
# Build the rig: mitm, wgbridge, mcp, agentvm, enclosurevm
viv rig build --name agentrig agent

# Start the rig: mitm, wgbridge, mcp, agentvm, enclosurevm
viv rig run agentrig

# Access the agentvm claude code runs from
viv rig izba agentrig exec agentvm

# Access the enclosurevm (claude code has access too)
viv rig izba agentrig exec enclosurevm

# Access the claude code in the container.
viv rig izba agentrig exec agentvm -- docker attach agent

# Rebuild EnclosureVM
viv rig izba agentrig stop enclosurevm
viv rig izba agentrig rm enclosurevm
viv rig izba agentrig rmi enclosurevm
viv rig build --name agentrig agent
```