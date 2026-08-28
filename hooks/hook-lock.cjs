'use strict';

/**
 * Cross-process hook concurrency cap.
 *
 * Admission is a counting semaphore of HOOK_LOCK_MAX_INFLIGHT implemented
 * with Node's bundled SQLite (`node:sqlite` DatabaseSync) and SQLite's
 * writer lock.
 *
 * Linearization point:
 *   The COMMIT of an INSERT INTO owners that ran inside a BEGIN IMMEDIATE
 *   transaction. BEGIN IMMEDIATE acquires SQLite's RESERVED/PENDING/EXCLUSIVE
 *   writer lock, so at most one process can be in the admission critical
 *   section. A BEFORE INSERT trigger also aborts any INSERT that would make
 *   COUNT(*) exceed HOOK_LOCK_MAX_INFLIGHT, so the engine itself refuses a
 *   fourth owner even if application logic were wrong.
 *
 * Successful acquisition always goes through that one INSERT+COMMIT.
 * Occupancy is the committed row, not a filesystem snapshot, ranking, or
 * post-rename check. Release DELETEs only that row's nonce. Live rows are
 * never deleted by another process. Stale/dead rows are removed only inside
 * the same IMMEDIATE transaction that decides admission — never via a
 * reusable shared-path stat-then-unlink.
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const HOOK_LOCK_SUBDIR = '.hook-locks';
const HOOK_LOCK_MAX_INFLIGHT = 3;
const HOOK_LOCK_STALE_MS = 30000;
const OWNERS_DB_FILENAME = 'owners.sqlite';
const OWNED_CLAIM_RE = /^owned-\d+-[0-9a-f]+\.(lock|pending)$/i;

let DatabaseSyncCtor = undefined;

function loadDatabaseSync() {
  if (DatabaseSyncCtor !== undefined) return DatabaseSyncCtor;
  const emitWarning = process.emitWarning;
  process.emitWarning = function patchedEmitWarning(warning, type) {
    const msg = typeof warning === 'string' ? warning : (warning && warning.message) || '';
    const name = typeof type === 'string' ? type : (warning && warning.name) || '';
    if (/sqlite/i.test(msg) && (/experimental/i.test(msg) || name === 'ExperimentalWarning')) {
      return;
    }
    return emitWarning.apply(process, arguments);
  };
  try {
    const sqlite = require('node:sqlite');
    DatabaseSyncCtor = sqlite.DatabaseSync || null;
  } catch {
    DatabaseSyncCtor = null;
  } finally {
    process.emitWarning = emitWarning;
  }
  return DatabaseSyncCtor;
}

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
    isLive = true;
  } else {
    const owner = Number.parseInt(ownerStr, 10);
    if (Number.isFinite(owner) && owner > 0) {
      isLive = pidIsLive(owner);
    }
  }
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

function runBarrier(sync, stage, info) {
  if (sync && typeof sync.barrier === 'function') {
    sync.barrier(stage, info);
  }
}

function unlinkOwnedPath(ownedPath) {
  // Unlink only a unique owned-*.lock/.pending pathname. Never unlink a
  // reusable shared slot/.reclaim pathname based on an earlier observation.
  try {
    fs.unlinkSync(ownedPath);
  } catch {
    /* already removed or unreadable */
  }
}

function isOwnedClaimName(name) {
  return OWNED_CLAIM_RE.test(name);
}

function isProvenDeadOwnedClaim(filePath) {
  let fd;
  try {
    fd = fs.openSync(filePath, 'r');
  } catch {
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

function nonceFromSync(sync) {
  if (sync && typeof sync.nonce === 'string' && sync.nonce) return sync.nonce;
  if (sync && typeof sync.claimName === 'string' && sync.claimName) return sync.claimName;
  return `${process.pid}-${crypto.randomBytes(8).toString('hex')}`;
}

function ownersDbPath(lockDir) {
  return path.join(lockDir, OWNERS_DB_FILENAME);
}

function openOwnersDb(lockDir, options = {}) {
  const DatabaseSync = loadDatabaseSync();
  if (!DatabaseSync) return null;
  const readOnly = Boolean(options.readOnly);
  try {
    const dbPath = ownersDbPath(lockDir);
    const db = readOnly ? new DatabaseSync(dbPath, { readOnly: true }) : new DatabaseSync(dbPath);
    if (!readOnly) {
      db.exec(`
        PRAGMA busy_timeout = 5000;
        PRAGMA journal_mode = DELETE;
        CREATE TABLE IF NOT EXISTS owners (
          nonce TEXT PRIMARY KEY,
          pid INTEGER NOT NULL,
          created_ms INTEGER NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS owners_cap BEFORE INSERT ON owners
        BEGIN
          SELECT RAISE(ABORT, 'hook-lock-capacity')
          WHERE (SELECT COUNT(*) FROM owners) >= ${HOOK_LOCK_MAX_INFLIGHT};
        END;
      `);
    } else {
      db.exec('PRAGMA busy_timeout = 1000;');
    }
    return db;
  } catch {
    return null;
  }
}

function gcDeadOwnerRows(db, now = Date.now()) {
  const rows = db.prepare('SELECT nonce, pid, created_ms FROM owners').all();
  const del = db.prepare('DELETE FROM owners WHERE nonce = ?');
  for (const row of rows) {
    if (!ownerLiveness(String(row.pid), row.created_ms, now)) {
      del.run(row.nonce);
    }
  }
}

function countOwnerRows(db) {
  const row = db.prepare('SELECT COUNT(*) AS c FROM owners').get();
  return row && Number.isFinite(row.c) ? row.c : 0;
}

function releaseOwner(lockDir, nonce) {
  const db = openOwnersDb(lockDir);
  if (!db) return;
  try {
    db.exec('BEGIN IMMEDIATE');
    db.prepare('DELETE FROM owners WHERE nonce = ?').run(nonce);
    db.exec('COMMIT');
  } catch {
    try {
      db.exec('ROLLBACK');
    } catch {
      /* already rolled back or closed */
    }
  } finally {
    try {
      db.close();
    } catch {
      /* already closed */
    }
  }
}

function countLiveOwners(gitNexusDir) {
  const lockDir = path.join(gitNexusDir, HOOK_LOCK_SUBDIR);
  const dbPath = ownersDbPath(lockDir);
  if (!fs.existsSync(dbPath)) return 0;
  const db = openOwnersDb(lockDir, { readOnly: true });
  if (!db) return -1;
  try {
    const now = Date.now();
    const rows = db.prepare('SELECT pid, created_ms FROM owners').all();
    return rows.filter((row) => ownerLiveness(String(row.pid), row.created_ms, now)).length;
  } catch {
    return -1;
  } finally {
    try {
      db.close();
    } catch {
      /* already closed */
    }
  }
}

function acquireHookSlot(gitNexusDir, sync) {
  const lockDir = path.join(gitNexusDir, HOOK_LOCK_SUBDIR);
  try {
    fs.mkdirSync(lockDir, { recursive: true });
  } catch {
    return null;
  }

  runBarrier(sync, 'before-stale-gc', { lockDir });
  reclaimStaleOwnedClaims(lockDir);
  runBarrier(sync, 'after-stale-gc', { lockDir });

  const nonce = nonceFromSync(sync);
  runBarrier(sync, 'after-private-create', { lockDir, nonce });
  runBarrier(sync, 'before-admission', { lockDir, nonce });
  runBarrier(sync, 'before-promote', { lockDir, nonce });

  const db = openOwnersDb(lockDir);
  if (!db) return null;

  let admitted = false;
  let liveForBarrier = -1;
  try {
    // Linearization starts here: BEGIN IMMEDIATE is the mutex.
    db.exec('BEGIN IMMEDIATE');
    gcDeadOwnerRows(db);
    const count = countOwnerRows(db);
    liveForBarrier = count;
    if (count >= HOOK_LOCK_MAX_INFLIGHT) {
      db.exec('ROLLBACK');
    } else {
      db.prepare('INSERT INTO owners (nonce, pid, created_ms) VALUES (?, ?, ?)').run(
        nonce,
        process.pid,
        Date.now(),
      );
      db.exec('COMMIT');
      admitted = true;
      liveForBarrier = countOwnerRows(db);
    }
  } catch {
    try {
      db.exec('ROLLBACK');
    } catch {
      /* already rolled back */
    }
    admitted = false;
  }

  runBarrier(sync, 'after-admission', {
    lockDir,
    nonce,
    live: liveForBarrier,
    held: liveForBarrier,
    pending: 0,
    admitted,
  });
  runBarrier(sync, 'after-count-live', {
    lockDir,
    live: liveForBarrier,
    held: liveForBarrier,
    pending: 0,
  });

  try {
    db.close();
  } catch {
    /* already closed */
  }

  if (!admitted) return null;

  let released = false;
  const onExit = () => {
    release();
  };
  const release = () => {
    if (released) return;
    released = true;
    process.removeListener('exit', onExit);
    runBarrier(sync, 'before-private-unlink', { lockDir, nonce, reason: 'release' });
    releaseOwner(lockDir, nonce);
  };
  process.on('exit', onExit);
  return release;
}

module.exports = {
  HOOK_LOCK_SUBDIR,
  HOOK_LOCK_MAX_INFLIGHT,
  HOOK_LOCK_STALE_MS,
  OWNERS_DB_FILENAME,
  acquireHookSlot,
  pidIsLive,
  ownerLiveness,
  countLiveOwners,
  isOwnedClaimName,
  reclaimStaleOwnedClaims,
};
