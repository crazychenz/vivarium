## Overview

When performing agentic development, many developers and users take great risks. Their trust that something malicious will not happen is placed in the upstream model providers. Their trust in an honest mistakes is placed in the tools and possible posterity. And almost universally folks are putting their heads in the sand in regards to the possibilities surrounding an insecure agentic setup.

One of the things I've been stressing over for the past few weeks is how to setup an environment that makes agentic development feel actually sandboxed.

### The Hazards

I hate security mantra and security mindset. More often than not, when folks talk about _security_, they should be framing it as safety and health. Fundamentally, this is the notion that we want to help honest people stay honest and safe.

In the world of agentic development, safety hazards often come from model ignorance or hallucinations. These gaps in the model's capabilities are ignored by the dumb agent and things often can keep moving forward down the wrong path, ever increasing the cost of correction.
### The Threats

In terms of _actual_ security, there is a very real issue with entities on the internet that maliciously attempt to degrade, steal, or hijack your resources for their own means. In the world of agentic development this comes in many forms. The most common being prompt injection.

### The Effects

In both cases of hazards and threats, there are a number of common effects if not properly mitigated:

- Agent leaks secrets.
	- Stealing model compute.
	- Stealing MCP tool API keys or access.
	- Stealing SSH key access.
- Agent performs unwanted execution (i.e. RCE).
	- Agent degrades environment.
	- Agent changes its own configuration.
	- Agent performs calls that were not part of context.
	- Agent runs up model costs (or electric costs).

After considering all of these effects, the naive approach would be to "lock it all down"! But that completely dorks the agent as a valuable resource. The reality is that you need to give the agent a lot of breathing room and room to make mistakes to get the maximum value out of it.

Consider a zoo as an analogy. In the early 20th century, we'd lock up large animals in tiny cages where they were clearly visible but depressed, unhappy, and often ill due to the constrained environment. Fast foward to today and you have much larger enclosures that allow the animals to roam (a bit) and therefore now have increased health and better lives. This has additional benefits of better breeding results, better research results, and a number of other benefits aside from their general demeaner. 

Agents are the same way. We can not (naively) lock them up into a tiny cage where everything they do becomes a human decision. One of two things happens in that situation:

- The agent's value is so low we ignore it and find another path of least resistance (often using someone else's infrastructure to absorb the risk.)
- The human gets decision fatigue and complacently clicks through all decisions.

We 100% want to keep the agent and its effects in an enclosure as much as reasonable, but we must also provide the agent room to breath. Tangibly, room to read artifacts, generate artifacts, and enable it to create as many turns as it requires (or is allocated) to accomplish the desired goal. Its needs the space to develop, compile, build, mock deploy, mock test, and iterate. (Something some companies that I've worked at never understood about developers alone, much less agents in agentic development.)

## The Mitigation

TODO: Image here.

In the above architecture, it may appear that the agent has been caged exactly as how I said not to. That is the wrong interpretation. Instead, consider the Agent VM to be the conceptual Agent in our analogy, the Execution Environment the enclosure, and the hypervisor+mitmproxy+MCP_gateway as the enclosure's walls+pits+fence.

### The Bits

- Starting with the Agent VM, we've locked down all LAN traffic to the MCP gateway and all external traffic must traverse the MITM proxy. The agent binary in the Agent VM has little to no write access aside from mandatory configuration maintenance and logging. The agent must have no ability to run local tool calls, modify any state of the local system, or be able to read secrets that are not of its own making.
  
- The agent binary (in Agent VM) will be configured so that any tool calls must go through the MCP gateway. This includes local shell tool calls. The intention is to make the agent think that its making local tool calls when in fact the MCP gateway is running all local commands in a remote execution environment.
	- The agent can have sudo in the execution environment and do anything the execution environment permits. This is where the agent can run free, create artifacts, consider its decisions and iterate without prejudice or judgement.
	- The execution environment networking must be locked down to specifically allowed IPs (e.g. git foundry and MCP). **No outgoing rogue calls!**
  
- The execution environment's external access is entirely through a file share that can be mounted. The developer or operator can review, update, and execute what they want from the file share. 
	- A more traditional push to Git Foundry can happen if the VM forwards an explicit endpoint (i.e. `guestfwd=`).
	- The execution environment can be pugged into a MITM proxy for more powerful filtering and inject capabilities if it requires more collaboration that just `git push` with external resources.
	
- The MCP gateway is a custom piece of python code that can perform any forwarding and responding actions necessary for the agent.
  
- Less traditional, the unprivileged Agent VM's access to things like an upstream model provider are completely MITM-ed for policy enforcement, packet injection, and auditing of all network traffic leaving our local environment.
	- The injection enables us to feed a false key to the agent binary's configuration and then inject the real key outside of its purview. This prevents the issue with API key leakage of the model API provider.
	  
	- The auditing permits potential for quarantined evaluation of model responses (e.g. via secondary models).
	  
	- The policy block is our firewall based on the TLS decrypted requests and responses. Using the kernel firewall isn't sufficient for TLS traffic and having a firewall in the guest VM unnecessarily increases the risk. Having the policy block permits cloud based model internet API calls required to be directly from the agent.

### Flexibility

Each piece of the architecture is loosely coupled to the next. I highly encourage folks to prescriptively apply the bits they want/need/desire as wanted/needed/desired. For maximum _safety_, do everything and more. For minimum _safety_, only implement the unprivileged agent VM and point it at a low risk execution environment. I do believe that allowing an agent binary to have access to its own configurations and therefore its own API keys is completely reasonable, especially if you don't have much invested in the API key itself. For those that could see 10 of thousands of currency disappear if they lose that key, I'd urge them to reconsider exposing the API key to an agent.

## The Process

TODO: Write about the process to create:

- Inject mitmproxy CA certificate
	- _Recommended ca cert injection in all cases_
- Configure proxy for agent VM, choose:
	- Make it completely open.
	- Use `mitmproxy --mode regular` (req guest config)
	- Use `mitmproxy --mode transparent` (req root)
	- Use user mode transparent gateway + MITM
- Agent qemu microvm VM
	- Choose Ubuntu or Alpine. (Agent bin req glibc?)
	- Generate / Provision
		- Mitm options?
	- Start
	- Use
	- Stop
- MCP Gateway
	- Start
	- Use
	- Stop
- Execution Environment
	- Generate / Provision
		- Mitm options?
		- Endpoints?
	- Start
	- Use
	- Stop
