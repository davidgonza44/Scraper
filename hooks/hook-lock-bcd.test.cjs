'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const test = require('node:test');

const lock = require('./hook-lock.cjs');

function tempRepo(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-bcd-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function waitUntil(predicate, timeoutMs = 8000, label = 'gate') {
  const start = Date.now();
  while (!predicate()) {
    if (Date.now() - start > timeoutMs) {
      throw new Error(`timed out waiting for ${label}`);
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
  }
}

function startPeakMonitor(dir) {
  let peak = Math.max(0, lock.countLiveOwners(dir));
  const samples = [peak];
  const timer = setInterval(() => {
    const n = lock.countLiveOwners(dir);
    samples.push(n);
    if (n > peak) peak = n;
  }, 5);
  if (typeof timer.unref === 'function') timer.unref();
  return {
    sample() {
      const n = lock.countLiveOwners(dir);
      samples.push(n);
      if (n > peak) peak = n;
      return n;
    },
    stop() {
      clearInterval(timer);
      this.sample();
      return { peak, samples };
    },
  };
}

function spawnScheduledContender(t, { dir, gates, id, claimName }) {
  const childSrc = path.join(gates, `child-${id}.cjs`);
  fs.writeFileSync(
    childSrc,
    `'use strict';
const fs = require('fs');
const path = require('path');
const lock = require(${JSON.stringify(require.resolve('./hook-lock.cjs'))});
const id = process.argv[2];
const gitNexusDir = process.argv[3];
const claimName = process.argv[4];
const gates = process.argv[5];
const readyPath = path.join(gates, 'ready-' + id);
const startPath = path.join(gates, 'start-' + id);
const createdPath = path.join(gates, 'created-' + id);
const admitReadyPath = path.join(gates, 'admit-ready-' + id);
const admitGoPath = path.join(gates, 'admit-go-' + id);
const statusPath = path.join(gates, 'status-' + id);
const donePath = path.join(gates, 'done');
fs.writeFileSync(readyPath, 'ready');
while (!fs.existsSync(startPath)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
const release = lock.acquireHookSlot(gitNexusDir, {
  claimName,
  barrier(stage) {
    if (stage === 'after-private-create') {
      fs.writeFileSync(createdPath, 'created');
    }
    if (stage === 'before-admission' || stage === 'before-promote') {
      fs.writeFileSync(admitReadyPath, 'ready');
      while (!fs.existsSync(admitGoPath)) {
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
      }
    }
  },
});
fs.writeFileSync(statusPath, release ? 'held' : 'skip');
while (!fs.existsSync(donePath)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
if (release) release();
`,
  );
  const childEnv = { ...process.env };
  delete childEnv.NODE_TEST_CONTEXT;
  const child = spawn(process.execPath, [childSrc, id, dir, claimName, gates], {
    stdio: 'ignore',
    env: childEnv,
  });
  t.after(() => {
    try {
      child.kill('SIGKILL');
    } catch {
      /* already gone */
    }
  });
  return child;
}

function spawnDelayContender(t, { dir, gates, id, delayMs }) {
  const childSrc = path.join(gates, `stress-${id}.cjs`);
  fs.writeFileSync(
    childSrc,
    `'use strict';
const fs = require('fs');
const path = require('path');
const lock = require(${JSON.stringify(require.resolve('./hook-lock.cjs'))});
const delayMs = Number(process.argv[2]);
const gitNexusDir = process.argv[3];
const startPath = process.argv[4];
const statusPath = process.argv[5];
const donePath = process.argv[6];
const readyPath = process.argv[7];
fs.writeFileSync(readyPath, 'ready');
while (!fs.existsSync(startPath)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
if (delayMs > 0) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delayMs);
}
const release = lock.acquireHookSlot(gitNexusDir);
fs.writeFileSync(statusPath, release ? 'held' : 'skip');
while (!fs.existsSync(donePath)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
if (release) release();
`,
  );
  const childEnv = { ...process.env };
  delete childEnv.NODE_TEST_CONTEXT;
  const statusPath = path.join(gates, `status-${id}`);
  const readyPath = path.join(gates, `ready-${id}`);
  const child = spawn(
    process.execPath,
    [childSrc, String(delayMs), dir, path.join(gates, 'start'), statusPath, path.join(gates, 'done'), readyPath],
    { stdio: 'ignore', env: childEnv },
  );
  t.after(() => {
    try {
      child.kill('SIGKILL');
    } catch {
      /* already gone */
    }
  });
  return { child, statusPath, readyPath };
}

test('lock admission is a single SQLite BEGIN IMMEDIATE decision', () => {
  const source = fs.readFileSync(path.join(__dirname, 'hook-lock.cjs'), 'utf8');
  assert.match(source, /BEGIN IMMEDIATE/);
  assert.match(source, /DatabaseSync/);
  assert.match(source, /CREATE TRIGGER IF NOT EXISTS owners_cap/);
  assert.doesNotMatch(source, /snapshotLiveClaims/);
  assert.doesNotMatch(source, /myRank/);
  assert.doesNotMatch(source, /pendingName/);
  assert.doesNotMatch(source, /fs\.renameSync/);
});

test('B/C/D reverse-promotion with one held owner never exceeds three live owners at any sample', (t) => {
  const dir = tempRepo(t);
  const releaseA = lock.acquireHookSlot(dir);
  assert.ok(releaseA);
  assert.equal(lock.countLiveOwners(dir), 1);
  t.after(() => {
    try {
      releaseA();
    } catch {
      /* already released */
    }
  });

  const gates = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-bcd-gates-'));
  t.after(() => fs.rmSync(gates, { recursive: true, force: true }));

  const roles = [
    { id: 'B', claimName: 'owned-2-bbbbbbbbbbbbbbbb' },
    { id: 'C', claimName: 'owned-3-cccccccccccccccc' },
    { id: 'D', claimName: 'owned-1-aaaaaaaaaaaaaaaa' },
  ];
  for (const role of roles) {
    spawnScheduledContender(t, { dir, gates, ...role });
  }
  waitUntil(() => roles.every((role) => fs.existsSync(path.join(gates, `ready-${role.id}`))), 8000, 'ready');

  const monitor = startPeakMonitor(dir);
  for (const role of roles) {
    fs.writeFileSync(path.join(gates, `start-${role.id}`), 'go');
  }
  waitUntil(
    () => roles.every((role) => fs.existsSync(path.join(gates, `admit-ready-${role.id}`))),
    8000,
    'all at admission gate',
  );
  assert.equal(lock.countLiveOwners(dir), 1, 'no contender may be admitted before the reverse schedule');
  monitor.sample();

  const admit = (id) => fs.writeFileSync(path.join(gates, `admit-go-${id}`), 'go');

  admit('D');
  waitUntil(() => fs.existsSync(path.join(gates, 'status-D')), 8000, 'D status');
  const afterD = monitor.sample();

  admit('C');
  waitUntil(() => fs.existsSync(path.join(gates, 'status-C')), 8000, 'C status');
  const afterC = monitor.sample();

  admit('B');
  waitUntil(() => fs.existsSync(path.join(gates, 'status-B')), 8000, 'B status');
  const afterB = monitor.sample();

  const outcomes = Object.fromEntries(
    roles.map((role) => [role.id, fs.readFileSync(path.join(gates, `status-${role.id}`), 'utf8')]),
  );
  const heldNew = roles.filter((role) => outcomes[role.id] === 'held').length;
  const { peak, samples } = monitor.stop();

  assert.equal(lock.countLiveOwners(dir), 1 + heldNew);
  assert.ok(heldNew >= 1, `capacity must admit at least one contender: ${JSON.stringify(outcomes)}`);
  assert.equal(
    heldNew,
    2,
    `one held plus three contenders must retain exactly two new owners: ${JSON.stringify(outcomes)}`,
  );
  assert.ok(
    peak <= lock.HOOK_LOCK_MAX_INFLIGHT,
    `peak live owners ${peak} exceeded cap ${lock.HOOK_LOCK_MAX_INFLIGHT}; afterD=${afterD} afterC=${afterC} afterB=${afterB} samples=${samples.join(',')} outcomes=${JSON.stringify(outcomes)}`,
  );
  assert.ok(afterD <= lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.ok(afterC <= lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.ok(afterB <= lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.equal(outcomes.D, 'held');
  assert.equal(outcomes.C, 'held');
  assert.equal(outcomes.B, 'skip');
  fs.writeFileSync(path.join(gates, 'done'), 'done');
  waitUntil(() => lock.countLiveOwners(dir) === 1, 8000, 'B/C/D children released');
  releaseA();
  assert.equal(lock.countLiveOwners(dir), 0);
});

test('four simultaneous contenders with zero held retain exactly three and peak never exceeds the cap', (t) => {
  const dir = tempRepo(t);
  const gates = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-four-'));
  t.after(() => fs.rmSync(gates, { recursive: true, force: true }));
  const roles = ['B', 'C', 'D', 'E'].map((id, i) => ({
    id,
    claimName: `owned-${i + 1}-${'ab'.repeat(8)}`,
  }));
  for (const role of roles) {
    spawnScheduledContender(t, { dir, gates, ...role });
  }
  waitUntil(() => roles.every((role) => fs.existsSync(path.join(gates, `ready-${role.id}`))), 8000, 'ready');
  const monitor = startPeakMonitor(dir);
  for (const role of roles) {
    fs.writeFileSync(path.join(gates, `start-${role.id}`), 'go');
  }
  waitUntil(
    () => roles.every((role) => fs.existsSync(path.join(gates, `admit-ready-${role.id}`))),
    8000,
    'all at gate',
  );
  assert.equal(lock.countLiveOwners(dir), 0);
  for (const role of [...roles].reverse()) {
    fs.writeFileSync(path.join(gates, `admit-go-${role.id}`), 'go');
    waitUntil(() => fs.existsSync(path.join(gates, `status-${role.id}`)), 8000, `${role.id} status`);
    monitor.sample();
  }
  const outcomes = roles.map((role) => fs.readFileSync(path.join(gates, `status-${role.id}`), 'utf8'));
  const held = outcomes.filter((v) => v === 'held').length;
  const { peak } = monitor.stop();
  assert.equal(held, lock.HOOK_LOCK_MAX_INFLIGHT, outcomes.join(','));
  assert.equal(outcomes.filter((v) => v === 'skip').length, 1);
  assert.ok(peak <= lock.HOOK_LOCK_MAX_INFLIGHT, `peak=${peak}`);
  assert.equal(lock.countLiveOwners(dir), lock.HOOK_LOCK_MAX_INFLIGHT);
  fs.writeFileSync(path.join(gates, 'done'), 'done');
});

test('randomized and delayed interleavings never admit a fourth owner', (t) => {
  for (let round = 0; round < 12; round++) {
    const dir = tempRepo(t);
    const gates = fs.mkdtempSync(path.join(os.tmpdir(), `hook-lock-stress-${round}-`));
    t.after(() => fs.rmSync(gates, { recursive: true, force: true }));
    const n = 8;
    const children = [];
    for (let i = 0; i < n; i++) {
      children.push(
        spawnDelayContender(t, {
          dir,
          gates,
          id: String(i),
          delayMs: (i * 7 + round * 3) % 25,
        }),
      );
    }
    waitUntil(() => children.every(({ readyPath }) => fs.existsSync(readyPath)), 8000, `ready round ${round}`);
    const monitor = startPeakMonitor(dir);
    fs.writeFileSync(path.join(gates, 'start'), 'go');
    waitUntil(
      () => children.every(({ statusPath }) => fs.existsSync(statusPath)),
      8000,
      `status round ${round}`,
    );
    const outcomes = children.map(({ statusPath }) => fs.readFileSync(statusPath, 'utf8'));
    const held = outcomes.filter((v) => v === 'held').length;
    const { peak } = monitor.stop();
    assert.ok(held >= 1, `round ${round} ${outcomes.join(',')}`);
    assert.equal(held, lock.HOOK_LOCK_MAX_INFLIGHT, `round ${round} ${outcomes.join(',')}`);
    assert.ok(peak <= lock.HOOK_LOCK_MAX_INFLIGHT, `round ${round} peak=${peak}`);
    assert.equal(lock.countLiveOwners(dir), held);
    fs.writeFileSync(path.join(gates, 'done'), 'done');
  }
});
