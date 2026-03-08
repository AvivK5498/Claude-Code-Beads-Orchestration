#!/bin/bash
# Tests for templates/hooks/validate-epic-close.sh
# Focuses on the epic children validation (CHECK 2)
# Mocks bd, git, and gh to isolate the hook logic

set -euo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/templates/hooks/validate-epic-close.sh"
PASS=0
FAIL=0
MOCK_DIR=""

setup_mock_dir() {
  MOCK_DIR=$(mktemp -d)
  # Mock git to skip CHECK 1 (return empty for remote URL)
  cat > "$MOCK_DIR/git" << 'MOCKGIT'
#!/bin/bash
echo ""
MOCKGIT
  chmod +x "$MOCK_DIR/git"

  # Mock gh (should never be reached, but just in case)
  cat > "$MOCK_DIR/gh" << 'MOCKGH'
#!/bin/bash
echo ""
MOCKGH
  chmod +x "$MOCK_DIR/gh"
}

cleanup() {
  [ -n "$MOCK_DIR" ] && rm -rf "$MOCK_DIR"
}
trap cleanup EXIT

run_hook() {
  local tool_input="$1"
  CLAUDE_TOOL_INPUT="$tool_input" PATH="$MOCK_DIR:$PATH" bash "$HOOK" 2>/dev/null
}

assert_allowed() {
  local test_name="$1"
  local tool_input="$2"
  local output
  local exit_code

  output=$(run_hook "$tool_input") && exit_code=0 || exit_code=$?

  if [ "$exit_code" -eq 0 ] && ! echo "$output" | grep -q '"deny"'; then
    echo "PASS: $test_name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $test_name (expected: allowed, got exit=$exit_code, output=$output)"
    FAIL=$((FAIL + 1))
  fi
}

assert_denied() {
  local test_name="$1"
  local tool_input="$2"
  local expected_fragment="${3:-}"
  local output
  local exit_code

  output=$(run_hook "$tool_input") && exit_code=0 || exit_code=$?

  if echo "$output" | grep -q '"deny"'; then
    if [ -n "$expected_fragment" ] && ! echo "$output" | grep -q "$expected_fragment"; then
      echo "FAIL: $test_name (denied but missing expected text: $expected_fragment)"
      FAIL=$((FAIL + 1))
    else
      echo "PASS: $test_name"
      PASS=$((PASS + 1))
    fi
  else
    echo "FAIL: $test_name (expected: denied, got exit=$exit_code, output=$output)"
    FAIL=$((FAIL + 1))
  fi
}

# ---- Test 1: Non-bd-close command ----
test_non_bd_close() {
  setup_mock_dir
  assert_allowed "Non-bd-close command is allowed" '{"command":"echo hello"}'
}

# ---- Test 2: bd close with --force ----
test_force_override() {
  setup_mock_dir
  # bd mock not needed — hook exits before calling bd
  assert_allowed "bd close --force is allowed" '{"command":"bd close BD-001 --force"}'
}

# ---- Test 3: Standalone bead (issue_type=task) ----
test_standalone_task() {
  setup_mock_dir
  cat > "$MOCK_DIR/bd" << 'MOCKBD'
#!/bin/bash
if [ "$1" = "show" ] && [ "$3" = "--json" ]; then
  echo '[{"id":"BD-001","issue_type":"task","status":"in_progress"}]'
elif [ "$1" = "list" ] && [ "$2" = "--json" ]; then
  echo '[{"id":"BD-001","issue_type":"task","status":"in_progress"}]'
fi
MOCKBD
  chmod +x "$MOCK_DIR/bd"

  assert_allowed "Standalone task is allowed to close" '{"command":"bd close BD-001"}'
}

# ---- Test 4: Epic with all children done ----
test_epic_all_done() {
  setup_mock_dir
  cat > "$MOCK_DIR/bd" << 'MOCKBD'
#!/bin/bash
if [ "$1" = "show" ] && [ "$3" = "--json" ]; then
  echo '[{"id":"BD-010","issue_type":"epic","status":"in_progress"}]'
elif [ "$1" = "list" ] && [ "$2" = "--json" ]; then
  echo '[
    {"id":"BD-010","issue_type":"epic","status":"in_progress"},
    {"id":"BD-010.1","issue_type":"task","status":"done"},
    {"id":"BD-010.2","issue_type":"task","status":"done"},
    {"id":"BD-010.3","issue_type":"task","status":"closed"}
  ]'
fi
MOCKBD
  chmod +x "$MOCK_DIR/bd"

  assert_allowed "Epic with all children done/closed is allowed" '{"command":"bd close BD-010"}'
}

# ---- Test 5: Epic with children in inreview ----
test_epic_children_inreview() {
  setup_mock_dir
  cat > "$MOCK_DIR/bd" << 'MOCKBD'
#!/bin/bash
if [ "$1" = "show" ] && [ "$3" = "--json" ]; then
  echo '[{"id":"BD-020","issue_type":"epic","status":"in_progress"}]'
elif [ "$1" = "list" ] && [ "$2" = "--json" ]; then
  echo '[
    {"id":"BD-020","issue_type":"epic","status":"in_progress"},
    {"id":"BD-020.1","issue_type":"task","status":"done"},
    {"id":"BD-020.2","issue_type":"task","status":"inreview"},
    {"id":"BD-020.3","issue_type":"task","status":"inreview"}
  ]'
fi
MOCKBD
  chmod +x "$MOCK_DIR/bd"

  assert_denied "Epic with inreview children is denied" \
    '{"command":"bd close BD-020"}' \
    "incomplete children"
}

# ---- Test 6: Epic with mixed statuses ----
test_epic_mixed_statuses() {
  setup_mock_dir
  cat > "$MOCK_DIR/bd" << 'MOCKBD'
#!/bin/bash
if [ "$1" = "show" ] && [ "$3" = "--json" ]; then
  echo '[{"id":"BD-030","issue_type":"epic","status":"in_progress"}]'
elif [ "$1" = "list" ] && [ "$2" = "--json" ]; then
  echo '[
    {"id":"BD-030","issue_type":"epic","status":"in_progress"},
    {"id":"BD-030.1","issue_type":"task","status":"done"},
    {"id":"BD-030.2","issue_type":"task","status":"inreview"},
    {"id":"BD-030.3","issue_type":"task","status":"in_progress"}
  ]'
fi
MOCKBD
  chmod +x "$MOCK_DIR/bd"

  assert_denied "Epic with mixed statuses is denied" \
    '{"command":"bd close BD-030"}' \
    "incomplete children"
}

# ---- Test 7: Epic with custom complete statuses ----
test_epic_custom_complete_statuses() {
  setup_mock_dir
  cat > "$MOCK_DIR/bd" << 'MOCKBD'
#!/bin/bash
if [ "$1" = "show" ] && [ "$3" = "--json" ]; then
  echo '[{"id":"BD-040","issue_type":"epic","status":"active"}]'
elif [ "$1" = "list" ] && [ "$2" = "--json" ]; then
  echo '[
    {"id":"BD-040","issue_type":"epic","status":"active"},
    {"id":"BD-040.1","issue_type":"task","status":"qa_done"},
    {"id":"BD-040.2","issue_type":"task","status":"archived"}
  ]'
fi
MOCKBD
  chmod +x "$MOCK_DIR/bd"

  export BEADS_COMPLETE_STATUSES="qa_done,archived"
  assert_allowed "Epic with custom complete statuses is allowed" '{"command":"bd close BD-040"}'
  unset BEADS_COMPLETE_STATUSES
}

# ---- Run all tests ----
echo "=== validate-epic-close.sh tests ==="
echo ""

test_non_bd_close
test_force_override
test_standalone_task
test_epic_all_done
test_epic_children_inreview
test_epic_mixed_statuses
test_epic_custom_complete_statuses

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
