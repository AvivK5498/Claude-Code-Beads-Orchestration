# Communication Style

## Core rule

Write in plain Russian. The goal is for a non-programmer to understand on the first read. No anglicisms, calques, or transliterations of English words when a short Russian equivalent exists.

## Trigger: when this rule fires

Before sending **every** response to the user. Applies to all Russian-language text — chat messages, task descriptions, code comments, commit messages.

## What to do

1. **Find marker words in the text and rewrite them.** Common cases:
   - «робастный / робастность» → «надёжный / устойчивый»
   - «итерация» (meaning «attempt / pass») → «попытка», «проход», «шаг»
   - «реджект / реджектится» → «отклоняется / отказ»
   - «коллбэк» → «обратный вызов»
   - «фикс» → «исправление»
   - «майнтейнить» → «поддерживать»
   - «эдж-кейс» → «крайний случай»
   - «trade-off» → «компромисс»
   - «diminishing return» → «убывающая отдача»
   - «overhead» → «накладные расходы»

2. **Any transliteration of an English term in Cyrillic is also under the rule**, if a short Russian equivalent exists:
   - «тенант» → «арендатор»
   - «энтити» → «сущность»
   - «инстанс» → «экземпляр»
   - «пейлоад» → «полезная нагрузка»
   - «митап» → «встреча»
   - «челлендж» → «сложная задача»
   - «дедлайн» → «срок»
   - «деплой» → «развёртывание»
   - «фича» → «возможность / функция»
   - «ассерт» → «проверка»

3. **Latin script in Russian text — replace or explain.** Exceptions that stay as-is: file names, commands, code fragments, paths, git entities, proper names, established technical terms (`git`, `npm`, `PR`, `API`).

4. **If no short Russian equivalent exists** — use the English term and explain it in parentheses on first mention. After that — use the Russian variant or the explained English term.

5. **Naturalized — leave as is:** «коммит» (in git context), «рефакторинг», «бэкенд», «фронтенд», «дебаггер».

## Banned

- Apologizing or adding «replaced X with Y» notes — rewrite silently
- Using jargon when a simple Russian word exists
- Using an English term without explanation when a Russian equivalent exists
- Treating the marker list as closed — these are examples; the rule is broader: any transliteration of an anglicism falls under it
