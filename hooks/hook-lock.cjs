const fs = require('fs');
const path = require('path');

const HOOK_LOCK_SUBDIR = '.hook-locks';
const HOOK_LOCK_MAX_INFLIGHT = 3;
const HOOK_LOCK_STALE_MS = 30000;

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
        let mtimeMs = Date.now();
        try {
          observedStat = fs.fstatSync(fd);
          mtimeMs = observedStat.mtimeMs;
          const buf = Buffer.alloc(32);
          const n = fs.readSync(fd, buf, 0, 32, 0);
          const ownerStr = buf.slice(0, n).toString('utf-8').trim();
          if (ownerStr === '') {
            // Owner created the file but hasn't written its PID yet. The
            // wx open+write window is microseconds; give it the benefit
            // of the doubt and treat as live.
            isLive = true;
          } else {
            const owner = Number.parseInt(ownerStr, 10);
            if (Number.isFinite(owner) && owner > 0) {
              try {
                process.kill(owner, 0);
                isLive = true;
              } catch (e) {
                // ESRCH = process gone -> treat as dead. EPERM = process exists
                // but owned by another user (cross-user lock dir) -> still alive,
                // keep the slot. Anything else: be conservative, assume alive.
                if (e && e.code === 'ESRCH') {
                  isLive = false;
                } else {
                  isLive = true;
                }
              }
            }
          }
        } catch {
          /* unreadable -- treat as dead */
        }
        // For slots younger than HOOK_LOCK_STALE_MS, PID-liveness wins --
        // a slow-but-alive hook is never wrongly evicted. For older slots,
        // age is the final arbiter as a defense against PID reuse on long-
        // abandoned slots. 30s >> the 7s augment timeout, so a healthy run
        // never crosses this threshold.
        if (isLive && Date.now() - mtimeMs > HOOK_LOCK_STALE_MS) {
          isLive = false;
        }
        if (isLive) {
          try { fs.closeSync(fd); } catch { /* already closed */ }
          break; // Try the next slot.
        }
        // Serialize stale cleanup with a sidecar created via wx. After owning
        // the claim, compare file identity to the still-open instance we
        // inspected. A contender that replaced it before the claim therefore
        // cannot have its new live lock removed.
        const claimPath = `${slotPath}.reclaim`;
        const claimToken = `${myPidStr}-${Date.now()}-${Math.random()}`;
        try {
          fs.writeFileSync(claimPath, claimToken, { flag: 'wx' });
        } catch {
          try { fs.closeSync(fd); } catch { /* already closed */ }
          break;
        }
        try {
          const currentStat = fs.statSync(slotPath);
          if (
            observedStat &&
            currentStat.dev === observedStat.dev &&
            currentStat.ino === observedStat.ino
          ) {
            fs.unlinkSync(slotPath);
          }
        } catch {
          /* stale instance already removed */
        } finally {
          try { fs.closeSync(fd); } catch { /* already closed */ }
          try {
            if (fs.readFileSync(claimPath, 'utf8') === claimToken) fs.unlinkSync(claimPath);
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
};
