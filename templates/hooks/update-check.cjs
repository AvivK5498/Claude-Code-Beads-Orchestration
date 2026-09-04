#!/usr/bin/env node
'use strict';

// Prints the latest published claude-protocol version, or nothing at all.
//
// Its own process on purpose: the session-start hook runs it with a hard time
// limit, and a limit is the only thing that reliably bounds a network call.
// A hook that hangs delays the start of every session.
//
// Silent on every failure — no network, GitHub down, rate limited, unreadable
// cache. A missed check costs nothing; a stack trace at session start costs
// attention.

const fs = require('fs');
const os = require('os');
const path = require('path');

const RELEASES_URL =
  'https://api.github.com/repos/weselow/claude-protocol/releases/latest';
const CACHE_DAYS = 7;
const REQUEST_TIMEOUT_MS = 3000;

/** Where the answer is remembered. CLAUDE_PLUGIN_DATA survives plugin updates. */
function cachePath() {
  const dir = process.env.CLAUDE_PLUGIN_DATA
    || path.join(os.homedir(), '.claude');
  return path.join(dir, 'claude-protocol-update-check.json');
}

function readCache() {
  try {
    const raw = JSON.parse(fs.readFileSync(cachePath(), 'utf8'));
    const age = Date.now() - Number(raw.checkedAt || 0);
    if (age >= 0 && age < CACHE_DAYS * 24 * 60 * 60 * 1000) {
      return typeof raw.latest === 'string' ? raw.latest : null;
    }
  } catch {
    // No cache, or one we cannot read. Both mean the same: ask again.
  }
  return null;
}

function writeCache(latest) {
  try {
    const file = cachePath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ latest, checkedAt: Date.now() }));
  } catch {
    // A cache we cannot write costs one request next time, nothing more.
  }
}

async function main() {
  const cached = readCache();
  if (cached) {
    process.stdout.write(cached);
    return;
  }

  const response = await fetch(RELEASES_URL, {
    headers: {
      'User-Agent': 'claude-protocol-update-check',
      Accept: 'application/vnd.github+json',
    },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!response.ok) return;

  const tag = String((await response.json()).tag_name || '');
  const latest = (tag.match(/\d+\.\d+\.\d+/) || [])[0];
  if (!latest) return;

  writeCache(latest);
  process.stdout.write(latest);
}

main().catch(() => {});
