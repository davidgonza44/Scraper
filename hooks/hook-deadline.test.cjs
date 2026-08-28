'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const deadline = require('./hook-deadline.cjs');
const hook = require('./gitnexus-hook.cjs');

test('internal budget plus safety margin fits the Cursor hook timeout', () => {
  const hooksJson = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', '.cursor', 'hooks.json'), 'utf8'),
  );
  const outerMs = Number(hooksJson.hooks.postToolUse[0].timeout) * 1000;
  assert.equal(outerMs, deadline.CURSOR_HOOK_TIMEOUT_MS);
  assert.ok(deadline.HOOK_TIMEOUT_SAFETY_MARGIN_MS >= 500);
  assert.equal(
    deadline.HOOK_INTERNAL_BUDGET_MS + deadline.HOOK_TIMEOUT_SAFETY_MARGIN_MS,
    deadline.CURSOR_HOOK_TIMEOUT_MS,
  );
  assert.ok(deadline.HOOK_INTERNAL_BUDGET_MS < outerMs);
});

test('slow Git commands reduce the remaining CLI budget', () => {
  let now = 1_000;
  const clock = deadline.createDeadline({ budgetMs: 9_000, nowFn: () => now, startedAt: 1_000 });
  const timeouts = [];
  const spawnSyncFn = (_cmd, _args, opts) => {
    timeouts.push(opts.timeout);
    now += 2_500;
    return { status: 0, stdout: '/tmp/repo\n', stderr: '' };
  };
  assert.equal(hook.gitCommand('/tmp/repo', ['rev-parse', '--show-toplevel'], clock, spawnSyncFn), '/tmp/repo\n');
  assert.equal(timeouts[0], 9_000);
  assert.equal(clock.remainingMs(), 6_500);
  assert.equal(hook.gitCommand('/tmp/repo', ['status', '--porcelain'], clock, spawnSyncFn), '/tmp/repo\n');
  assert.equal(timeouts[1], 6_500);
  assert.equal(clock.remainingMs(), 4_000);
});

test('no CLI starts after deadline exhaustion', () => {
  let now = 0;
  const clock = deadline.createDeadline({ budgetMs: 100, nowFn: () => now, startedAt: 0 });
  now = 100;
  const started = [];
  const result = hook.executeHook(
    {
      cwd: '/tmp/deadline-exhausted',
      tool_name: 'Grep',
      tool_input: { pattern: 'validateUser' },
    },
    {
      deadline: clock,
      spawnSync(cmd, args) {
        started.push({ cmd, args });
        return { status: 0, stdout: '[GitNexus] should-not-run', stderr: '' };
      },
    },
  );
  assert.equal(result.status, 'timeout');
  assert.equal(started.length, 0);
});

test('timeout exits cleanly without emitting partial context', () => {
  let now = 0;
  const clock = deadline.createDeadline({ budgetMs: 50, nowFn: () => now, startedAt: 0 });
  now = 50;
  const logs = [];
  const originalLog = console.log;
  console.log = (...args) => {
    logs.push(args.join(' '));
  };
  try {
    const result = hook.executeHook(
      {
        cwd: '/tmp/deadline-clean',
        tool_name: 'Grep',
        tool_input: { pattern: 'validateUser' },
      },
      { deadline: clock, spawnSync: () => ({ status: 0, stdout: '[GitNexus] partial', stderr: '' }) },
    );
    assert.equal(result.status, 'timeout');
    assert.deepEqual(logs, []);
  } finally {
    console.log = originalLog;
  }
});

test('normal augmentation still has a reasonable CLI budget', () => {
  const clock = deadline.createDeadline({ budgetMs: deadline.HOOK_INTERNAL_BUDGET_MS, nowFn: () => 0, startedAt: 0 });
  const remaining = clock.remainingMs();
  assert.ok(remaining >= 8_000, `remaining=${remaining}`);
  assert.ok(remaining <= deadline.CURSOR_HOOK_TIMEOUT_MS - deadline.HOOK_TIMEOUT_SAFETY_MARGIN_MS);
});

test('spawnWithDeadline never passes a zero timeout', () => {
  const clock = deadline.createDeadline({ budgetMs: 0, nowFn: () => 10, startedAt: 0 });
  let spawned = false;
  const result = deadline.spawnWithDeadline(clock, () => {
    spawned = true;
    return { status: 0, stdout: '', stderr: '' };
  }, 'git', ['status']);
  assert.equal(result.skipped, true);
  assert.equal(spawned, false);
  assert.equal(result.error.code, 'ETIMEDOUT');
});
