'use strict';

const CURSOR_HOOK_TIMEOUT_MS = 10_000;
const HOOK_TIMEOUT_SAFETY_MARGIN_MS = 500;
const HOOK_INTERNAL_BUDGET_MS = CURSOR_HOOK_TIMEOUT_MS - HOOK_TIMEOUT_SAFETY_MARGIN_MS;

function createDeadline(options = {}) {
  const nowFn = options.nowFn || Date.now;
  const budgetMs = options.budgetMs != null ? options.budgetMs : HOOK_INTERNAL_BUDGET_MS;
  const startedAt = options.startedAt != null ? options.startedAt : nowFn();
  return {
    budgetMs,
    startedAt,
    nowFn,
    remainingMs() {
      const rem = budgetMs - (nowFn() - startedAt);
      return rem > 0 ? rem : 0;
    },
    expired() {
      return this.remainingMs() <= 0;
    },
    canSpawn() {
      return this.remainingMs() > 0;
    },
    spawnTimeoutMs() {
      return this.remainingMs();
    },
  };
}

function spawnWithDeadline(deadline, spawnSyncFn, command, args, options = {}) {
  if (deadline) {
    if (!deadline.canSpawn() || deadline.spawnTimeoutMs() <= 0) {
      const error = new Error('hook deadline exhausted');
      error.code = 'ETIMEDOUT';
      return { error, status: null, stdout: '', stderr: '', skipped: true };
    }
  }
  const timeout = deadline ? deadline.spawnTimeoutMs() : options.timeout;
  // Node treats timeout: 0 as "no timeout". Never pass 0.
  if (timeout !== undefined && timeout <= 0) {
    const error = new Error('hook deadline exhausted');
    error.code = 'ETIMEDOUT';
    return { error, status: null, stdout: '', stderr: '', skipped: true };
  }
  const opts = { ...options };
  if (timeout !== undefined) opts.timeout = timeout;
  return spawnSyncFn(command, args, opts);
}

module.exports = {
  CURSOR_HOOK_TIMEOUT_MS,
  HOOK_TIMEOUT_SAFETY_MARGIN_MS,
  HOOK_INTERNAL_BUDGET_MS,
  createDeadline,
  spawnWithDeadline,
};
