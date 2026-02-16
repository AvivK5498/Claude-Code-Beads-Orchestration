#!/usr/bin/env node
'use strict';

// UserPromptSubmit: Force clarification on vague requests + epic reminder

const { readStdinJSON, getField, injectText, runHook } = require('./hook-utils');

runHook('clarify-vague-request', () => {
  const input = readStdinJSON();
  const prompt = getField(input, 'prompt');
  const length = prompt.length;

  if (length < 50) {
    injectText(`<system-reminder>
STOP. This request is too short to act on safely.

BEFORE doing anything else, you MUST use the AskUserQuestion tool to clarify:
- What specific outcome does the user want?
- What files/components are involved?
- Are there any constraints or preferences?

Do NOT guess. Do NOT start working. Ask first.
</system-reminder>
`);
  } else if (length < 200) {
    injectText(`<system-reminder>
This request may be ambiguous. Consider using AskUserQuestion to clarify before proceeding.
</system-reminder>
`);
  }

  // Always remind about epic workflow
  injectText(`<cross-domain-check>
CRITICAL: If this task spans multiple supervisors, you MUST create an EPIC.
Cross-domain = Epic. No exceptions.
</cross-domain-check>
`);
});
