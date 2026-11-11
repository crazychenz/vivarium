# Claude Code is 314MB?!?!

| base container | w/o    | w/    |
| -------------- | ------ | ----- |
| alpine         | 18.5MB | 500MB |
| distroless     | 37.2MB | 465MB |
| distroless-dbg | 39.1MB | 467MB |

## The Issue

Claude is written in Javascript. (sigh) At some point, Anthropic decided they wanted to distribute claude code as a "native" binary. So they bought Bun (the Javascript Engine) and rolled the whole thing with their javascript up into a single binary. Ordinarily, I would praise a statically compiled binary: its portable and more dependency free than traditional unix-y things. This is not that situation. Since claude code was built with Javascript and tacked onto an existing Bun binary there is ZERO link time optimization.

Link time optimization is when the compiler looks at all the application code and the provided library code and only includes the code that is used by the app from the libraries. This is how you can take a libc.a that is 20MB and an application that is 1KB and build a binary that is something like 2MB.

Let's consider what claude code is... Its an AI agent with a standard loop:

```python
def run_agent(user_goal, tools, policy):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + describe(tools)},
        {"role": "user",   "content": user_goal},
    ]

    for step in range(MAX_STEPS):
        # Call model (network comms)
        reply = llm.chat(messages, tools=schemas(tools))
        messages.append(reply)

        if not reply.tool_calls:
            # Nothing left to do, stop looping.
            return reply.text

        for call in reply.tool_calls:
            # Model requested more information.
            if not policy.allows(call):
                result = "Denied by user policy"
            elif policy.needs_approval(call) and not ask_user(call):
                result = "User declined"
            else:
                try:
                    # Run a command to do something (system call or network comms)
                    result = tools[call.name](**call.args)
                except Exception as e:
                    result = f"Error: {e}"

            messages.append({"role": "tool", "tool_call_id": call.id, "content": truncate(result), control})

        # Optionally compact context (network comms)
        messages = maybe_compact(messages)
```

For those that are not aware, that is 80% of what an agent is. The rest is:

- Skills Management (file IO)
- Tool Definition Management (e.g. file IO, network comms)
- Configuration Parsing (file IO)
- Authentication (i.e. crypt libraries, network comms)
- Metric Gathering (file IO)
- Logging / Auditing (file IO)
- User Interface

And that covers about 99% of what goes into an agent. If you break this down into dependencies:

- Network Comms && TLS Handling
- File IO - Parse, Serialization (e.g. JSON library)
- `clone()` System Call (i.e. run the tools)
- TUI library

**Now why in the bloody blistering and flaming hell do these things take 314MBs?!**

## The Threat

Put simply, if someone get RCE into a claude code agent, they effectively have the entire Bun Javascript Core to work with. TBF, if one gets RCE into anything with read, write, execute, you might as well put on your coat and head home. But to make it this easy for hackers to inject some javascript to sow any amount of havoc in your user profile (or worse, your system with a privilege escalation).

In the event that claude code was responsibly developed, it'd have a limited number of system calls permitted and we could reasonable audit its behavior. In fact, that is something you still can do ... monitor claude code's `strace` and then only allow those system calls with SELinux. (sigh).
