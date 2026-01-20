---
name: subagents-discipline
description: Invoke at the start of any implementation task to enforce verification-first development
---

# Implementation Discipline

**Core principle:** Test the FEATURE, not just the component you built.

---

## Three Rules

### Rule 1: Look Before You Code

Before writing code that touches external data (API, database, file, config):

1. **Fetch/read the ACTUAL data** - run the command, see the output
2. **Note exact field names, types, formats** - not what docs say, what you SEE
3. **Code against what you observed** - not what you assumed

This catches: field name mismatches, wrong data shapes, missing fields, format differences.

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

### Rule 2: Test Both Levels

**Component test** catches: logic bugs, edge cases, type errors
**Feature test** catches: integration bugs, auth issues, data flow problems

Both are required. Component test alone is NOT sufficient.

| You built | Component test | Feature test |
|-----------|----------------|--------------|
| API endpoint | curl returns 200 | UI calls API, displays result |
| Database change | Migration runs | App reads/writes correctly |
| Frontend component | Renders, no errors | User can see and interact |
| Full-stack feature | Each piece works alone | End-to-end flow works |

**The pattern:**
1. Build the thing
2. Component test - verify your piece works in isolation
3. Feature test - verify the integrated feature works end-to-end
4. Only then claim done

### Rule 3: Use Your Tools

Before claiming you can't fully test:

1. **Check what MCP servers you have access to** - list available tools
2. **If any tool can help verify the feature works**, use it
3. **Be resourceful** - browser automation, database inspection, API testing tools

"I couldn't test the feature" is only valid after exhausting available options.

---

## DEMO Block (Required)

Every completion must include evidence. Code reviewer will verify this.

```
DEMO:
  COMPONENT:
    Command: [what you ran to test the component]
    Result: [what you observed]

  FEATURE:
    Steps: [how you tested the integrated feature]
    Result: [what you observed - screenshot, output, etc.]
```

### When Full Feature Test Isn't Possible

If you genuinely cannot test end-to-end (long-running job, external service, no browser tools):

```
DEMO:
  COMPONENT:
    Command: curl localhost:3008/api/endpoint
    Result: 200, returns expected data

  FEATURE: PARTIAL
    Verified: [what you could test]
    Needs human check: [what still needs verification]
    Why: [specific reason - no browser MCP, takes 10+ minutes, requires external service]
```

**Not acceptable reasons for PARTIAL:**
- "Server wasn't running" → start it
- "Didn't have test data" → create it
- "Would take too long" → if < 2 minutes, do it

**Acceptable reasons:**
- No browser/UI automation tools available
- External API with rate limits or costs
- Job takes > 5 minutes to complete
- Requires production data that can't be mocked

---

## For Epic Children

If your BEAD_ID contains a dot (e.g., BD-001.2), you're implementing part of a larger feature:

1. **Check for design doc**: `bd show {EPIC_ID} --json | jq -r '.[0].design'`
2. **Read it if it exists** - this is your contract
3. **Match it exactly** - same field names, same types, same shapes

Design docs ensure all pieces fit together. If you deviate, integration fails.

---

## Completion Checklist

Before marking done:

- [ ] Looked at actual data/interfaces before coding (not assumed)
- [ ] Component test passes (your piece works in isolation)
- [ ] Feature test passes OR documented as PARTIAL with valid reason
- [ ] DEMO block included with evidence
- [ ] Used available tools to test (checked MCP servers, used what helps)

---

## Red Flags - Stop and Verify

When you catch yourself thinking:
- "This should work..." → run it and see
- "I assume the field is..." → look at the actual data
- "I'll test it later..." → test it now
- "It's too simple to break..." → verify anyway

When you're about to say:
- "Done!" / "Fixed!" / "Should work now!" → show the DEMO first

---

## The Bottom Line

```
Component test passing ≠ feature works
Curl returning 200 ≠ UI displays correctly
TypeScript compiles ≠ user can use it
```

Test the feature like a user would use it. Then show evidence. Then claim done.
