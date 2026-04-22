<div align="center">

# CLAUDE PROTOCOL

**Структура, которая переживает потерю контекста. Каждая задача отслежена. Каждое решение задокументировано.**

[![npm version](https://img.shields.io/npm/v/claude-protocol?style=for-the-badge&logo=npm&logoColor=white&color=CB3837)](https://www.npmjs.com/package/claude-protocol)
[![GitHub stars](https://img.shields.io/github/stars/weselow/claude-protocol?style=for-the-badge&logo=github&color=181717)](https://github.com/weselow/claude-protocol)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

<br>

```bash
npx claude-protocol init --lang ru
```

<br>

![The Claude Protocol](screenshots/kanbanui.png)

<br>

[Зачем](#зачем) · [Что изменилось в v3](#что-изменилось-в-v3) · [Как работает](#как-работает) · [Установка](#установка) · [Workflow](#workflow) · [Хуки](#хуки) · [FAQ](#faq)

**[English version](README.md)**

</div>

---

## Зачем

Claude Code теряет контекст. Планы исчезают после сжатия. Задачи забываются между сессиями. Изменения идут прямо в main без трассировки.

Claude Protocol решает это тремя вещами:

- **Beads** — персистентное отслеживание задач. Одна задача = один worktree = один PR. Переживает перезапуски и сжатие контекста.
- **Хуки** — enforcement, а не инструкции. Редактирование на main заблокировано. Завершение без чеклиста заблокировано. `git --no-verify` заблокирован.
- **bd prime** — хук SessionStart загружает недавние beads, так что состояние переживает потерю контекста.

Ограничения вместо инструкций. Что заблокировано — нельзя проигнорировать.

## Происхождение

Проект начался как форк [The Claude Protocol](https://github.com/AvivK5498/The-Claude-Protocol) Авива Каплана. Автор оригинала, похоже, прекратил разработку — PR не рассматриваются, а базовые инструменты (beads CLI, API хуков Claude Code) значительно изменились.

v3 — это переписывание с нуля. Другая архитектура, другая философия. Подробности: [decisions-ru.md](docs/decisions-ru.md).

## Что изменилось в v3

### v3.3.0 (2026-04-22)

- **Механизм upgrade** — новая команда `npx claude-protocol upgrade` с
  флагами `--dry-run` и `--all <parent>` для пакетного обновления
  нескольких проектов. Каждое удаление бэкапится в
  `.claude/.upgrades/<timestamp>/`.
- **Memory-система удалена** — `knowledge.jsonl`, `memory-capture.cjs` и
  `recall.cjs` больше нет. Заменены на встроенные `bd remember` /
  `bd memories`. Устаревшие файлы чистятся автоматически при upgrade.
- **Совместимость с bd 1.0.2** — репозиторий bd переехал на gastownhall;
  URL-ы установки обновлены. Workflow больше не использует устаревший
  статус `inreview`.
- **Защита от path traversal** — upgrade никогда не пишет и не удаляет
  что-либо за пределами директории проекта.

Убрали всё, что не улучшает результат. Добавили всё, что улучшает.

**Убрано:**
- 5 специализированных агентов (Scout, Detective, Architect, Scribe, Discovery) — дублировали встроенные возможности Claude Code
- Генерация Tech Supervisor по стеку — 500+ строк контекста на каждый, Claude и так знает эти технологии
- Персоны агентов ("Rex-ревьюер") — устаревший подход к промптам, просто забивает контекст
- MCP Provider Delegator, Kanban UI, Web Interface Guidelines — лишняя инфраструктура
- 19 bash-хуков — заменены на 8 кроссплатформенных Node.js хуков

**Добавлено:**
- Верификация чеклиста — хук блокирует завершение, если требования из описания не отмечены
- Дашборд при старте сессии — показывает открытые задачи, PR ожидающие cleanup, устаревшие beads, последние знания
- Обязательный size check — автоматическое решение: один bead или epic с children
- Требование plan-to-beads — все запланированные задачи должны быть созданы в beads до начала реализации
- Контроль качества LEARNED — конкретный формат: проблема → решение → контекст
- Безопасная установка и обновление — SHA-256 манифест отслеживает пользовательские изменения, `--force` для чистой переустановки
- Справочник команд bd в rules — предотвращает выдумывание несуществующих команд

**Изменено:**
- Правила основаны на триггерах ("создаёшь API endpoint → добавь логирование") вместо справочных документов
- Поиск по базе знаний обязателен перед каждым расследованием
- Dev-правила (implementation, logging, TDD) включены по умолчанию

Подробности: [docs/decisions-ru.md](docs/decisions-ru.md)

## Как работает

### Что устанавливается

```
.claude/
  agents/
    code-reviewer.md        # Adversarial 3-фазный ревью
    merge-supervisor.md     # Протокол разрешения конфликтов
  hooks/                    # 8 Node.js enforcement-хуков
  rules/
    beads-workflow.md       # Жизненный цикл задач, справочник bd
    implementation-standard.md
    logging-standard.md
    tdd-workflow.md
    resilience-standard.md
  skills/
    project-discovery/      # Извлечение конвенций проекта
  settings.json             # Конфигурация хуков
  .manifest.json            # Хеши файлов для безопасных обновлений
CLAUDE.md                   # Инструкции оркестратора
.beads/                     # База задач + база знаний
```

### Безопасно для существующих проектов — и для обновлений

Первая установка и переустановка используют одну команду: `npx claude-protocol init`.

- **Хуки и навыки** — всегда обновляются до последней версии (enforcement-код).
- **Правила и агенты** — обновляются только если вы их не меняли. Изменённые файлы сохраняются; новая версия записывается в `.claude/.upgrades/` для ручного ревью.
- **CLAUDE.md** — секция beads дописывается, если отсутствует. Исходный контент сохраняется.
- **settings.json** — хуки мержатся по типу события. Ваши существующие хуки остаются.
- **.gitignore** — недостающие записи дописываются. Ничего не удаляется.

Используйте `--force` для перезаписи всех файлов, включая изменённые (чистая переустановка).

### Что происходит при старте сессии

При каждом запуске Claude Code хук `session-start` показывает:

- **ACTION REQUIRED** — merged worktrees с незакрытыми beads, устаревшие задачи в `inreview`
- **In Progress** — beads для продолжения работы
- **Ready** — незаблокированные beads, готовые к dispatch
- **Blocked / Stale** — beads ожидающие зависимости или неактивные 3+ дней
- **Recent Knowledge** — последние 5 LEARNED-записей из базы знаний
- **Open PRs** — ваши PR ожидающие ревью

Ручная проверка не нужна. Контекст восстанавливается автоматически.

### Исследование проекта

После установки выполните `/project-discovery` в Claude Code. Команда сканирует кодовую базу и записывает `.claude/rules/project-conventions.md`:

- Обнаруженные технологии и фреймворки
- Конвенции именования и паттерны
- Настройка тестирования и команды
- Анти-паттерны специфичные для проекта

Файл автоматически загружается в контекст каждого агента. Генерация супервайзеров по стеку не нужна.

## Установка

### Требования

- Python 3.11+
- Node.js 20+
- git

### Установить

```bash
npx claude-protocol init --lang ru
```

Перезапустите Claude Code. Выполните `/project-discovery`.

### Опции

| Флаг | Описание |
|------|----------|
| `--project-dir PATH` | Целевая директория (по умолчанию: текущая) |
| `--project-name NAME` | Имя проекта для CLAUDE.md (автоопределяется из package.json / pyproject.toml / Cargo.toml / go.mod) |
| `--no-rules` | Пропустить dev-правила (implementation, logging, TDD, resilience) |
| `--lang en\|ru` | Язык dev-правил (по умолчанию: en) |
| `--force` | Перезаписать все файлы, включая изменённые (чистая переустановка) |

### Локальная разработка (до публикации в npm)

```bash
cd /path/to/claude-protocol && npm link
npx claude-protocol init --lang ru  # работает в любом проекте
```

## Upgrade

Существующие проекты обновляются безопасно — изменённые пользователем файлы
сохраняются; чистятся только артефакты самого claude-protocol.

### Предпросмотр (рекомендуется сначала)

```bash
npx claude-protocol@latest upgrade --dry-run
```

Печатает точный список файлов, директорий и записей settings-хуков, которые
будут изменены. Ничего не трогает.

### Применить

```bash
npx claude-protocol@latest upgrade
```

Запускает init-сценарий, затем удаляет устаревшие артефакты. Каждое
удаление бэкапится в `.claude/.upgrades/<UTC-timestamp>/` — можно
откатиться, скопировав файлы обратно.

### Пакетно (несколько проектов)

```bash
npx claude-protocol@latest upgrade --all /path/to/parent
```

Проходит по всем прямым подпапкам parent-директории, в которых есть
`.beads/`, и обновляет каждую. Комбинируйте с `--dry-run`, чтобы сначала
проверить, что будет сделано.

### Rollback

Директория бэкапа `.claude/.upgrades/<timestamp>/obsolete/` повторяет
структуру проекта. Скопируйте нужные файлы обратно на место. Ничего не
удаляется безвозвратно.

## Workflow

### Каждая задача проходит через beads

```
План → Size check → Создать beads → bd ready → Dispatch → Worktree → PR → Merge → Close
```

**Size check** выполняется автоматически перед созданием beads:
- Больше 3 файлов или несколько доменов (DB + API + frontend) → epic с children
- Больше 50 строк по оценке → рассмотреть декомпозицию
- Иначе → один bead

Один bead = один worktree = один PR = один ревьюируемый diff.

### Параллельная работа

```bash
bd dep add TASK-2 TASK-1    # TASK-2 заблокирован TASK-1
bd close TASK-1              # TASK-2 становится ready
bd ready                     # показывает все незаблокированные задачи
```

Оркестратор диспатчит все ready-задачи параллельно через `Task()`.

### Quick fix

Для изменений до 10 строк на feature branch. На main жёстко заблокировано хуками.

```bash
git checkout -b fix-typo     # обязательно не main
# edit → хук запрашивает подтверждение → commit
```

### Верификация завершения

Субагенты блокируются от завершения если:
- Нет секции `Checklist:` со всеми отмеченными `[x]` пунктами
- Статус bead не `inreview`
- Код не закоммичен и не запушен
- Нет комментария к bead
- Ответ превышает лимиты (25 строк / 1200 символов)

## Хуки

| Хук | Событие | Что делает |
|-----|---------|------------|
| enforce-branch-before-edit | PreToolUse (Edit/Write) | Блокирует редактирование на main. Запрашивает подтверждение на feature branch с именем файла и размером изменения. |
| bash-guard | PreToolUse (Bash) | Блокирует `--no-verify`. Требует описание для `bd create`. Валидирует закрытие epic (все children done, PR merged). |
| validate-completion | SubagentStop | Проверяет worktree, push, статус, чеклист, комментарий, многословность. |
| memory-capture | PostToolUse (Bash) | Извлекает LEARNED-записи → `.beads/memory/knowledge.jsonl` с авто-тегами. |
| session-start | SessionStart | Показывает задачи, merged PR, знания, напоминания ACTION REQUIRED. |
| nudge-claude-md-update | PreCompact | Напоминает обновить CLAUDE.md перед сжатием контекста. |
| hook-utils | — | Общие утилиты: getField, parseBeadId, deny/ask/block, execCommand. |
| recall | — | Поиск по базе знаний: `node .beads/memory/recall.cjs "keyword"`. |

## Dev-правила

Включены по умолчанию. Пропустить: `--no-rules`. На русском: `npx claude-protocol init --lang ru`.

| Правило | Что делает |
|---------|------------|
| implementation-standard | Процесс с подтверждением пользователя. Метрики кода (функция < 30 строк, класс < 200, nesting < 4). Self-review с триггером `/simplify`. |
| logging-standard | На основе триггеров: "создаёшь API endpoint → добавь логирование". Покрывает внешние вызовы, платежи, авторизацию, фоновые задачи. Sentry + Seq. |
| tdd-workflow | На основе триггеров: "новая функция → сначала тест". Цикл RED → GREEN → REFACTOR. Чёткие исключения (конфиги, DTO, миграции). |
| resilience-standard | На основе триггеров: "вызываешь внешний API → что если таймаут/5xx?". Покрывает БД, платежи, файлы, фоновые задачи. Стратегии: retry, fallback, circuit breaker, compensation. |

## FAQ

**В: `bd init` зависает при установке.**
О: Dolt-сервер не запущен. Bootstrap создаёт `.beads/` вручную через 15 секунд. Запустите `bd init` позже когда Dolt будет доступен, или используйте SQLite-бэкенд.

**В: Хуки не работают после установки.**
О: Перезапустите Claude Code. Хуки загружаются из `settings.json` при запуске.

**В: Claude выдумывает команды типа `bd export`.**
О: В `beads-workflow.md` есть полная таблица команд. Если Claude всё равно выдумывает — проверьте что `.claude/rules/` существует.

**В: Что будет, если запустить `init` повторно после обновления claude-protocol?**
О: Изменённые правила и агенты сохраняются — новые версии записываются в `.claude/.upgrades/` для ревью. Хуки и навыки всегда обновляются. Используйте `--force` для чистой переустановки.

**В: Можно использовать без Dolt?**
О: Да. Beads по умолчанию работает с SQLite. Dolt добавляет версионную историю и ветвление для базы задач.

## Благодарности

- [The Claude Protocol](https://github.com/AvivK5498/The-Claude-Protocol) — Авив Каплан, оригинальный проект
- [beads](https://github.com/steveyegge/beads) — Стив Йегге, git-native отслеживание задач
- [`/simplify`](https://github.com/anthropics/claude-code-skills) — Борис Черни, навык упрощения кода

## Лицензия

MIT
