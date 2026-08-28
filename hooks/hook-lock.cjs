const fs = require('fs');
const path = require('path');

const HOOK_LOCK_SUBDIR = '.hook-locks';
const HOOK_LOCK_MAX_INFLIGHT = 3;
const HOOK_LOCK_STALE_MS = 30000;

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
  // claims. 30s >> the 7s augment timeout, so a healthy run never crosses
  // this threshold. Reclaim sidecars use the same timeout: they should only
  // exist for the microseconds of stale-slot cleanup.
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

function unlinkIfSameIdentity(filePath, observedStat) {
  if (!observedStat) return false;
  try {
    const current = fs.statSync(filePath);
    if (current.dev === observedStat.dev && current.ino === observedStat.ino) {
      fs.unlinkSync(filePath);
      return true;
    }
  } catch {
    /* replaced or already gone */
  }
  return false;
}

function tryCreateExclusive(filePath, contents) {
  try {
    fs.writeFileSync(filePath, contents, { flag: 'wx' });
    return true;
  } catch {
    return false;
  }
}

function acquireStaleClaim(claimPath, contents) {
  if (tryCreateExclusive(claimPath, contents)) return true;
  let fd;
  try {
    fd = fs.openSync(claimPath, 'r');
  } catch {
    return tryCreateExclusive(claimPath, contents);
  }
  let meta;
  try {
    meta = readOwnerMetadata(fd);
  } catch {
    meta = null;
  } finally {
    try { fs.closeSync(fd); } catch { /* already closed */ }
  }
  if (!meta || meta.isLive) return false;
  unlinkIfSameIdentity(claimPath, meta.stat);
  return tryCreateExclusive(claimPath, contents);
}

function acquireHookSlot(gitNexusDir) {
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

  const myPidStr = String(process.pid);

  for (let slot = 0; slot < HOOK_LOCK_MAX_INFLIGHT; slot++) {
    const slotPath = path.join(lockDir, `slot-${slot}.lock`);
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        fs.writeFileSync(slotPath, myPidStr, { flag: 'wx' });
        let released = false;
        const release = () => {
          if (released) return;
          released = true;
          try {
            // Only unlink if we still own the slot. If we appeared stale and
            // another hook took over, the file now belongs to it -- leave alone.
            const content = fs.readFileSync(slotPath, 'utf-8').trim();
            if (content === myPidStr) fs.unlinkSync(slotPath);
          } catch {
            /* already removed or unreadable */
          }
        };
        process.on('exit', release);
        return release;
      } catch {
        // Slot exists. Decide whether to take it over.
        // Open once and inspect mtime + content via the same fd so there's
        // no TOCTOU between the metadata check and the content read
        // (codeql js/file-system-race).
        let fd;
        let observedStat;
        try {
          fd = fs.openSync(slotPath, 'r');
        } catch {
          continue; // Vanished between EEXIST and open -- retry this slot.
        }
        let isLive = false;
        try {
          const meta = readOwnerMetadata(fd);
          observedStat = meta.stat;
          isLive = meta.isLive;
        } catch {
          /* unreadable -- treat as dead */
        }
        if (isLive) {
          try { fs.closeSync(fd); } catch { /* already closed */ }
          break; // Try the next slot.
        }
        // Serialize stale cleanup with a sidecar created via wx. After owning
        // the claim, compare file identity to the still-open instance we
        // inspected. A contender that replaced it before the claim therefore
        // cannot have its new live lock removed. Abandoned reclaim sidecars
        // are recovered only when their owner is dead or stale; a live
        // reclaim claimant is never stolen.
        const claimPath = `${slotPath}.reclaim`;
        const claimToken = `${myPidStr}-${Date.now()}-${Math.random()}`;
        const claimRecord = `${myPidStr}\n${claimToken}`;
        if (!acquireStaleClaim(claimPath, claimRecord)) {
          try { fs.closeSync(fd); } catch { /* already closed */ }
          break;
        }
        try {
          unlinkIfSameIdentity(slotPath, observedStat);
        } finally {
          try { fs.closeSync(fd); } catch { /* already closed */ }
          try {
            if (fs.readFileSync(claimPath, 'utf8') === claimRecord) fs.unlinkSync(claimPath);
          } catch {
            /* claim already removed or replaced */
          }
        }
        // Loop and retry this slot.
      }
    }
  }

  return null;
}

module.exports = {
  HOOK_LOCK_SUBDIR,
  HOOK_LOCK_MAX_INFLIGHT,
  HOOK_LOCK_STALE_MS,
  acquireHookSlot,
  pidIsLive,
  ownerLiveness,
  unlinkIfSameIdentity,
};
