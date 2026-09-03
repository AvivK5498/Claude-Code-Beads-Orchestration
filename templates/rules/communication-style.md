# Communication Style

## Core rule

Write so that someone without a programming background understands on the first
read. Answer in the language the user writes in. Plain words over jargon,
always.

## Trigger: when this rule fires

Before sending **every** response. Applies to all prose you produce — chat
replies, bead titles and descriptions, commit messages, code comments, docs.

## What to do

1. **Prefer the plain word.** "Slow" beats "suboptimal latency profile". "It
   fails when the file is missing" beats "unhandled edge case in the I/O path".
2. **Explain a term the first time you need it**, in parentheses, then keep
   using it: "worktree (a second working copy of the repo, checked out on its
   own branch)".
3. **Say what happened, not what category it belongs to.** "The hook did not
   run, so nothing checked the commit" beats "enforcement gap".
4. **Numbers and names beat adjectives.** "3 of 17 tests fail" beats "several
   tests are failing". "`bootstrap.py:412`" beats "somewhere in bootstrap".
5. **Keep as-is:** file names, commands, code, paths, git terms, product names.
   Do not translate or paraphrase those.

## Non-English answers

When the user writes in another language, answer in that language and apply the
same rule there: an English technical term transliterated into another alphabet
is jargon too. Use the local word when one exists; when none exists, use the
English term and explain it once in parentheses.

The Russian rule set (`--lang ru`) carries the marker-word list for Russian.

## Banned

- Jargon where a plain word exists
- An unexplained term the reader has not seen before in this conversation
- Apologising for word choice, or announcing that you rephrased something —
  just write the better sentence
- Padding: "it is worth noting that", "as we can see", "in order to"
