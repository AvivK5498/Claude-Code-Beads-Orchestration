# Границы работы с репозиториями

## Главное правило

Работаем только в `weselow/claude-protocol`. Никаких коммитов, отправок, PR, комментариев, слияний в форк-источник `AvivK5498/The-Claude-Protocol` без явного разрешения пользователя.

## Контекст

Проект — независимая переработка форка от `AvivK5498/The-Claude-Protocol`. Исходный репозиторий заброшен, мы переписали его под Claude 4.6+ и опубликовали как отдельный npm-пакет `claude-protocol`. `git remote upstream` сохранён локально для истории, но рабочих действий туда не идёт.

## Запреты

- `git push upstream <ветка>` — никогда, кроме прямой просьбы пользователя
- `gh pr create` без `--repo weselow/claude-protocol` — по умолчанию `gh` может выбрать `upstream` и создать PR в чужом репо. Так уже случилось с ошибочным PR #12 в `AvivK5498/The-Claude-Protocol`
- `gh issue create`, `gh pr comment`, `gh pr merge`, `gh pr close` без `--repo weselow/claude-protocol`
- Любая работа с issues, PR, обсуждениями в `AvivK5498/The-Claude-Protocol` без согласования с пользователем

## Что делать

- `gh` команды: всегда `--repo weselow/claude-protocol`
- Перед любой публикацией чего-либо в `AvivK5498/The-Claude-Protocol` — спросить пользователя
- Если случайно опубликовалось туда — закрыть с пояснением «создано по ошибке», заново создать в `weselow/claude-protocol`
