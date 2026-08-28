const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const lock = require('./hook-lock.cjs');

function tempRepo(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hook-lock-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
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
  const old = new Date(Date.now() - lock.HOOK_LOCK_STALE_MS - 1000);
  fs.utimesSync(slot, old, old);

  const originalWrite = fs.writeFileSync;
  let replaced = false;
  fs.writeFileSync = function (target, ...args) {
    if (!replaced && String(target).startsWith(`${slot}.reclaim`)) {
      replaced = true;
      fs.unlinkSync(slot); // P2 removes stale A.
      originalWrite.call(fs, slot, '1', { flag: 'wx' }); // P2 owns live B (PID 1).
    }
    return originalWrite.call(fs, target, ...args);
  };
  t.after(() => { fs.writeFileSync = originalWrite; });

  const release = lock.acquireHookSlot(dir);
  assert.equal(replaced, true);
  assert.equal(fs.readFileSync(slot, 'utf8'), '1');
  // Slots 1 or 2 may be acquired, but P1 must not own replacement slot 0.
  assert.ok(release);
  release();
});

test('release cannot unlink a replacement owner', (t) => {
  const dir = tempRepo(t);
  const release = lock.acquireHookSlot(dir);
  const slot = path.join(dir, lock.HOOK_LOCK_SUBDIR, 'slot-0.lock');
  fs.writeFileSync(slot, 'replacement');
  release();
  assert.equal(fs.readFileSync(slot, 'utf8'), 'replacement');
});
