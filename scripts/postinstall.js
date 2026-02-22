#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const os = require('os');

const SKILL_NAME = 'create-beads-orchestration';

// Get paths
const homeDir = os.homedir();
const claudeDir = path.join(homeDir, '.claude');
const claudeSkillsDir = path.join(claudeDir, 'skills', SKILL_NAME);
const packageDir = path.dirname(__dirname);
const sourceSkillDir = path.join(packageDir, 'skills', SKILL_NAME);

console.log('\n📦 Installing beads-orchestration skill...\n');

try {
  // Create ~/.claude/skills/create-beads-orchestration/
  fs.mkdirSync(claudeSkillsDir, { recursive: true });

  // Copy SKILL.md
  const sourceFile = path.join(sourceSkillDir, 'SKILL.md');
  const destFile = path.join(claudeSkillsDir, 'SKILL.md');

  if (!fs.existsSync(sourceFile)) {
    console.warn(`⚠️  Source skill not found: ${sourceFile}`);
    console.warn('   You can run bootstrap manually: npx beads-orchestration bootstrap');
  } else {
    fs.copyFileSync(sourceFile, destFile);
    console.log(`✅ Installed skill to: ${claudeSkillsDir}`);
  }

  // Save package location for bootstrap.py
  const configFile = path.join(claudeDir, 'beads-orchestration-path.txt');
  fs.writeFileSync(configFile, packageDir);
  console.log(`✅ Saved package path to: ${configFile}`);
} catch (err) {
  // Graceful fallback — postinstall failure should not block npm install
  console.warn(`⚠️  Postinstall could not complete: ${err.message}`);
  console.warn('   You can run bootstrap manually: npx beads-orchestration bootstrap');
}

console.log(`
🎉 Installation complete!

Package location: ${packageDir}

Usage:
  In any Claude Code session, run:

    /create-beads-orchestration

  The skill will guide you through setting up orchestration for your project.

`);
