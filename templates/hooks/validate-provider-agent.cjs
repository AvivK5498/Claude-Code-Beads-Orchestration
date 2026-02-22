#!/usr/bin/env node
'use strict';

// PreToolUse: mcp__provider_delegator__invoke_agent — Validate allowed agents

const { readStdinJSON, getField, deny, runHook } = require('./hook-utils.cjs');

runHook('validate-provider-agent', () => {
  const input = readStdinJSON();
  const agent = getField(input, 'tool_input.agent');
  const allowed = ['scout', 'detective', 'architect', 'scribe', 'code-reviewer'];

  if (!allowed.includes(agent)) {
    deny(
      `Agent '${agent}' cannot be invoked via Codex. ` +
      'Implementation agents (*-supervisor, discovery) must use Task() with BEAD_ID for beads workflow.'
    );
  }
});
