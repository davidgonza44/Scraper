'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const HOOK_LOCK_SUBDIR = '.hook-locks';
const HOOK_LOCK_MAX_INFLIGHT = 3;
const HOOK_LOCK_STALE_MS = 30000;
const OWNED_CLAIM_RE = /^owned-\d+-[0-9a-f]+\.(lock|pending)$/i;

function pidIsLive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    // ESRCH = process gone. EPERM = process exists but owned by another user.
    if (e && e.code === 'ESRCH') return false;
    return true;
  }
}

function ownerLiveness(ownerStr, mtimeMs, now = Date.now()) {
  let isLive = false;
  if (ownerStr === '') {
    // Owner created the file but hasn't written its PID yet. The wx
    // open+write window is microseconds; treat as live unless stale.
    isLive = true;
  } else {
    const owner = Number.parseInt(ownerStr, 10);
    if (Number.isFinite(owner) && owner > 0) {
      isLive = pidIsLive(owner);
    }
  }
  // For files younger than HOOK_LOCK_STALE_MS, PID-liveness wins -- a
  // slow-but-alive hook is never wrongly evicted. For older files, age is
  // the final arbiter as a defense against PID reuse on long-abandoned
  // claims. 30s >> the hook's internal budget, so a healthy run never
  // crosses this threshold.
  if (isLive && now - mtimeMs > HOOK_LOCK_STALE_MS) {
    isLive = false;
  }
  return isLive;
}

function readOwnerMetadata(fd) {
  const stat = fs.fstatSync(fd);
  const buf = Buffer.alloc(64);
  const n = fs.readSync(fd, buf, 0, 64, 0);
  const ownerStr = buf.slice(0, n).toString('utf-8').trim().split(/\r?\n/, 1)[0] || '';
  return {
    stat,
    ownerStr,
    isLive: ownerLiveness(ownerStr, stat.mtimeMs),
  };
}

function tryCreateExclusive(filePath, contents) {
  try {
    fs.writeFileSync(filePath, contents, { flag: 'wx' });
    return true;
  } catch {
    return false;
  }
}

function uniqueOwnedClaimPath(lockDir, suffix) {
  const nonce = crypto.randomBytes(8).toString('hex');
  return path.join(lockDir, `owned-${process.pid}-${nonce}${suffix}`);
}

function runBarrier(sync, stage, info) {
  if (sync && typeof sync.barrier === 'function') {
    sync.barrier(stage, info);
  }
}

function unlinkOwnedPath(ownedPath) {
  // Unlink only a unique pathname this process exclusively created, or a
  // unique owned claim proven dead. Never unlink a shared slot/.reclaim
  // pathname based on an earlier inode, token, PID, or timestamp observation.
  try {
    fs.unlinkSync(ownedPath);
  } catch {
    /* already removed or unreadable */
  }
}

function isOwnedClaimName(name) {
  return OWNED_CLAIM_RE.test(name);
}

function isHeldLockName(name) {
  return isOwnedClaimName(name) && name.toLowerCase().endsWith('.lock');
}

function isPendingName(name) {
  return isOwnedClaimName(name) && name.toLowerCase().endsWith('.pending');
}

function isLiveLockPath(filePath) {
  let fd;
  try {
    fd = fs.openSync(filePath, 'r');
  } catch (err) {
    if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) {
      return false;
    }
    // Exists but unreadable: count as live so admission fails closed
    // rather than admitting a 4th owner.
    return true;
  }
  try {
    return readOwnerMetadata(fd).isLive;
  } catch {
    return true;
  } finally {
    try {
      fs.closeSync(fd);
    } catch {
      /* already closed */
    }
  }
}

function isProvenDeadOwnedClaim(filePath) {
  let fd;
  try {
    fd = fs.openSync(filePath, 'r');
  } catch {
    // Unreadable or missing: fail closed. Never delete a claim whose
    // ownership cannot be proven dead.
    return false;
  }
  try {
    return !readOwnerMetadata(fd).isLive;
  } catch {
    return false;
  } finally {
    try {
      fs.closeSync(fd);
    } catch {
      /* already closed */
    }
  }
}

function snapshotLiveClaims(lockDir) {
  let names;
  try {
    names = fs.readdirSync(lockDir);
  } catch {
    return null;
  }
  const held = [];
  const pending = [];
  for (const name of names) {
    if (!isOwnedClaimName(name)) continue;
    if (!isLiveLockPath(path.join(lockDir, name))) continue;
    if (isHeldLockName(name)) held.push(name);
    else if (isPendingName(name)) pending.push(name);
  }
  held.sort();
  pending.sort();
  return { held, pending };
}

function reclaimStaleOwnedClaims(lockDir) {
  let names;
  try {
    names = fs.readdirSync(lockDir);
  } catch {
    return;
  }
  for (const name of names) {
    if (!isOwnedClaimName(name)) continue;
    const filePath = path.join(lockDir, name);
    if (isProvenDeadOwnedClaim(filePath)) unlinkOwnedPath(filePath);
  }
}

function countLiveOwners(gitNexusDir) {
  const lockDir = path.join(gitNexusDir, HOOK_LOCK_SUBDIR);
  const snapshot = snapshotLiveClaims(lockDir);
  return snapshot ? snapshot.held.length : -1;
}

function acquireHookSlot(gitNexusDir, sync) {
  const lockDir = path.join(gitNexusDir, HOOK_LOCK_SUBDIR);
  try {
    fs.mkdirSync(lockDir, { recursive: true });
  } catch {
    // Cannot create lock dir (read-only fs, cross-user perm denial, out of
    // inodes, etc.) -- fail closed by returning null. Caller skips augment.
    // Fail-open here would let N concurrent hooks all proceed unguarded and
    // reintroduce the #1486 fan-out the guard exists to prevent.
    return null;
  }

  runBarrier(sync, 'before-stale-gc', { lockDir });
  reclaimStaleOwnedClaims(lockDir);
  runBarrier(sync, 'after-stale-gc', { lockDir });

  const myPidStr = String(process.pid);
  const pendingPath = uniqueOwnedClaimPath(lockDir, '.pending');
  if (!tryCreateExclusive(pendingPath, myPidStr)) {
    // Unique pathname collision or the directory became unwritable. Do not
    // fall back to a shared slot/.reclaim pathname.
    return null;
  }
  const pendingName = path.basename(pendingPath);
  const ownedPath = pendingPath.replace(/\.pending$/i, '.lock');

  runBarrier(sync, 'after-private-create', { ownedPath: pendingPath, lockDir });

  const snapshot = snapshotLiveClaims(lockDir);
  const liveCount = snapshot ? snapshot.held.length + snapshot.pending.length : -1;
  runBarrier(sync, 'after-count-live', {
    ownedPath: pendingPath,
    lockDir,
    live: liveCount,
    held: snapshot ? snapshot.held.length : -1,
    pending: snapshot ? snapshot.pending.length : -1,
  });

  if (!snapshot) {
    runBarrier(sync, 'before-private-unlink', { ownedPath: pendingPath, lockDir, reason: 'cap' });
    unlinkOwnedPath(pendingPath);
    return null;
  }

  const capacity = HOOK_LOCK_MAX_INFLIGHT - snapshot.held.length;
  const myRank = snapshot.pending.indexOf(pendingName);
  if (capacity <= 0 || myRank < 0 || myRank >= capacity) {
    runBarrier(sync, 'before-private-unlink', { ownedPath: pendingPath, lockDir, reason: 'cap' });
    unlinkOwnedPath(pendingPath);
    return null;
  }

  try {
    fs.renameSync(pendingPath, ownedPath);
  } catch {
    unlinkOwnedPath(pendingPath);
    unlinkOwnedPath(ownedPath);
    return null;
  }

  const heldAfter = snapshotLiveClaims(lockDir);
  if (!heldAfter) {
    unlinkOwnedPath(ownedPath);
    return null;
  }
  const heldName = path.basename(ownedPath);
  const heldRank = heldAfter.held.indexOf(heldName);
  if (
    heldAfter.held.length > HOOK_LOCK_MAX_INFLIGHT &&
    (heldRank < 0 || heldRank >= HOOK_LOCK_MAX_INFLIGHT)
  ) {
    runBarrier(sync, 'before-private-unlink', { ownedPath, lockDir, reason: 'cap' });
    unlinkOwnedPath(ownedPath);
    return null;
  }

  let released = false;
  const onExit = () => {
    release();
  };
  const release = () => {
    if (released) return;
    released = true;
    process.removeListener('exit', onExit);
    runBarrier(sync, 'before-private-unlink', { ownedPath, lockDir, reason: 'release' });
    unlinkOwnedPath(ownedPath);
  };
  process.on('exit', onExit);
  return release;
}

module.exports = {
  HOOK_LOCK_SUBDIR,
  HOOK_LOCK_MAX_INFLIGHT,
  HOOK_LOCK_STALE_MS,
  acquireHookSlot,
  pidIsLive,
  ownerLiveness,
  countLiveOwners,
  isOwnedClaimName,
  reclaimStaleOwnedClaims,
};
