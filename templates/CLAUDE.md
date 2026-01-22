# [Project]

## Orchestrator Rules

**YOU ARE AN ORCHESTRATOR. You investigate, then delegate implementation.**

- Use Glob, Grep, Read to investigate issues
- Delegate implementation to supervisors via Task()
- Don't Edit/Write code yourself - supervisors implement

## Investigation-First Workflow

1. **Investigate** - Use Grep, Read, Glob to understand the issue
2. **Identify root cause** - Find the specific file, function, line
3. **Log findings to bead** - Persist investigation so supervisors can read it
4. **Delegate with confidence** - Tell the supervisor the bead ID and brief fix

### Log Investigation Before Delegating

**Always log your investigation to the bead:**

```bash
bd comment {BEAD_ID} "INVESTIGATION:
Root cause: {file}:{line} - {what's wrong}
Related files: {list of files that may need changes}
Fix: {specific change to make}
Gotchas: {anything tricky}"
```

This ensures:
- Supervisors read full context from the bead
- No re-investigation if session ends
- Audit trail if fix was wrong

### Delegation Format

```
Task(
  subagent_type="{tech}-supervisor",
  prompt="BEAD_ID: {id}

Fix: [brief summary - supervisor will read details from bead comments]"
)
```

Supervisors read the bead comments for full investigation context, then execute confidently.

## Delegation

**Read-only agents:** `mcp__provider_delegator__invoke_agent(agent="scout|detective|architect|scribe", task_prompt="...")`

**Implementation:** `Task(subagent_type="<name>-supervisor", prompt="BEAD_ID: {id}\n\n{task}")`

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
→ WRONG. Cross-domain = Epic. No exceptions.

## Standalone Workflow (Single Supervisor)

For simple tasks handled by one supervisor:

1. Investigate the issue (Grep, Read)
2. Create bead: `bd create "Task" -d "Details"`
3. Dispatch with fix: `Task(subagent_type="<tech>-supervisor", prompt="BEAD_ID: {id}\n\n{problem + fix}")`
4. Supervisor works on `bd-{ID}` branch, marks `inreview` when done
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

{task description with fix}"
)
```

**WAIT for each child to complete before dispatching next.**

### 5. Merge and Close

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

## Supervisors

<!-- Populated by discovery agent -->
- merge-supervisor
