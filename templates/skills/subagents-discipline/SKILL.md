---
name: subagents-discipline
description: Core engineering principles for implementation tasks
advertise: true
---

# Implementation Principles

## Rule 0: Read the Bead First

Before implementing anything, **read the bead comments** for context:

```bash
bd show {BEAD_ID}
bd comments {BEAD_ID}
```

The orchestrator's dispatch prompt is automatically logged as a DISPATCH comment on the bead. This contains:
- The investigation findings
- Root cause analysis (file, function, line)
- Related files that may need changes
- Gotchas and edge cases

**Use this context.** Don't re-investigate. The comments contain everything you need to implement confidently.

If no dispatch or context comments exist, ask the orchestrator to provide context before proceeding.

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

## Rule 2: Test Functionally (Close the Loop)

**Principle: Optimize for the fastest way to verify your work actually works.**

| You built | Fast verification | Slower alternative |
|-----------|------------------|--------------------|
| API endpoint | `curl` the endpoint, check response | Write integration test |
| Database change | Run migration, query the result | Write migration test |
| Frontend component | Load in browser, interact with it | Write component test |
| CLI tool | Run the command, check output | Write unit test |
| Config change | Restart service, verify behavior | N/A — just verify |

**Two strategies:**

1. **User Journey Tests** — Test actual behavior as a user experiences it:
   ```bash
   # API: curl with real data
   curl -X POST localhost:3000/api/users -d '{"name":"test"}' -H "Content-Type: application/json"

   # CLI: run the command
   bd create "Test" -d "Testing" && bd list

   # Error case: curl with invalid auth
   curl -X POST localhost:3000/api/users -H "Authorization: Bearer invalid"
   ```

2. **Component Tests** — Supplement for regression prevention when fast verification isn't possible:
   - Complex logic with many edge cases
   - Code that runs in environments you can't easily replicate
   - Shared libraries used by multiple consumers

**"Close the Loop" principle:** Run the actual thing. Verify it works. Check error cases.

Good: "Curled endpoint with invalid auth, got 401 as expected"
Bad: "Wrote tests, they compile"

## Rule 3: Use Your Tools

Before claiming you can't fully test:

1. **Check what MCP servers you have access to** - list available tools
2. **If any tool can help verify the feature works**, use it
3. **Be resourceful** - browser automation, database inspection, API testing tools

## Rule 4: Log Your Approach (Optional)

If you deviated from the orchestrator's suggestion, found a better path, or made a choice future maintainers might question:

```bash
bd comment {BEAD_ID} "APPROACH: Used X instead of Y because Z"
```

When to log:
- Deviated from the suggested fix
- Multiple valid solutions, chose one for a specific reason
- Future maintainers might question the approach

Skip if the code is self-explanatory. This is not enforced.

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
