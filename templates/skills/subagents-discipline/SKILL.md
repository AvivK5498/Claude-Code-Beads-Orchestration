---
name: subagents-discipline
description: Core engineering principles for implementation tasks
---

# Implementation Principles

## Rule 0: Read the Bead First

Before implementing anything, **read the bead comments** for investigation context:

```bash
bd show {BEAD_ID}
bd comments {BEAD_ID}
```

The orchestrator has already:
- Investigated the issue using Grep, Read, Glob
- Found the root cause (specific file, function, line)
- Documented related files that may need changes
- Noted gotchas and edge cases

**Use this context.** Don't re-investigate. The comments contain everything you need to implement confidently.

If no investigation comments exist, ask the orchestrator to provide context before proceeding.

---

## Rule 1: Look Before You Code

Before writing code that touches external data (API, database, file, config):

1. **Fetch/read the ACTUAL data** - run the command, see the output
2. **Note exact field names, types, formats** - not what docs say, what you SEE
3. **Code against what you observed** - not what you assumed

```
WITHOUT looking first:
  Assumed: column is "reference_images"
  Reality: column is "reference_image_url"
  Result:  Query fails

WITH looking first:
  Ran: SELECT column_name FROM information_schema.columns WHERE table_name = 'assets';
  Saw: reference_image_url
  Coded against: reference_image_url
  Result: Works
```

## Rule 2: Test Both Levels

**Component test** catches: logic bugs, edge cases, type errors
**Feature test** catches: integration bugs, auth issues, data flow problems

| You built | Component test | Feature test |
|-----------|----------------|--------------|
| API endpoint | curl returns 200 | UI calls API, displays result |
| Database change | Migration runs | App reads/writes correctly |
| Frontend component | Renders, no errors | User can see and interact |
| Full-stack feature | Each piece works alone | End-to-end flow works |

## Rule 3: Use Your Tools

Before claiming you can't fully test:

1. **Check what MCP servers you have access to** - list available tools
2. **If any tool can help verify the feature works**, use it
3. **Be resourceful** - browser automation, database inspection, API testing tools

---

## For Epic Children

If your BEAD_ID contains a dot (e.g., BD-001.2), you're implementing part of a larger feature:

1. **Check for design doc**: `bd show {EPIC_ID} --json | jq -r '.[0].design'`
2. **Read it if it exists** - this is your contract
3. **Match it exactly** - same field names, same types, same shapes

---

## Red Flags - Stop and Verify

When you catch yourself thinking:
- "This should work..." → run it and see
- "I assume the field is..." → look at the actual data
- "I'll test it later..." → test it now
- "It's too simple to break..." → verify anyway
