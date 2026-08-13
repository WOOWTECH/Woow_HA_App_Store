---
name: hello-world
description: Minimal example skill. Prints a greeting via the shell. Use when the user asks to test that the pi skill system is loading skills correctly, or as a template for authoring new skills.
---

# Hello World Skill

Minimal reference skill demonstrating the pi skill layout. Drop this folder into `/data/pi-agent/skills/hello-world/` (or use the pi-web **Skills → Add skill** local-path flow) and it will be visible in every new pi session's `<available_skills>` block.

## Structure

```
hello-world/
├── SKILL.md        <-- Required. Frontmatter drives discovery.
└── scripts/
    └── greet.sh    <-- Referenced from SKILL.md steps.
```

## Steps

1. Confirm the runtime has bash: `which bash`
2. Run the greeting script: `bash scripts/greet.sh "$USER"`
3. Read stdout back to the user verbatim.

## Notes

- Skills are user-scope by default (global — visible to every session under the same PI_CODING_AGENT_DIR).
- A running session picks up skills at session start; add a new skill and start a new session (or use `/skill:hello-world`) to activate it.
- The `description` field above is what pi's model sees in the system prompt — write it in the imperative "Use when..." form so the model knows when to invoke.
