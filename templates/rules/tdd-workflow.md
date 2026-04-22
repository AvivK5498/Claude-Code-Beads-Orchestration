# TDD Workflow

## Main Rule

No production code without a failing test. Wrote code before test — delete it, start with test.

## Triggers: when TDD kicks in

When writing code, **stop and write a test first** if you:

- Create a new function/method/class
- Fix a bug — first a test reproducing the bug
- Change behavior of existing code
- Add validation or a business rule
- Write error handling with specific logic

## Exceptions (TDD NOT needed)

- Configuration files
- Simple DTOs/models without logic
- One-off scripts/migrations
- Prototypes (but then delete and rewrite with TDD)

## RED → GREEN → REFACTOR Cycle

1. **RED** — write one test for one behavior. Run — it must fail
2. **GREEN** — write minimal code to make the test pass. No "while I'm at it"
3. **REFACTOR** — improve code with green tests. Run tests after each change
4. **Repeat** for the next behavior

## Prohibitions

- Don't change the test to match broken code — change code to match the test
- Don't write 100 lines then run tests — max 10-15 lines between runs
- Don't assume tests pass — always actually run them
- Don't keep code "as reference" — delete means delete

## Mocks: minimum and with understanding

- Only mock external dependencies (API, DB, filesystem)
- Before mocking ask: "what side effects of this method does the test depend on?"
- Don't test mock behavior — test real code
- Mock more complex than the test — use integration test instead
- Incomplete mock (missing fields from real response) — it's a bug, not saving effort
