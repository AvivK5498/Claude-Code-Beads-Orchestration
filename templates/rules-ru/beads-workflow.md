# Рабочий процесс Beads

## Beads = единый источник истины. Ничто не должно жить только у тебя в голове.

Контекст сжимается. Сессии перезапускаются. Beads остаются.

### Когда создавать bead — ВСЕГДА если:
- Пользователь просит реализовать, починить, отрефакторить или изменить что-либо
- Ты обнаружил баг, тех-долг или улучшение во время работы
- Задача требует follow-up, который сейчас не делается
- Ты начал нетривиальное расследование

### После планирования — size check, затем создание beads:
Когда план согласован и пользователь подтвердил, ПЕРЕД реализацией:

**Шаг 1: Проверка размера (решение в одну фразу):**
- >3 файлов ИЛИ >1 домена (БД + API, backend + frontend) → epic с дочерними
- В описании есть «а затем», «после этого», несколько шагов → несколько beads
- >50 строк оценки → рассмотри разбиение
- Иначе → один bead

Правило: 1 bead = 1 PR = 1 диф для ревью.

**Шаг 2: Создание beads:**
- Одиночная задача: `bd create "Task" -d "..."`
- Epic: `bd create "Feature" -d "..." --type epic`, затем дети с `--parent` и `--deps`
- Полный список значений `--type` (task, bug, feature, epic, spike, story, milestone, ...): `bd create --help`
- Проверь: `bd list` — план теперь живёт в beads, а не только в контексте

**Шаг 3: Только теперь начинай работу** с `bd ready` → dispatch

### Когда bead НЕ нужен:
- Quick fix, одобренный пользователем (<10 строк, feature branch)
- Чистый research/обсуждение без планируемых изменений кода

### Дисциплина статусов:
- Создан → `open` (по умолчанию)
- Начал работу → `bd update {ID} --status in_progress`
- Отправлен на ревью → `bd comments add {ID} "AWAITING REVIEW"`, bead остаётся в `in_progress` до мержа пользователем
- Смержен/готов → `bd close {ID}`
- **Статус epic:** Когда начинаешь работу над первым ребёнком → `bd update {EPIC_ID} --status in_progress`. Epic остаётся в `in_progress`, пока не завершены все дочерние.
- **Никогда не оставляй bead в `in_progress` между сессиями без причины**

### Обнаружено во время работы:
Когда находишь тех-долг, баги или улучшения во время работы над чем-то другим:
```bash
bd create "Fix: [what]" -d "Discovered while working on {CURRENT_BEAD}: [details]"
```
Не чини это сейчас (если не тривиально). Создай bead, чтобы не забыть.

## Начало задачи

1. Распарси BEAD_ID из dispatch-промпта
2. Создай worktree (ОБЯЗАТЕЛЬНО через bd, не через raw git — см. Banned):
   ```bash
   bd worktree create .worktrees/bd-{BEAD_ID} --branch bd-{BEAD_ID}
   cd .worktrees/bd-{BEAD_ID}
   ```
   Это создаёт `.beads/redirect`, указывающий на основной `.beads/` — все bd команды используют единый dolt-сервер из главного репо. Raw `git worktree add` создал бы теневую копию `.beads/` со своим dolt-сервером, что ведёт к утечке процессов и потере данных.
3. Пометь in progress: `bd update {BEAD_ID} --status in_progress`
4. Если это ребёнок epic — проверь статус epic. Если epic ещё `open`, пометь и его: `bd update {EPIC_ID} --status in_progress`
5. Прочти контекст bead: `bd show {BEAD_ID}` и `bd comments {BEAD_ID}`

## Во время реализации

- Работай ТОЛЬКО в своём worktree: `.worktrees/bd-{BEAD_ID}/`
- Коммить часто с понятными сообщениями
- Логируй прогресс: `bd comments add {BEAD_ID} "Completed X, working on Y"`

## Завершение задачи

Выполни ВСЕ шаги по порядку:

1. **Самоверификация по требованиям:**
   - Запусти `bd show {BEAD_ID}` — перечитай описание
   - Проверь каждый пункт/требование из описания
   - Если чего-то не хватает — реализуй сейчас, не пропускай
2. `git add -A && git commit -m "..."`
3. `git push origin bd-{BEAD_ID}`
4. Оставь завершающий комментарий: `bd comments add {BEAD_ID} "Completed: [summary]"`
5. Сигнал к ревью: `bd comments add {BEAD_ID} "AWAITING REVIEW"` — оставь bead в статусе `in_progress`; пользователь закроет его после мержа PR.
6. Верни отчёт о завершении (checklist ОБЯЗАТЕЛЕН — хук заблокирует без него):
   ```
   BEAD {BEAD_ID} COMPLETE
   Worktree: .worktrees/bd-{BEAD_ID}
   Checklist:
   - [x] требование 1 из описания
   - [x] требование 2 из описания
   Files: [только имена]
   Tests: pass
   Summary: [1 предложение]
   ```

CLI: `bd prime` для общего обзора, `bd <cmd> --help` для деталей

## Banned

- Работа напрямую в ветке main
- Реализация без BEAD_ID
- Мерж своей ветки (пользователь мержит через PR)
- Редактирование файлов вне своего worktree
- Raw `git worktree add` / `git worktree remove` — ОБЯЗАТЕЛЬНО использовать `bd worktree create` / `bd worktree remove`. Raw git worktree создаёт теневые копии `.beads/`, плодит orphan процессы dolt-server, блокирует удаление файлов и теряет данные beads. См.: документация по механизму `.beads/redirect`.
