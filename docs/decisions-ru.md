# Решения по рефакторингу The Claude Protocol

Документ описывает все решения, принятые в ходе рефакторинга The Claude Protocol v2 → v3. Каждое решение содержит контекст, альтернативы и обоснование.

---

## 1. Что полезно, что бесполезно для Claude Code

### 1.1 Personas — бесполезны

**Было:** 7 агентов с именами и характерами (Rex — code reviewer, Mira — merge supervisor, Scout, Detective, Architect, Scribe, Discovery).

**Решение:** Убрали все personas. Оставили 2 агента (code-reviewer, merge-supervisor) без имён — только технические инструкции.

**Почему:** Personas основаны на старом понимании промптов эпохи GPT-3 ("ты — senior developer"). Claude Code — это модель с сильными встроенными инструкциями. Строка "You are Rex, an adversarial code reviewer" не меняет качество ревью. Конкретный чеклист (проверь SQL injection, проверь error handling) — меняет. Personas просто забивают контекст.

### 1.2 Многоуровневая иерархия агентов — избыточна

**Было:** Orchestrator → Tech Supervisor (генерируется динамически per-stack) → Worker. Плюс 5 специализированных агентов (Scout для поиска, Detective для дебага, Architect для архитектуры и т.д.).

**Решение:** Orchestrator → `Task(subagent_type="general-purpose")`. Без промежуточных супервайзеров. Без специализированных агентов.

**Почему:**
- Специализированные агенты дублируют встроенные возможности Claude Code (Glob, Grep, Read — это и есть "Scout")
- Tech Supervisors генерировались из внешних источников (Web Interface Guidelines Apple, React best practices) — 500+ строк контекста на каждый, при этом Claude и так знает эти технологии
- Каждый промежуточный агент — потеря контекста и overhead на передачу данных
- Конвенции проекта лучше хранить в `.claude/rules/` (auto-loaded) — они попадают в контекст каждого агента автоматически

### 1.3 Constraints > Instructions

**Ключевой принцип:** Блокировка плохих действий через hooks эффективнее чем просьба "пожалуйста, не делай так".

**Примеры:**
- "Не коммить на main" (инструкция) → hook `enforce-branch-before-edit.cjs` физически блокирует Edit/Write на main (constraint)
- "Используй description при создании bead" (инструкция) → hook `bash-guard.cjs` блокирует `bd create` без `-d` (constraint)
- "Не пропускай pre-commit hooks" (инструкция) → hook блокирует `git --no-verify` (constraint)

**Почему:** Claude может проигнорировать инструкцию при длинном контексте или после compaction. Hook сработает всегда.

### 1.4 Trigger-based правила > Reference documents

**Было:** Длинные документы-стандарты (200+ строк каждый) которые Claude должен "помнить".

**Решение:** Правила переписаны как триггеры — "когда ты делаешь X, остановись и сделай Y".

**Почему:** Claude не перечитывает rules при каждом действии. Но триггер ("создаёшь API endpoint → логируй") срабатывает в момент написания кода — это ближе к muscle memory чем к справочнику.

### 1.5 INoT (Instruction, Nudge, output Template) — частично полезен

**Обсуждали:** Метод структурирования промптов с Instruction, Nudge и Template.

**Решение:** Не внедряли как отдельную методологию. Но принцип output template уже используется — completion report субагента имеет фиксированный формат (BEAD COMPLETE, Worktree, Checklist, Files, Tests, Summary), который проверяется хуком.

**Почему:** INoT полезен для one-shot промптов. Для системных правил (rules, hooks) триггеры работают лучше.

---

## 2. Правила разработки

### 2.1 implementation-standard.md

**Что оставили:**
- Процесс с пользователем (обсуждение → ТЗ → подтверждение → реализация)
- Метрики кода (CC < 10, функция < 30 строк, класс < 200, nesting < 4)
- Правило 3-х альтернатив для архитектурных решений
- Self-review субагентом после завершения задачи
- Триггер `/simplify` при изменении >3 файлов или >50 строк

**Что убрали:**
- Всё что дублирует встроенные инструкции Claude Code (не модифицируй файлы которые не читал, предпочитай Edit, не создавай лишних файлов)
- Общие фразы ("пиши качественный код")

### 2.2 logging-standard.md

**Решение:** Trigger-based — список ситуаций когда остановиться и подумать о логах (API endpoint, внешний вызов, платежи, catch/except и т.д.).

**Почему:** Логирование — именно то о чём забывают. Не потому что не знают как, а потому что не думают об этом в момент написания кода. Триггеры решают эту проблему.

### 2.3 tdd-workflow.md

**Решение:** Триггеры + исключения. Когда включается TDD (новая функция, баг-фикс, изменение поведения). Когда НЕ нужен (конфиги, DTO, миграции).

**Почему:** TDD как абсолютное правило не работает — Claude начнёт писать тесты для конфигов. Триггеры + исключения дают баланс.

### 2.4 `/simplify` (Boris Cherny)

**Решение:** Интегрирован как обязательный шаг в self-review: если изменено >3 файлов или >50 строк — вызвать `/simplify`.

**Почему:** Это встроенный skill Claude Code который ищет дублирование, мёртвый код, возможности упрощения. Бесплатно и эффективно.

---

## 3. Beads Workflow

### 3.1 Beads как single source of truth

**Решение:** ВСЕ задачи создаются в beads. Не в markdown, не в TodoWrite, не "в голове". Beads переживают compaction, перезапуски сессий, смену контекста.

**Почему:** Главная проблема Claude Code — потеря контекста. После compaction или новой сессии агент не помнит что планировал. Beads — persistent storage которое всегда доступно через `bd list`, `bd ready`.

### 3.2 Обязательный size check после планирования

**Решение:** После утверждения плана — обязательная проверка перед созданием beads:
- >3 файлов или >1 домен → epic с children
- >50 строк → рассмотреть декомпозицию
- Иначе → один bead

**Почему:** Без этого Claude либо создаёт один гигантский bead, либо дробит мелочь на 10 подзадач. Конкретные критерии убирают субъективность.

### 3.3 Plan → Beads → Work (строгий порядок)

**Решение:** После завершения plan mode ВСЕ задачи из плана должны быть созданы в beads ДО начала реализации.

**Почему:** Если начать работу до создания beads — часть задач потеряется при compaction. План живёт только в контексте, beads — в базе.

### 3.4 Status discipline

**Решение:**
- `open` → создана
- `in_progress` → взята в работу
- `inreview` → на проверке (enforced хуком validate-completion)
- `done` → закрыта

**Enforcement:**
- `inreview` при завершении — хук блокирует субагента если не выставлен
- `in_progress` при старте — инструкция (нет enforcement, bd не хранит историю статусов)
- Закрытие после мержа — `session-start.cjs` показывает ACTION REQUIRED для merged worktrees и beads в `inreview`

### 3.5 Checklist verification при завершении

**Решение:** Субагент обязан перед закрытием:
1. Перечитать `bd show {ID}` — сверить description с результатом
2. Включить в completion report секцию `Checklist:` с отметками `[x]`

**Enforcement:** Hook `validate-completion.cjs` блокирует если нет `Checklist:` или есть незакрытые `[ ]`.

**Почему:** Без этого Claude часто говорит "готово" сделав 3 из 5 пунктов задачи. Особенно после compaction.

### 3.6 Discovered tech debt → bead

**Решение:** Если в процессе работы обнаружен техдолг, баг или улучшение — сразу `bd create`, не пытаться чинить inline.

**Почему:** "Потом починю" = никогда. Bead не забудется.

### 3.7 LEARNED comments — конкретные, а не формальные

**Решение:** LEARNED комментарий должен содержать: проблема → решение → контекст.

**BAD:** `LEARNED: fixed async issue`
**GOOD:** `LEARNED: pg connection pool exhaustion under load → set max=20 and idle_timeout=30s. Default max=10 caused 503s at >50 rps`

**Почему:** Вагие записи бесполезны для recall. Конкретные — находятся по ключевым словам и содержат готовое решение.

### 3.8 bd command reference в rules

**Решение:** Добавили таблицу доступных команд bd в `beads-workflow.md` с пометкой "use ONLY these — do NOT invent commands".

**Почему:** Claude выдумывает несуществующие команды (например `bd export`). Явный список решает проблему.

---

## 4. Knowledge Base

### 4.1 Recall перед каждым расследованием

**Решение:** Перед началом любого расследования — обязательный `node .beads/memory/recall.cjs "keyword"`.

**Почему:** Без этого Claude заново решает проблемы которые уже решались в прошлых сессиях.

### 4.2 docs/issues/*.md — отвергнуто

**Обсуждали:** Создавать markdown-заметку после каждой закрытой задачи.

**Решение:** Не делаем. Beads + LEARNED comments + recall.cjs покрывают это без дублирования.

**Почему:** `bd show {ID}` + `bd comments {ID}` уже содержат всё. Markdown — двойная работа без дополнительной ценности для агента.

---

## 5. Инфраструктура

### 5.1 Hooks на Node.js (.cjs), не bash

**Решение:** Все хуки — CommonJS Node.js. Не bash, не ESM.

**Почему:** Кроссплатформенность (Windows). CommonJS потому что Claude Code hooks запускаются через `node`, ESM потребовал бы package.json с `"type": "module"` в папке hooks.

### 5.2 Bootstrap не перезаписывает существующие файлы

**Решение:**
- `CLAUDE.md` — если существует, дописывает beads секцию через разделитель
- `settings.json` — мержит hooks по event type, не дублирует существующие
- `.gitignore` — дописывает недостающие entries

**Почему:** Пользователь может ставить beads в существующий проект с настроенным CLAUDE.md и hooks.

### 5.3 `bd init` с таймаутом

**Решение:** `subprocess.run` с `timeout=15, stdin=DEVNULL`. При таймауте — создать `.beads/` вручную.

**Почему:** `bd init` может зависнуть если Dolt сервер не запущен. Bootstrap не должен блокироваться.

### 5.4 npm link для локальной разработки

**Решение:** `npm link` — одноразовая команда, после которой `npx claude-protocol bootstrap` работает из любого проекта.

**Почему:** Пакет ещё не опубликован в npm. `npm link` создаёт симлинк на текущий код — изменения подхватываются без пересборки.

### 5.5 Skill `/create-claude-protocol` — удалён

**Решение:** Убрали. Установка только через `npx claude-protocol bootstrap`.

**Почему:** Скилл дублировал CLI. Один способ установки проще поддерживать.

---

## 6. Что удалено и почему

| Удалено | Почему |
|---------|--------|
| 5 агентов (Scout, Detective, Architect, Scribe, Discovery) | Дублируют встроенные возможности Claude Code |
| Tech Supervisor generation | 500+ строк контекста без пользы, конвенции лучше в `.claude/rules/` |
| MCP Provider Delegator | Отдельная инфраструктура для внешних провайдеров, не нужна |
| Web Interface Guidelines, React Best Practices | Claude и так это знает, только забивает контекст |
| Beads workflow injection (3 файла) | Заменено одним `beads-workflow.md` в rules (auto-loaded) |
| 19 bash hooks | Заменены 8 Node.js hooks (кроссплатформенность) |
| `skills/subagents-discipline/` | Правила для субагентов лучше через rules + hooks |
| `templates/ui-constraints.md` | Специфично для Apple/SwiftUI, не универсально |
| `scripts/postinstall.js` | Убрали автоматическую установку при npm install |
| SKILL.md (root + skills/) | Установка только через CLI, скилл не нужен |

---

## 7. Итоговая архитектура v3

```
npx claude-protocol bootstrap [--with-rules]
  │
  ├── .beads/                    # Task database (Dolt/SQLite)
  │   └── memory/knowledge.jsonl # Knowledge base
  │
  ├── .claude/
  │   ├── agents/
  │   │   ├── code-reviewer.md   # Adversarial review (no persona)
  │   │   └── merge-supervisor.md # Conflict resolution (no persona)
  │   ├── hooks/                 # 8 Node.js enforcement hooks
  │   ├── rules/
  │   │   ├── beads-workflow.md  # Auto-loaded: workflow + bd reference
  │   │   └── [optional dev rules]
  │   ├── skills/
  │   │   └── project-discovery/ # Extract project conventions
  │   └── settings.json          # Hook configuration
  │
  └── CLAUDE.md                  # Orchestrator instructions
```

**Принцип:** Минимум файлов, максимум enforcement. Constraints > Instructions. Beads = single source of truth.
