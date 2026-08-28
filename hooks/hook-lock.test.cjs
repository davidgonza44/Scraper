const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
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

test('acquires/releases three slots and enforces the cap', (t) => {
  const dir = tempRepo(t);
  const releases = [lock.acquireHookSlot(dir), lock.acquireHookSlot(dir), lock.acquireHookSlot(dir)];
  assert.ok(releases.every(Boolean));
  assert.equal(lock.acquireHookSlot(dir), null);
  releases.forEach((release) => release());
  assert.ok(lock.acquireHookSlot(dir));
});

test('live owners are not evicted and dead stale owners are reclaimable', (t) => {
  const dir = tempRepo(t);
  const lockDir = path.join(dir, lock.HOOK_LOCK_SUBDIR);
  fs.mkdirSync(lockDir);
  fs.writeFileSync(path.join(lockDir, 'slot-0.lock'), String(process.pid));
  fs.writeFileSync(path.join(lockDir, 'slot-1.lock'), '99999999');
  const old = new Date(Date.now() - lock.HOOK_LOCK_STALE_MS - 1000);
  fs.utimesSync(path.join(lockDir, 'slot-1.lock'), old, old);
  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(fs.readFileSync(path.join(lockDir, 'slot-0.lock'), 'utf8'), String(process.pid));
  release();
});

test('stale cleanup cannot delete or acquire a replacement live owner', (t) => {
  const dir = tempRepo(t);
  const lockDir = path.join(dir, lock.HOOK_LOCK_SUBDIR);
  const slot = path.join(lockDir, 'slot-0.lock');
  fs.mkdirSync(lockDir);
  fs.writeFileSync(slot, '99999999');
  stampStale(slot);

  const liveOwner = spawnLiveOwner(t);
  const originalWrite = fs.writeFileSync;
  let replaced = false;
  fs.writeFileSync = function (target, ...args) {
    if (!replaced && String(target).startsWith(`${slot}.reclaim`)) {
      replaced = true;
      fs.unlinkSync(slot); // P2 removes stale A.
      originalWrite.call(fs, slot, String(liveOwner.pid), { flag: 'wx' }); // P2 owns live B.
    }
    return originalWrite.call(fs, target, ...args);
  };
  t.after(() => { fs.writeFileSync = originalWrite; });

  const release = lock.acquireHookSlot(dir);
  assert.equal(replaced, true);
  assert.equal(fs.readFileSync(slot, 'utf8'), String(liveOwner.pid));
  assert.notEqual(fs.readFileSync(slot, 'utf8'), String(process.pid));
  process.kill(liveOwner.pid, 0);
  // Slots 1 or 2 may be acquired, but P1 must not own replacement slot 0.
  assert.ok(release);
  release();
  assert.equal(fs.readFileSync(slot, 'utf8'), String(liveOwner.pid));
});

test('release cannot unlink a replacement owner', (t) => {
  const dir = tempRepo(t);
  const release = lock.acquireHookSlot(dir);
  const slot = path.join(dir, lock.HOOK_LOCK_SUBDIR, 'slot-0.lock');
  fs.writeFileSync(slot, 'replacement');
  release();
  assert.equal(fs.readFileSync(slot, 'utf8'), 'replacement');
});

test('abandoned reclaim sidecars are recovered so stale slots remain acquirable', (t) => {
  const dir = tempRepo(t);
  const lockDir = path.join(dir, lock.HOOK_LOCK_SUBDIR);
  fs.mkdirSync(lockDir);
  for (let slot = 0; slot < lock.HOOK_LOCK_MAX_INFLIGHT; slot++) {
    const slotPath = path.join(lockDir, `slot-${slot}.lock`);
    const reclaimPath = `${slotPath}.reclaim`;
    fs.writeFileSync(slotPath, '99999999');
    fs.writeFileSync(reclaimPath, '88888888\nabandoned');
    stampStale(slotPath);
    stampStale(reclaimPath);
  }

  const release = lock.acquireHookSlot(dir);
  assert.ok(release, 'stale slots with abandoned reclaim sidecars must still be recoverable');
  const owned = [];
  for (let slot = 0; slot < lock.HOOK_LOCK_MAX_INFLIGHT; slot++) {
    const slotPath = path.join(lockDir, `slot-${slot}.lock`);
    if (fs.readFileSync(slotPath, 'utf8').trim() === String(process.pid)) {
      owned.push(slot);
    }
  }
  assert.equal(owned.length, 1);
  release();
});

test('a live reclaim owner is never stolen', (t) => {
  const dir = tempRepo(t);
  const lockDir = path.join(dir, lock.HOOK_LOCK_SUBDIR);
  fs.mkdirSync(lockDir);
  const liveOwner = spawnLiveOwner(t);
  const slot0 = path.join(lockDir, 'slot-0.lock');
  const reclaim0 = `${slot0}.reclaim`;
  fs.writeFileSync(slot0, '99999999');
  fs.writeFileSync(reclaim0, `${liveOwner.pid}\nlive-claim`);
  stampStale(slot0);

  const release = lock.acquireHookSlot(dir);
  assert.ok(release);
  assert.equal(fs.readFileSync(reclaim0, 'utf8'), `${liveOwner.pid}\nlive-claim`);
  assert.equal(fs.readFileSync(slot0, 'utf8'), '99999999');
  assert.notEqual(fs.readFileSync(path.join(lockDir, 'slot-1.lock'), 'utf8').trim(), '');
  release();
  process.kill(liveOwner.pid, 0);
});
