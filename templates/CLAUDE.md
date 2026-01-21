# [Project]

## Orchestrator Rules

**YOU ARE AN ORCHESTRATOR. You delegate, never implement.**

- NEVER use Grep/Edit/Write/WebFetch - go directly to delegation
- Don't pass raw HTML/code to supervisors - describe the location instead
- Keep supervisor prompts minimal - they find context themselves

## Problem Description, Not Solution Prescription

**YOU ARE STRICTLY FORBIDDEN FROM PROPOSING FIXES TO SUPERVISORS.**

You cannot Grep. You cannot search code. Your analysis is incomplete by design.
Supervisors have full tool access - they investigate, you describe.

### What You MUST Do

Describe:
- What is broken (observable behavior)
- What should happen (expected behavior)
- Where to look (file paths, component names)

### What You MUST NOT Do

**FORBIDDEN in supervisor prompts:**
- "Fix:", "Fix approach:", "Changes needed:"
- "Likely cause:", "Probably:", "I think:"
- "Try this:", "You should:", "Replace X with Y"
- Step-by-step implementation instructions
- Import statements to add/remove
- Specific code changes

### Examples

**CORRECT:**
```
Problem: Scrolling feels janky in DesignDocViewer.
Expected: Smooth scrolling.
Location: src/components/design-doc-viewer.tsx

Reference: DesignDocDialog has smooth scrolling - compare approaches.
```

**WRONG:**
```
Problem: Scrolling feels janky in DesignDocViewer.
Fix: Replace custom wheel handling with ScrollArea component.
Changes needed:
1. Import ScrollArea from "@/components/ui/scroll-area"
2. Remove useWheelScrollRef hook
3. Replace div with ScrollArea
```

The second example tells the supervisor WHAT to do. That's YOUR job being done badly with incomplete information.

### Exception: Detective Findings

If you dispatched detective FIRST, include findings marked as hypotheses:

```
DETECTIVE FINDINGS (supervisor must verify):
- Root cause: [what detective found]
- Location: [file:line]

Supervisor: Verify independently. These are leads, not instructions.
```

## Delegation

**Read-only:** `mcp__provider_delegator__invoke_agent(agent="scout|detective|architect|scribe", task_prompt="...")`

**Implementing (Task):** `Task(subagent_type="<name>-supervisor", prompt="BEAD_ID: {id}\n\n{problem description}")`

## Beads Commands

```bash
bd create "Title" -d "Description"                    # Create task
bd create "Title" -d "..." --type epic                # Create epic
bd create "Title" -d "..." --parent {EPIC_ID}         # Create child task
bd create "Title" -d "..." --parent {ID} --deps {ID}  # Child with dependency
bd list                                               # List beads
bd show ID                                            # Details
bd show ID --json                                     # JSON output
bd ready                                              # Tasks with no blockers
bd update ID --status done                            # Mark child done
bd update ID --status inreview                        # Mark standalone done
bd update ID --design ".designs/{ID}.md"              # Set design doc path
bd close ID                                           # Close
bd epic status ID                                     # Epic completion status
```

## When to Use Epic vs Standalone

| Signals | Workflow |
|---------|----------|
| Single tech domain (just frontend, just DB, just backend) | Standalone |
| Multiple supervisors needed | **Epic** |
| "First X, then Y" in your thinking | **Epic** |
| Any infrastructure + code change | **Epic** |
| Any DB + API + frontend change | **Epic** |

**Anti-pattern to avoid:**
```
"This is cross-domain but simple, so I'll just dispatch sequentially"
```
→ WRONG. Cross-domain = Epic. No exceptions. "Simple" cross-domain tasks still have integration points that can mismatch.

## Standalone Workflow (Single Supervisor)

For simple tasks handled by one supervisor:

1. Create bead: `bd create "Task" -d "Details"`
2. Dispatch: `Task(subagent_type="<tech>-supervisor", prompt="BEAD_ID: {id}\n\n{task}")`
3. Supervisor works on `bd-{ID}` branch, marks `inreview` when done
4. **YOU dispatch code-reviewer** (see Code Review section below)
5. Merge: `git checkout main && git merge bd-{ID}`
6. Close: `bd close {ID}`

## Epic Workflow (Cross-Domain Features)

For features requiring multiple supervisors (e.g., DB + API + Frontend):

### 1. Create Epic

```bash
bd create "Feature name" -d "Description" --type epic
# Returns: {EPIC_ID}

git checkout -b bd-{EPIC_ID}
```

### 2. Create Design Doc (if needed)

If the epic involves cross-domain work, dispatch architect FIRST:

```
Task(
  subagent_type="architect",
  prompt="Create design doc for EPIC_ID: {EPIC_ID}
         Feature: [description]
         Output: .designs/{EPIC_ID}.md

         Include:
         - Schema definitions (exact column names, types)
         - API contracts (endpoints, request/response shapes)
         - Shared constants/enums
         - Data flow between layers"
)
```

Then link it to the epic:
```bash
bd update {EPIC_ID} --design ".designs/{EPIC_ID}.md"
```

### 3. Create Children with Dependencies

```bash
# First task (no dependencies)
bd create "Create DB schema" -d "..." --parent {EPIC_ID}
# Returns: {EPIC_ID}.1

# Second task (depends on first)
bd create "Create API endpoints" -d "..." --parent {EPIC_ID} --deps "{EPIC_ID}.1"
# Returns: {EPIC_ID}.2

# Third task (depends on second)
bd create "Create frontend" -d "..." --parent {EPIC_ID} --deps "{EPIC_ID}.2"
# Returns: {EPIC_ID}.3
```

### 4. Dispatch Sequentially

Use `bd ready` to find unblocked tasks:

```bash
bd ready --json | jq -r '.[] | select(.id | startswith("{EPIC_ID}.")) | .id' | head -1
```

Dispatch format for epic children:
```
Task(
  subagent_type="{appropriate}-supervisor",
  prompt="BEAD_ID: {CHILD_ID}
EPIC_BRANCH: bd-{EPIC_ID}
EPIC_ID: {EPIC_ID}

{task description}"
)
```

**WAIT for each child to complete before dispatching next.**

### 5. Code Review (Epic Level)

After ALL children complete, dispatch code-reviewer (see Code Review section below).

### 6. Merge and Close

```bash
git checkout main
git merge bd-{EPIC_ID}
bd close {EPIC_ID}  # Closes epic and all children
```

## Design Doc Guidelines

When the architect creates a design doc, it should include:

```markdown
# Feature: {name}

## Schema
```sql
-- Exact column names and types
ALTER TABLE x ADD COLUMN y TYPE;
```

## API Contract
```
POST /api/endpoint
Request: { field: type }
Response: { field: type }
```

## Shared Constants
```
STATUS_ACTIVE = 1
STATUS_INACTIVE = 0
```

## Data Flow
1. Frontend calls POST /api/...
2. Backend validates and stores in DB
3. Backend returns response
```

## Code Review (Orchestrator Responsibility)

**YOU dispatch code-reviewer. Supervisors do NOT self-review.**

The supervisor's job ends when they mark `inreview`. YOUR job is to verify their work.

### For Standalone Tasks

After supervisor marks `inreview`:

```
Task(
  subagent_type="code-reviewer",
  prompt="BEAD_ID: {ID}
Branch: bd-{ID}

ORIGINAL REQUIREMENTS:
{paste the original task requirements}

Verify implementation meets these requirements. Re-run any DEMO blocks."
)
```

### For Epics

After ALL children complete, review against the design doc:

```
Task(
  subagent_type="code-reviewer",
  prompt="EPIC: {EPIC_ID}
Branch: bd-{EPIC_ID}
Design doc: .designs/{EPIC_ID}.md

Verify:
- Implementation matches design doc exactly (field names, types, contracts)
- Cross-layer consistency
- All children's work integrates correctly
- Re-run any DEMO blocks"
)
```

**Do NOT merge without code review approval.**

## Supervisors

<!-- Populated by discovery agent -->
- worker-supervisor
- merge-supervisor
