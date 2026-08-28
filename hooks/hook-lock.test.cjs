const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const test = require('node:test');

const lock = require('./hook-lock.cjs');

function tempRepo(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function spawnLiveOwner(t) {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    stdio: 'ignore',
  });
  t.after(() => {
    try {
      child.kill('SIGKILL');
    } catch {
      /* already gone */
    }
  });
  assert.ok(child.pid > 0);
  process.kill(child.pid, 0);
  return child;
}

function stampStale(filePath) {
  const old = new Date(Date.now() - lock.HOOK_LOCK_STALE_MS - 1000);
  fs.utimesSync(filePath, old, old);
}

function lockDirOf(dir) {
  return path.join(dir, lock.HOOK_LOCK_SUBDIR);
}

function listLockNames(dir) {
  const lockDir = lockDirOf(dir);
  if (!fs.existsSync(lockDir)) return [];
  return fs.readdirSync(lockDir).filter((name) => name.endsWith('.lock'));
}

function waitUntil(predicate, timeoutMs = 8000) {
  const start = Date.now();
  while (!predicate()) {
    if (Date.now() - start > timeoutMs) {
      throw new Error('timed out waiting for deterministic gate');
    }
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 20);
  }
}

function patchLockFs(t, { onStat, onUnlink, onWrite, created }) {
  const originalStat = fs.statSync;
  const originalUnlink = fs.unlinkSync;
  const originalWrite = fs.writeFileSync;
  const originalRename = fs.renameSync;
  if (onStat) {
    fs.statSync = function patchedStat(target, ...args) {
      return onStat(originalStat, target, args);
    };
  }
  if (onUnlink) {
    fs.unlinkSync = function patchedUnlink(target, ...args) {
      return onUnlink(originalUnlink, target, args);
    };
  }
  if (onWrite) {
    fs.writeFileSync = function patchedWrite(target, data, options, ...rest) {
      return onWrite(originalWrite, target, data, options, rest);
    };
  }
  fs.renameSync = function patchedRename(src, dest, ...args) {
    const result = originalRename.call(fs, src, dest, ...args);
    if (created && created.has(path.resolve(String(src)))) {
      created.add(path.resolve(String(dest)));
    }
    return result;
  };
  t.after(() => {
    fs.statSync = originalStat;
    fs.unlinkSync = originalUnlink;
    fs.writeFileSync = originalWrite;
    fs.renameSync = originalRename;
  });
  return { originalStat, originalUnlink, originalWrite, originalRename };
}

function seedAbandonedSharedClaims(lockDir) {
  fs.mkdirSync(lockDir, { recursive: true });
  const leftovers = [];
  for (let slot = 0; slot < lock.HOOK_LOCK_MAX_INFLIGHT; slot++) {
    const slotPath = path.join(lockDir, `slot-${slot}.lock`);
    const reclaimPath = `${slotPath}.reclaim`;
    fs.writeFileSync(slotPath, '99999999');
    fs.writeFileSync(reclaimPath, '88888888\nabandoned');
    stampStale(slotPath);
    stampStale(reclaimPath);
    leftovers.push(slotPath, reclaimPath);
  }
  return leftovers;
}

test('acquires/releases three slots and enforces the cap', (t) => {
  const dir = tempRepo(t);
  const releases = [lock.acquireHookSlot(dir), lock.acquireHookSlot(dir), lock.acquireHookSlot(dir)];
  assert.ok(releases.every(Boolean));
  assert.equal(lock.countLiveOwners(dir), lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.equal(lock.acquireHookSlot(dir), null);
  assert.equal(lock.countLiveOwners(dir), lock.HOOK_LOCK_MAX_INFLIGHT);
  releases.forEach((release) => release());
  assert.equal(lock.countLiveOwners(dir), 0);
  assert.ok(lock.acquireHookSlot(dir));
});

test('live owners are not evicted and dead stale owners do not consume the cap', (t) => {
  const dir = tempRepo(t);
  const lockDir = lockDirOf(dir);
  fs.mkdirSync(lockDir);
  const liveOwner = spawnLiveOwner(t);
  const livePath = path.join(lockDir, `owned-${liveOwner.pid}-aaaaaaaaaaaaaaaa.lock`);
  const deadPath = path.join(lockDir, 'owned-99999999-deaddeaddeaddead.lock');
  fs.writeFileSync(livePath, String(liveOwner.pid));
  fs.writeFileSync(deadPath, '99999999');
  stampStale(deadPath);

  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  assert.equal(fs.existsSync(deadPath), false);
  assert.equal(lock.countLiveOwners(dir), 1);
  release();
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  process.kill(liveOwner.pid, 0);
});

test('release cannot unlink a replacement owner', (t) => {
  const dir = tempRepo(t);
  const first = lock.acquireHookSlot(dir);
  const replacement = lock.acquireHookSlot(dir);
  assert.ok(first);
  assert.ok(replacement);
  assert.equal(lock.countLiveOwners(dir), 2);
  first();
  assert.equal(lock.countLiveOwners(dir), 1);
  replacement();
  assert.equal(lock.countLiveOwners(dir), 0);
});

test('abandoned shared slot and reclaim leftovers never block admission and are never unlinked', (t) => {
  const dir = tempRepo(t);
  const leftovers = seedAbandonedSharedClaims(lockDirOf(dir));
  const createdByAcquire = new Set();
  const foreignUnlinks = [];
  patchLockFs(t, {
    created: createdByAcquire,
    onWrite(originalWrite, target, data, options, rest) {
      const result = originalWrite.call(fs, target, data, options, ...rest);
      const opts = options && typeof options === 'object' ? options : {};
      if (opts.flag === 'wx') createdByAcquire.add(path.resolve(String(target)));
      return result;
    },
    onUnlink(originalUnlink, target, args) {
      const resolved = path.resolve(String(target));
      if (!createdByAcquire.has(resolved)) foreignUnlinks.push(resolved);
      return originalUnlink.call(fs, target, ...args);
    },
  });

  const release = lock.acquireHookSlot(dir);
  assert.ok(release, 'stale leftovers must not consume unique-file admission');
  assert.deepEqual(foreignUnlinks, []);
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
  assert.equal(lock.countLiveOwners(dir), 1);
  release();
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
});

test('a live unique owner is never stolen', (t) => {
  const dir = tempRepo(t);
  const lockDir = lockDirOf(dir);
  fs.mkdirSync(lockDir);
  const liveOwner = spawnLiveOwner(t);
  const livePath = path.join(lockDir, `owned-${liveOwner.pid}-bbbbbbbbbbbbbbbb.lock`);
  fs.writeFileSync(livePath, String(liveOwner.pid));

  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  assert.equal(lock.countLiveOwners(dir), 1);
  release();
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  process.kill(liveOwner.pid, 0);
});

test('a process unlinks only lock files it exclusively created', (t) => {
  const dir = tempRepo(t);
  const leftovers = seedAbandonedSharedClaims(lockDirOf(dir));
  const createdByAcquire = new Set();
  const foreignUnlinks = [];
  patchLockFs(t, {
    created: createdByAcquire,
    onWrite(originalWrite, target, data, options, rest) {
      const result = originalWrite.call(fs, target, data, options, ...rest);
      const opts = options && typeof options === 'object' ? options : {};
      if (opts.flag === 'wx') createdByAcquire.add(path.resolve(String(target)));
      return result;
    },
    onUnlink(originalUnlink, target, args) {
      const resolved = path.resolve(String(target));
      if (!createdByAcquire.has(resolved)) foreignUnlinks.push(resolved);
      return originalUnlink.call(fs, target, ...args);
    },
  });

  const release = lock.acquireHookSlot(dir);
  assert.deepEqual(foreignUnlinks, []);
  assert.ok(release);
  release();
  assert.deepEqual(foreignUnlinks, []);
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
});

test('stale observer paused after observation cannot remove a replacement claim', (t) => {
  const dir = tempRepo(t);
  const leftovers = seedAbandonedSharedClaims(lockDirOf(dir));
  const leftoverSet = new Set(leftovers.map((p) => path.resolve(p)));
  let bRelease = null;
  let bOwned = null;
  let installingB = false;
  const createdByA = new Set();
  const aUnlinked = [];
  patchLockFs(t, {
    created: createdByA,
    onWrite(originalWrite, target, data, options, rest) {
      const result = originalWrite.call(fs, target, data, options, ...rest);
      const opts = options && typeof options === 'object' ? options : {};
      if (opts.flag === 'wx' && !installingB) createdByA.add(path.resolve(String(target)));
      return result;
    },
    onUnlink(originalUnlink, target, args) {
      const resolved = path.resolve(String(target));
      if (createdByA.has(resolved) || leftoverSet.has(resolved) || (bOwned && resolved === path.resolve(bOwned))) {
        aUnlinked.push(resolved);
      }
      return originalUnlink.call(fs, target, ...args);
    },
  });

  const aRelease = lock.acquireHookSlot(dir, {
    barrier(stage, info) {
      if (stage !== 'after-private-create' || bRelease) return;
      // Process A has observed leftovers and created its private claim.
      // Process B now replaces/acquires while A is still paused.
      installingB = true;
      try {
        bRelease = lock.acquireHookSlot(dir);
      } finally {
        installingB = false;
      }
      assert.ok(bRelease);
      assert.equal(lock.countLiveOwners(dir), 1);
    },
  });

  assert.ok(aRelease);
  assert.ok(bRelease);
  assert.equal(lock.countLiveOwners(dir), 2);
  assert.ok(lock.countLiveOwners(dir) <= lock.HOOK_LOCK_MAX_INFLIGHT);
  aRelease();
  assert.equal(lock.countLiveOwners(dir), 1);
  bRelease();
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
});

test('exactly one cleanup winner: overflow unlinks only the private file of that contender', (t) => {
  const dir = tempRepo(t);
  const held = [lock.acquireHookSlot(dir), lock.acquireHookSlot(dir), lock.acquireHookSlot(dir)];
  assert.ok(held.every(Boolean));
  assert.equal(lock.countLiveOwners(dir), lock.HOOK_LOCK_MAX_INFLIGHT);
  const leftovers = seedAbandonedSharedClaims(lockDirOf(dir));
  const createdByContender = new Set();
  const foreignUnlinks = [];
  patchLockFs(t, {
    created: createdByContender,
    onWrite(originalWrite, target, data, options, rest) {
      const result = originalWrite.call(fs, target, data, options, ...rest);
      const opts = options && typeof options === 'object' ? options : {};
      if (opts.flag === 'wx') createdByContender.add(path.resolve(String(target)));
      return result;
    },
    onUnlink(originalUnlink, target, args) {
      const resolved = path.resolve(String(target));
      if (!createdByContender.has(resolved)) foreignUnlinks.push(resolved);
      return originalUnlink.call(fs, target, ...args);
    },
  });

  const first = lock.acquireHookSlot(dir, {
    barrier(stage) {
      if (stage !== 'after-private-create') return;
      const second = lock.acquireHookSlot(dir);
      assert.equal(second, null);
    },
  });
  assert.equal(first, null);
  assert.deepEqual(foreignUnlinks, []);
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
  assert.equal(lock.countLiveOwners(dir), lock.HOOK_LOCK_MAX_INFLIGHT);
  held.forEach((release) => release());
  assert.equal(lock.countLiveOwners(dir), 0);
});

test('four concurrent child processes never exceed three live owners', async (t) => {
  const dir = tempRepo(t);
  const gates = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-gate-'));
  t.after(() => fs.rmSync(gates, { recursive: true, force: true }));
  const startGate = path.join(gates, 'start');
  const doneGate = path.join(gates, 'done');
  const statusDir = path.join(gates, 'status');
  fs.mkdirSync(statusDir);
  const childSrc = path.join(gates, 'acquire-child.cjs');
  fs.writeFileSync(
    childSrc,
    `'use strict';
const fs = require('fs');
const readyPath = process.argv[2];
const startGate = process.argv[3];
const doneGate = process.argv[4];
const statusPath = process.argv[5];
const gitNexusDir = process.argv[6];
fs.writeFileSync(readyPath, 'ready');
const lock = require(${JSON.stringify(require.resolve('./hook-lock.cjs'))});
while (!fs.existsSync(startGate)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
const release = lock.acquireHookSlot(gitNexusDir);
fs.writeFileSync(statusPath, release ? 'held' : 'skip');
while (!fs.existsSync(doneGate)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
if (release) release();
`,
  );

  const children = [];
  for (let i = 0; i < 4; i++) {
    const statusPath = path.join(statusDir, `child-${i}`);
    const readyPath = path.join(statusDir, `ready-${i}`);
    let stderr = '';
    const childEnv = { ...process.env };
    delete childEnv.NODE_TEST_CONTEXT;
    const child = spawn(process.execPath, [childSrc, readyPath, startGate, doneGate, statusPath, dir], {
      stdio: ['ignore', 'ignore', 'pipe'],
      env: childEnv,
    });
    assert.ok(child.pid, 'child must start');
    child.on('error', (err) => {
      stderr += String(err);
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    const exit = new Promise((resolve) => child.once('exit', resolve));
    children.push({ child, statusPath, readyPath, getStderr: () => stderr, exit });
  }
  t.after(() => {
    for (const { child } of children) {
      try {
        child.kill('SIGKILL');
      } catch {
        /* already gone */
      }
    }
  });

  waitUntil(() => children.every(({ readyPath }) => fs.existsSync(readyPath)));
  fs.writeFileSync(startGate, 'go');
  waitUntil(
    () => children.every(({ statusPath }) => fs.existsSync(statusPath)),
    8000,
  );
  const outcomes = children.map(({ statusPath, getStderr, child }) => {
    assert.equal(getStderr(), '', `child pid=${child.pid} stderr=${getStderr()}`);
    return fs.readFileSync(statusPath, 'utf8');
  });
  const held = outcomes.filter((v) => v === 'held').length;
  const skipped = outcomes.filter((v) => v === 'skip').length;
  assert.ok(held >= 1, `at least one owner must be admitted: ${outcomes.join(',')}`);
  assert.ok(skipped >= 1, `at least one contender must be denied: ${outcomes.join(',')}`);
  assert.ok(held <= lock.HOOK_LOCK_MAX_INFLIGHT, `held=${held} outcomes=${outcomes.join(',')}`);
  assert.equal(lock.countLiveOwners(dir), held);
  assert.ok(lock.countLiveOwners(dir) <= lock.HOOK_LOCK_MAX_INFLIGHT);
  fs.writeFileSync(doneGate, 'done');
  await Promise.all(children.map(({ exit }) => exit));
});

test('mkdir failure fails closed without creating shared claims', (t) => {
  const dir = tempRepo(t);
  fs.writeFileSync(path.join(dir, lock.HOOK_LOCK_SUBDIR), 'not-a-dir');
  assert.equal(lock.acquireHookSlot(dir), null);
});

function spawnBarrierContenders(t, dir, n, { afterCreate, afterCount } = {}) {
  const gates = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-elect-'));
  t.after(() => fs.rmSync(gates, { recursive: true, force: true }));
  fs.mkdirSync(path.join(gates, 'created'));
  fs.mkdirSync(path.join(gates, 'counted'));
  const childSrc = path.join(gates, 'child.cjs');
  fs.writeFileSync(
    childSrc,
    `'use strict';
const fs = require('fs');
const path = require('path');
const readyPath = process.argv[2];
const startGate = process.argv[3];
const createdDir = process.argv[4];
const allCreated = process.argv[5];
const countedDir = process.argv[6];
const allCounted = process.argv[7];
const doneGate = process.argv[8];
const statusPath = process.argv[9];
const livePath = process.argv[10];
const gitNexusDir = process.argv[11];
const lock = require(${JSON.stringify(require.resolve('./hook-lock.cjs'))});
fs.writeFileSync(readyPath, 'ready');
while (!fs.existsSync(startGate)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
const release = lock.acquireHookSlot(gitNexusDir, {
  barrier(stage, info) {
    if (stage === 'after-private-create') {
      fs.writeFileSync(path.join(createdDir, String(process.pid)), 'created');
      while (!fs.existsSync(allCreated)) {
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
      }
    }
    if (stage === 'after-count-live') {
      fs.writeFileSync(livePath, String(info.live));
      fs.writeFileSync(path.join(countedDir, String(process.pid)), 'counted');
      while (!fs.existsSync(allCounted)) {
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
      }
    }
  }
});
fs.writeFileSync(statusPath, release ? 'held' : 'skip');
while (!fs.existsSync(doneGate)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
if (release) release();
`,
  );
  const children = [];
  for (let i = 0; i < n; i++) {
    const statusPath = path.join(gates, `status-${i}`);
    const readyPath = path.join(gates, `ready-${i}`);
    const livePath = path.join(gates, `live-${i}`);
    const childEnv = { ...process.env };
    delete childEnv.NODE_TEST_CONTEXT;
    const child = spawn(
      process.execPath,
      [
        childSrc,
        readyPath,
        path.join(gates, 'start'),
        path.join(gates, 'created'),
        path.join(gates, 'all-created'),
        path.join(gates, 'counted'),
        path.join(gates, 'all-counted'),
        path.join(gates, 'done'),
        statusPath,
        livePath,
        dir,
      ],
      { stdio: 'ignore', env: childEnv },
    );
    children.push({ child, statusPath, readyPath, livePath });
  }
  t.after(() => {
    for (const { child } of children) {
      try {
        child.kill('SIGKILL');
      } catch {
        /* already gone */
      }
    }
  });
  waitUntil(() => children.every(({ readyPath }) => fs.existsSync(readyPath)));
  fs.writeFileSync(path.join(gates, 'start'), 'go');
  if (afterCreate !== false) {
    waitUntil(() => fs.readdirSync(path.join(gates, 'created')).length === n);
    fs.writeFileSync(path.join(gates, 'all-created'), 'go');
  }
  if (afterCount !== false) {
    waitUntil(() => fs.readdirSync(path.join(gates, 'counted')).length === n);
    fs.writeFileSync(path.join(gates, 'all-counted'), 'go');
  }
  waitUntil(() => children.every(({ statusPath }) => fs.existsSync(statusPath)));
  const liveOwners = lock.countLiveOwners(dir);
  const outcomes = children.map(({ statusPath }) => fs.readFileSync(statusPath, 'utf8'));
  const lives = children.map(({ livePath }) =>
    fs.existsSync(livePath) ? fs.readFileSync(livePath, 'utf8') : '',
  );
  fs.writeFileSync(path.join(gates, 'done'), 'done');
  return { outcomes, lives, children, gates, liveOwners, peakLockFiles: liveOwners };
}

test('four contenders gated after create and count elect at most three owners and at least one winner', (t) => {
  const dir = tempRepo(t);
  const { outcomes, liveOwners, peakLockFiles } = spawnBarrierContenders(t, dir, 4);
  const held = outcomes.filter((v) => v === 'held').length;
  const skipped = outcomes.filter((v) => v === 'skip').length;
  assert.ok(held >= 1, `at least one winner: ${outcomes.join(',')}`);
  assert.ok(held <= lock.HOOK_LOCK_MAX_INFLIGHT, `held=${held}`);
  assert.equal(held, lock.HOOK_LOCK_MAX_INFLIGHT, `election should retain three: ${outcomes.join(',')}`);
  assert.equal(skipped, 1);
  assert.equal(liveOwners, lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.ok(peakLockFiles <= lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.ok(lock.countLiveOwners(dir) <= lock.HOOK_LOCK_MAX_INFLIGHT);
});

test('abandoned unique owned files do not accumulate across acquires', (t) => {
  const dir = tempRepo(t);
  const lockDir = lockDirOf(dir);
  fs.mkdirSync(lockDir);
  const stale = [];
  for (let i = 0; i < 12; i++) {
    const hex = i.toString(16).padStart(16, '0');
    const stalePath = path.join(lockDir, `owned-99999999-${hex}.lock`);
    fs.writeFileSync(stalePath, '99999999');
    stampStale(stalePath);
    stale.push(stalePath);
  }
  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  for (const stalePath of stale) {
    assert.equal(fs.existsSync(stalePath), false, stalePath);
  }
  assert.equal(lock.countLiveOwners(dir), 1);
  release();
  assert.equal(listLockNames(dir).filter((name) => /^owned-\d+-[0-9a-f]+\.lock$/i.test(name)).length, 0);
});

test('concurrent stale cleanup does not delete live unique claims or replacements', (t) => {
  const dir = tempRepo(t);
  const lockDir = lockDirOf(dir);
  fs.mkdirSync(lockDir);
  const liveOwner = spawnLiveOwner(t);
  const livePath = path.join(lockDir, `owned-${liveOwner.pid}-dddddddddddddddd.lock`);
  fs.writeFileSync(livePath, String(liveOwner.pid));
  const stale = [];
  for (let i = 0; i < 8; i++) {
    const hex = (i + 16).toString(16).padStart(16, '0');
    const stalePath = path.join(lockDir, `owned-99999999-${hex}.lock`);
    fs.writeFileSync(stalePath, '99999999');
    stampStale(stalePath);
    stale.push(stalePath);
  }
  const { outcomes, liveOwners } = spawnBarrierContenders(t, dir, 3);
  const held = outcomes.filter((v) => v === 'held').length;
  assert.ok(held >= 1);
  assert.ok(held <= lock.HOOK_LOCK_MAX_INFLIGHT);
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  for (const stalePath of stale) {
    assert.equal(fs.existsSync(stalePath), false, stalePath);
  }
  assert.ok(liveOwners <= lock.HOOK_LOCK_MAX_INFLIGHT);
  process.kill(liveOwner.pid, 0);
});

test('cleanup racing with a live replacement never unlinks the replacement', (t) => {
  const dir = tempRepo(t);
  const lockDir = lockDirOf(dir);
  fs.mkdirSync(lockDir);
  const stalePath = path.join(lockDir, 'owned-99999999-eeeeeeeeeeeeeeee.lock');
  fs.writeFileSync(stalePath, '99999999');
  stampStale(stalePath);
  let bRelease = null;
  let bOwned = null;
  const aRelease = lock.acquireHookSlot(dir, {
    barrier(stage) {
      if (stage !== 'before-stale-gc' || bRelease) return;
      bRelease = lock.acquireHookSlot(dir);
      assert.ok(bRelease);
      assert.equal(lock.countLiveOwners(dir), 1);
    },
  });
  assert.ok(aRelease);
  assert.ok(bRelease);
  assert.equal(fs.existsSync(stalePath), false);
  assert.equal(lock.countLiveOwners(dir), 2);
  aRelease();
  assert.equal(lock.countLiveOwners(dir), 1);
  bRelease();
});

test('crash before release is reclaimed by ownership-safe GC', (t) => {
  const dir = tempRepo(t);
  const childSrc = path.join(os.tmpdir(), `hook-lock-crash-${process.pid}.cjs`);
  fs.writeFileSync(
    childSrc,
    `'use strict';
const fs = require('fs');
const lock = require(${JSON.stringify(require.resolve('./hook-lock.cjs'))});
const dir = process.argv[2];
const statusPath = process.argv[3];
const release = lock.acquireHookSlot(dir);
fs.writeFileSync(statusPath, release ? 'held' : 'skip');
process.kill(process.pid, 'SIGKILL');
`,
  );
  t.after(() => {
    try {
      fs.unlinkSync(childSrc);
    } catch {
      /* already gone */
    }
  });
  const statusPath = path.join(dir, 'crash-status');
  const childEnv = { ...process.env };
  delete childEnv.NODE_TEST_CONTEXT;
  const result = spawnSync(process.execPath, [childSrc, dir, statusPath], {
    stdio: 'ignore',
    env: childEnv,
  });
  assert.equal(result.signal, 'SIGKILL');
  assert.equal(fs.readFileSync(statusPath, 'utf8'), 'held');
  const dbPath = path.join(lockDirOf(dir), lock.OWNERS_DB_FILENAME);
  assert.equal(fs.existsSync(dbPath), true);
  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(lock.countLiveOwners(dir), 1);
  release();
  assert.equal(lock.countLiveOwners(dir), 0);
});

test('GC never deletes foreign live ownership or shared leftovers', (t) => {
  const dir = tempRepo(t);
  const leftovers = seedAbandonedSharedClaims(lockDirOf(dir));
  const liveOwner = spawnLiveOwner(t);
  const livePath = path.join(lockDirOf(dir), `owned-${liveOwner.pid}-ffffffffffffffff.lock`);
  const replacement = path.join(lockDirOf(dir), 'owned-replacement.lock');
  fs.writeFileSync(livePath, String(liveOwner.pid));
  fs.writeFileSync(replacement, 'replacement');
  lock.reclaimStaleOwnedClaims(lockDirOf(dir));
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  assert.equal(fs.readFileSync(replacement, 'utf8'), 'replacement');
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
  process.kill(liveOwner.pid, 0);
});

test('gated four-contender election is stable across repeated runs', (t) => {
  for (let i = 0; i < 8; i++) {
    const dir = tempRepo(t);
    const { outcomes, liveOwners, peakLockFiles } = spawnBarrierContenders(t, dir, 4);
    const held = outcomes.filter((v) => v === 'held').length;
    assert.equal(held, lock.HOOK_LOCK_MAX_INFLIGHT, `run ${i} ${outcomes.join(',')}`);
    assert.equal(liveOwners, lock.HOOK_LOCK_MAX_INFLIGHT);
    assert.ok(peakLockFiles <= lock.HOOK_LOCK_MAX_INFLIGHT);
  }
});

