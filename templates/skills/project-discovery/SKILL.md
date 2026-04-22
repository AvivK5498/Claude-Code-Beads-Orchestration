---
name: project-discovery
description: Analyze existing project and extract conventions, patterns, and architecture into .claude/rules/project-conventions.md
user-invocable: true
---

# Project Discovery

Analyze an existing project codebase and extract everything needed for effective development into `.claude/rules/project-conventions.md`.

## When to Use

- First time working with an existing project
- After major architectural changes
- When CLAUDE.md conventions feel outdated

## Process

### Step 1: Detect Tech Stack

Scan project root for dependency/config files:

```
package.json, tsconfig.json, .csproj, *.sln,
pyproject.toml, requirements.txt, go.mod, Cargo.toml,
Dockerfile, docker-compose.yml, .github/workflows/
```

Extract: languages, frameworks, ORM, libraries with exact versions.

### Step 2: Map Project Structure

Scan directory tree (depth 3-4). Identify:

- Where business logic lives (handlers, services, domain)
- Where API endpoints defined (controllers, routes)
- Where data access lives (repositories, DbContext, queries)
- Where tests live and how they're organized
- Where config/DI setup lives
- Where shared/common code lives

### Step 3: Extract Architecture Patterns

Read 3-5 representative files from each layer. Identify:

- **Architecture style**: vertical slices, layered, clean architecture, modular monolith
- **Request handling**: MediatR handlers, controller logic, minimal API, service layer
- **Data access**: raw ORM (DbContext/Prisma), Repository pattern, CQRS
- **Mapping**: AutoMapper, Mapster, manual mapping, extension methods
- **Validation**: FluentValidation, DataAnnotations, manual, Zod
- **Error handling**: Result pattern, exceptions + middleware, Either monad, custom error types
- **DI approach**: constructor injection, module registration, how services are registered

### Step 4: Extract Naming Conventions

From existing code, detect actual patterns (not guess):

- File naming: PascalCase, kebab-case, camelCase
- Class suffixes: Service, Handler, Repository, Controller, Validator, etc.
- Method naming: async suffix? Get/Find/Fetch preference?
- Interface prefixes: I-prefix or not
- Test naming: MethodName_Scenario_Expected? Should_When? Describe/it?
- Folder structure conventions

### Step 5: Detect Anti-Patterns (What NOT to Use)

Look for signs of deliberate avoidance:

- No Repository interfaces over ORM = "don't wrap ORM"
- No AutoMapper but has Mapster = "use Mapster"
- No try-catch in handlers but has global middleware = "don't catch locally"
- No comments but descriptive names = "self-documenting code preferred"

### Step 6: Detect Testing Conventions

Find test projects/directories. From existing tests detect:

- Framework: xUnit, NUnit, Jest, Vitest, pytest
- Assertion library: FluentAssertions, Shouldly, expect, assert
- Mocking: Moq, NSubstitute, jest.mock, unittest.mock
- Test structure: Arrange-Act-Assert, Given-When-Then
- What's mocked and what's not (real DB? in-memory? testcontainers?)
- Naming pattern of test files and methods

### Step 7: Write Output

Write all findings to `.claude/rules/project-conventions.md` in this format:

```markdown
# Project Conventions

## Tech Stack
- [Language] [version]
- [Framework] [version]
- [ORM] [version]
- [Key libraries]: [list with versions]

## Architecture
- Style: [vertical slices / layered / clean / etc.]
- Request flow: [controller -> handler -> repository / etc.]
- Error handling: [Result pattern / exceptions + middleware / etc.]
- Validation: [where and how]
- Mapping: [library or approach]

## Structure
[actual directory tree with annotations]

## Naming
- Files: [pattern]
- Classes: [suffixes]
- Methods: [conventions]
- Tests: [naming pattern]

## Testing
- Framework: [name]
- Assertions: [library]
- Mocking: [library and approach]
- Test data: [factories / builders / inline]

## Do NOT Use
- [specific anti-patterns for this project]
- [libraries/approaches deliberately avoided]
```

### Step 8: Verify

After writing, ask the user:

> Extracted project conventions to `.claude/rules/project-conventions.md`.
> Please review — are there corrections or additions?

## Important

- Extract ONLY what you can confirm from actual code. Do not guess.
- If a pattern is inconsistent across the codebase (mixed styles), note both and ask the user which is preferred.
- Keep the output concise — pointers and patterns, not explanations of what they are.
- If `.claude/rules/project-conventions.md` already exists, show the user what changed and ask before overwriting.
