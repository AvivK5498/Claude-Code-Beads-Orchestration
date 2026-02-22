#!/usr/bin/env node
'use strict';

// PreToolUse: NotebookEdit — Block orchestrator from notebook editing

const { deny, runHook } = require('./hook-utils.cjs');

runHook('block-notebook-edit', () => {
  deny('Tool \'NotebookEdit\' blocked. Orchestrators investigate and delegate via Task(). Supervisors implement.');
});
