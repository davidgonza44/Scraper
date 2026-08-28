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

function patchLockFs(t, { onStat, onUnlink, onWrite }) {
  const originalStat = fs.statSync;
  const originalUnlink = fs.unlinkSync;
  const originalWrite = fs.writeFileSync;
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
  t.after(() => {
    fs.statSync = originalStat;
    fs.unlinkSync = originalUnlink;
    fs.writeFileSync = originalWrite;
  });
  return { originalStat, originalUnlink, originalWrite };
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
  const livePath = path.join(lockDir, `owned-${liveOwner.pid}-live.lock`);
  const deadPath = path.join(lockDir, 'owned-99999999-dead.lock');
  fs.writeFileSync(livePath, String(liveOwner.pid));
  fs.writeFileSync(deadPath, '99999999');
  stampStale(deadPath);

  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  assert.equal(fs.readFileSync(deadPath, 'utf8'), '99999999');
  assert.equal(lock.countLiveOwners(dir), 2);
  release();
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  process.kill(liveOwner.pid, 0);
});

test('release cannot unlink a replacement owner', (t) => {
  const dir = tempRepo(t);
  const release = lock.acquireHookSlot(dir);
  const lockDir = lockDirOf(dir);
  const ours = listLockNames(dir);
  assert.equal(ours.length, 1);
  const foreign = path.join(lockDir, 'owned-replacement.lock');
  fs.writeFileSync(foreign, 'replacement');
  release();
  assert.equal(fs.readFileSync(foreign, 'utf8'), 'replacement');
  assert.ok(!fs.existsSync(path.join(lockDir, ours[0])));
});

test('abandoned shared slot and reclaim leftovers never block admission and are never unlinked', (t) => {
  const dir = tempRepo(t);
  const leftovers = seedAbandonedSharedClaims(lockDirOf(dir));
  const createdByAcquire = new Set();
  const foreignUnlinks = [];
  patchLockFs(t, {
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
  const livePath = path.join(lockDir, `owned-${liveOwner.pid}-held.lock`);
  fs.writeFileSync(livePath, String(liveOwner.pid));

  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(fs.readFileSync(livePath, 'utf8'), String(liveOwner.pid));
  assert.equal(lock.countLiveOwners(dir), 2);
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
      const names = listLockNames(dir).filter((name) => name.startsWith('owned-'));
      const bName = names.find((name) => !createdByA.has(path.resolve(path.join(info.lockDir, name))));
      assert.ok(bName);
      bOwned = path.join(info.lockDir, bName);
      assert.equal(lock.countLiveOwners(dir), 2);
    },
  });

  assert.ok(aRelease);
  assert.ok(bRelease);
  assert.ok(bOwned);
  assert.equal(fs.existsSync(bOwned), true);
  assert.ok(!aUnlinked.includes(path.resolve(bOwned)));
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
    assert.ok(!aUnlinked.includes(path.resolve(leftover)));
  }
  assert.equal(lock.countLiveOwners(dir), 2);
  assert.ok(lock.countLiveOwners(dir) <= lock.HOOK_LOCK_MAX_INFLIGHT);
  aRelease();
  assert.equal(fs.existsSync(bOwned), true);
  bRelease();
  for (const leftover of leftovers) {
    assert.equal(fs.existsSync(leftover), true, leftover);
  }
});

test('exactly one cleanup winner: overflow unlinks only the private file of that contender', (t) => {
  const dir = tempRepo(t);
  const held = [lock.acquireHookSlot(dir), lock.acquireHookSlot(dir), lock.acquireHookSlot(dir)];
  assert.ok(held.every(Boolean));
  const heldNames = new Set(listLockNames(dir).map((name) => path.resolve(path.join(lockDirOf(dir), name))));
  const createdByContender = new Set();
  const unlinked = [];
  const winners = [];
  patchLockFs(t, {
    onWrite(originalWrite, target, data, options, rest) {
      const result = originalWrite.call(fs, target, data, options, ...rest);
      const opts = options && typeof options === 'object' ? options : {};
      if (opts.flag === 'wx') createdByContender.add(path.resolve(String(target)));
      return result;
    },
    onUnlink(originalUnlink, target, args) {
      const resolved = path.resolve(String(target));
      unlinked.push(resolved);
      if (createdByContender.has(resolved)) winners.push(resolved);
      return originalUnlink.call(fs, target, ...args);
    },
  });

  const first = lock.acquireHookSlot(dir, {
    barrier(stage, info) {
      if (stage !== 'after-private-create') return;
      const second = lock.acquireHookSlot(dir);
      assert.equal(second, null);
    },
  });
  assert.equal(first, null);
  assert.ok(winners.length >= 1);
  const uniqueWinners = new Set(winners);
  for (const owned of uniqueWinners) {
    const count = winners.filter((p) => p === owned).length;
    assert.ok(count >= 1);
    assert.ok(createdByContender.has(owned));
    assert.ok(!heldNames.has(owned));
  }
  for (const heldPath of heldNames) {
    assert.ok(!unlinked.includes(heldPath));
    assert.equal(fs.existsSync(heldPath), true);
  }
  assert.equal(lock.countLiveOwners(dir), lock.HOOK_LOCK_MAX_INFLIGHT);
  held.forEach((release) => release());
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
