#!/usr/bin/env node
/**
 * GitNexus Cursor postToolUse Hook
 *
 * Receives a JSON event on stdin describing a finished tool call, derives a
 * search pattern (Grep query or Read file basename), runs
 * `gitnexus augment <pattern>`, and emits the enriched context back as
 * `{ additional_context: "..." }` so the agent sees it alongside the
 * tool result.
 *
 * Shell command parsing is intentionally unsupported. Arbitrary shell
 * grammars (value-bearing flags, pattern-file modes, compound command
 * boundaries, Windows `.exe` names) failed repeatedly; the hook matcher
 * is exactly `Read|Grep`.
 *
 * Cross-platform (no bash, no jq -- runs on Windows, Linux, and macOS).
 *
 * Cursor 2.4+ generic hooks: https://cursor.com/docs/agent/hooks
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { acquireHookSlot } = require('./hook-lock.cjs');
const { pathsEqual, pathContains } = require('./path-identity.cjs');
const { discoverGitNexusCli, npmGlobalNodeModules } = require('./gitnexus-cli-discovery.cjs');
const {
  createDeadline,
  spawnWithDeadline,
  CURSOR_HOOK_TIMEOUT_MS,
  HOOK_INTERNAL_BUDGET_MS,
  HOOK_TIMEOUT_SAFETY_MARGIN_MS,
} = require('./hook-deadline.cjs');

function readInput() {
  try {
    const data = fs.readFileSync(0, 'utf-8').replace(/^\uFEFF/, '');
    return JSON.parse(data);
  } catch {
    return {};
  }
}

function isGlobalRegistryDir(candidate) {
  if (
    fs.existsSync(path.join(candidate, 'gitnexus.json')) ||
    fs.existsSync(path.join(candidate, 'meta.json'))
  ) {
    return false;
  }
  return (
    fs.existsSync(path.join(candidate, 'registry.json')) ||
    fs.existsSync(path.join(candidate, 'repos'))
  );
}

function gitCommand(cwd, args, deadline, spawnSyncFn = spawnSync) {
  const result = spawnWithDeadline(deadline, spawnSyncFn, 'git', args, {
    encoding: 'utf-8',
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
    timeout: deadline ? undefined : 2000,
  });
  if (!result || result.skipped || result.error || result.status !== 0) return null;
  return result.stdout == null ? '' : String(result.stdout);
}

function gitStdout(cwd, args, deadline, spawnSyncFn) {
  const out = gitCommand(cwd, args, deadline, spawnSyncFn);
  if (out == null) return null;
  const trimmed = out.trim();
  return trimmed || null;
}

function isReviewedWorktreeDirty(cwd, deadline, spawnSyncFn) {
  const out = gitCommand(cwd, ['status', '--porcelain'], deadline, spawnSyncFn);
  if (out == null) return true;
  return out.trim().length > 0;
}

function readGitNexusMetaFile(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { ok: false };
      }
      return { ok: true, value: parsed };
    } catch {
      return { ok: false };
    }
  } catch (err) {
    if (err && (err.code === 'ENOENT' || err.code === 'ENOTDIR')) {
      return { missing: true };
    }
    return { ok: false };
  }
}

function loadGitNexusMeta(gitNexusDir) {
  const primary = readGitNexusMetaFile(path.join(gitNexusDir, 'gitnexus.json'));
  if (primary.ok) return primary.value;
  if (!primary.missing) return null;
  const legacy = readGitNexusMetaFile(path.join(gitNexusDir, 'meta.json'));
  if (legacy.ok) return legacy.value;
  return null;
}

function indexedCommitIdentity(meta) {
  if (!meta || typeof meta.lastCommit !== 'string') return null;
  const commit = meta.lastCommit.trim();
  return commit || null;
}

function canonicalIndexMatchesReviewedWorktree(gitNexusDir, workTreeRoot, deadline, spawnSyncFn) {
  const indexed = indexedCommitIdentity(loadGitNexusMeta(gitNexusDir));
  if (!indexed) return false;
  const head = gitStdout(workTreeRoot, ['rev-parse', 'HEAD'], deadline, spawnSyncFn);
  if (!head || indexed !== head) return false;
  if (isReviewedWorktreeDirty(workTreeRoot, deadline, spawnSyncFn)) return false;
  return true;
}

function findWorkingTreeRoot(cwd, deadline, spawnSyncFn) {
  const toplevel = gitStdout(cwd, ['rev-parse', '--show-toplevel'], deadline, spawnSyncFn);
  return toplevel ? path.resolve(toplevel) : null;
}

function findCanonicalRepoRoot(cwd, deadline, spawnSyncFn) {
  const commonDir = gitStdout(
    cwd,
    ['rev-parse', '--path-format=absolute', '--git-common-dir'],
    deadline,
    spawnSyncFn,
  );
  if (!commonDir) return null;
  const resolved = path.resolve(commonDir.replace(/[/\\]+$/, ''));
  // Worktrees share the main repo's `.git`. Submodules use `.git/modules/<name>`,
  // which must not be treated as another repository root to walk from.
  if (path.basename(resolved) !== '.git') return null;
  return path.dirname(resolved);
}

function walkForGitNexusDir(startDir, stopDir) {
  const stop = path.resolve(stopDir);
  let dir = path.resolve(startDir);
  for (let i = 0; i < 64; i++) {
    if (pathContains(stop, dir)) {
      const candidate = path.join(dir, '.gitnexus');
      if (fs.existsSync(candidate) && !isGlobalRegistryDir(candidate)) {
        return candidate;
      }
    }
    if (pathsEqual(dir, stop)) break;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function findGitNexusDir(startDir, deadline, spawnSyncFn) {
  const cwd = path.resolve(startDir || process.cwd());
  const workTreeRoot = findWorkingTreeRoot(cwd, deadline, spawnSyncFn);
  if (!workTreeRoot) return null;
  const fromWorkTree = walkForGitNexusDir(cwd, workTreeRoot);
  if (fromWorkTree) return fromWorkTree;
  const canonicalRoot = findCanonicalRepoRoot(cwd, deadline, spawnSyncFn);
  if (canonicalRoot && !pathsEqual(path.resolve(canonicalRoot), workTreeRoot)) {
    const fromCanonical = walkForGitNexusDir(canonicalRoot, canonicalRoot);
    if (fromCanonical && canonicalIndexMatchesReviewedWorktree(fromCanonical, workTreeRoot, deadline, spawnSyncFn)) {
      return fromCanonical;
    }
  }
  return null;
}

/**
 * Extract a search pattern from the tool input. Cursor 2.4 docs at
 * https://cursor.com/docs/agent/hooks list the tool *matchers* but do not
 * formally specify the per-tool tool_input field names, so we probe a
 * generous set of MCP-style aliases. As a last-resort fallback for Grep
 * (the highest-frequency search path) we also accept the longest plausible
 * string value in tool_input. Set GITNEXUS_DEBUG=1 to log the raw payload
 * to stderr if Cursor changes the contract and aliases stop matching.
 *
 * Shell is not a supported matcher and is never parsed here.
 */
function pickLongestStringValue(obj) {
  let best = null;
  if (!obj || typeof obj !== 'object') return null;
  for (const v of Object.values(obj)) {
    if (typeof v === 'string' && v.length >= 3 && (!best || v.length > best.length)) {
      best = v;
    }
  }
  return best;
}

function extractPattern(toolName, toolInput) {
  const t = (toolName || '').toLowerCase();

  if (t === 'grep') {
    const aliases = [
      toolInput.query,
      toolInput.pattern,
      toolInput.regex,
      toolInput.q,
      toolInput.search,
      toolInput.searchQuery,
    ];
    let seenUnusableAlias = false;
    for (const a of aliases) {
      if (typeof a !== 'string') continue;
      if (a.length >= 3) return a;
      seenUnusableAlias = true;
    }
    // A present but unusable pattern alias occupies the pattern slot.
    // Do not fall through to non-pattern tool_input fields (paths, globs).
    if (seenUnusableAlias) return null;
    // Last resort: scan tool_input for any reasonable-looking string value.
    return pickLongestStringValue(toolInput);
  }

  if (t === 'read') {
    const filePath =
      toolInput.target_file ||
      toolInput.file_path ||
      toolInput.filePath ||
      toolInput.path ||
      toolInput.file ||
      '';
    if (!filePath) return null;
    const base = path.basename(String(filePath), path.extname(String(filePath)));
    const cleaned = base.replace(/[^a-zA-Z0-9_]/g, '');
    return cleaned.length >= 3 ? cleaned : null;
  }

  return null;
}

function resolveCliPath(options = {}) {
  const found = discoverGitNexusCli(options);
  return found ? found.path : '';
}

function normalizeInvocation(invocation) {
  if (!invocation) return null;
  if (typeof invocation === 'string') {
    const trimmed = invocation.trim();
    if (!trimmed) return null;
    if (/\.(cmd|bat)$/i.test(trimmed)) return null;
    if (/\.c?js$/i.test(trimmed)) {
      return {
        kind: 'js',
        command: process.execPath,
        argsPrefix: [trimmed],
        path: trimmed,
        source: 'string',
      };
    }
    return {
      kind: 'native',
      command: trimmed,
      argsPrefix: [],
      path: trimmed,
      source: 'string',
    };
  }
  if (typeof invocation !== 'object') return null;
  if (!invocation.command) return null;
  if (/\.(cmd|bat)$/i.test(String(invocation.command))) return null;
  return invocation;
}

function runGitNexusCli(invocation, args, cwd, timeout, spawnSyncFn = spawnSync) {
  const inv = normalizeInvocation(invocation);
  if (!inv || !inv.command) {
    const error = new Error('gitnexus CLI invocation not found');
    error.code = 'ENOENT';
    return { error, status: 1, stdout: '', stderr: '' };
  }
  if (timeout !== undefined && timeout <= 0) {
    const error = new Error('hook deadline exhausted');
    error.code = 'ETIMEDOUT';
    return { error, status: null, stdout: '', stderr: '', skipped: true };
  }

  const argv = [...(Array.isArray(inv.argsPrefix) ? inv.argsPrefix : []), ...args];
  return spawnSyncFn(inv.command, argv, {
    encoding: 'utf-8',
    timeout,
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
    shell: false,
  });
}

function emitContext(result) {
  const text = result && String(result).trim();
  if (!text) return false;
  console.log(JSON.stringify({ additional_context: text }));
  return true;
}

function executeHook(input, deps = {}) {
  const spawnSyncFn = deps.spawnSync || spawnSync;
  const nowFn = deps.nowFn || Date.now;
  const env = deps.env || process.env;
  const deadline = deps.deadline || createDeadline({ nowFn, budgetMs: HOOK_INTERNAL_BUDGET_MS });
  const discoverOptions = deps.discoverOptions || {};

  if (env.GITNEXUS_DEBUG) {
    try {
      process.stderr.write(`GitNexus Cursor hook stdin: ${JSON.stringify(input).slice(0, 500)}\n`);
    } catch {
      /* never let debug logging break the hook */
    }
  }

  const cwd = input.cwd || process.cwd();
  if (!path.isAbsolute(cwd)) return { status: 'skip' };
  if (deadline.expired()) return { status: 'timeout' };

  const gitNexusDir = findGitNexusDir(cwd, deadline, spawnSyncFn);
  if (deadline.expired()) return { status: 'timeout' };
  if (!gitNexusDir) return { status: 'skip' };

  const toolName = input.tool_name || '';
  const toolInput = input.tool_input || {};
  const pattern = extractPattern(toolName, toolInput);
  if (!pattern || pattern.length < 3) return { status: 'skip' };

  const release = acquireHookSlot(gitNexusDir);
  if (!release) {
    if (env.GITNEXUS_DEBUG) {
      process.stderr.write('[GitNexus] augment skipped: hook slots saturated\n');
    }
    return { status: 'saturated' };
  }

  try {
    if (!deadline.canSpawn()) return { status: 'timeout' };
    const discovered = discoverGitNexusCli({
      env,
      deadline,
      cwd,
      spawnSync: spawnSyncFn,
      ...discoverOptions,
    });
    if (env.GITNEXUS_DEBUG) {
      process.stderr.write(`GitNexus Cursor hook cliPath: ${(discovered && discovered.path) || '(empty)'}\n`);
    }
    if (!deadline.canSpawn()) return { status: 'timeout' };
    if (!discovered) return { status: 'skip' };

    const child = runGitNexusCli(
      discovered,
      ['augment', '--', pattern],
      cwd,
      deadline.spawnTimeoutMs(),
      spawnSyncFn,
    );
    if (env.GITNEXUS_DEBUG && child.error) {
      process.stderr.write(
        `GitNexus Cursor hook spawn error: ${child.error.code || ''} ${child.error.message || ''}\n`,
      );
    }
    if (deadline.expired() || child.skipped || child.error || child.status !== 0) {
      return { status: deadline.expired() || child.skipped ? 'timeout' : 'fail-open' };
    }
    const result = child.stdout || child.stderr || '';
    if (deadline.expired()) return { status: 'timeout' };
    if (emitContext(result)) return { status: 'ok' };
    return { status: 'fail-open' };
  } finally {
    release();
  }
}

function main() {
  try {
    const input = readInput();
    executeHook(input);
  } catch (err) {
    if (process.env.GITNEXUS_DEBUG) {
      console.error('GitNexus Cursor hook error:', (err.message || '').slice(0, 200));
    }
  }
}

if (require.main === module) {
  main();
}

module.exports = {
  resolveCliPath,
  runGitNexusCli,
  normalizeInvocation,
  extractPattern,
  findGitNexusDir,
  findCanonicalRepoRoot,
  walkForGitNexusDir,
  loadGitNexusMeta,
  canonicalIndexMatchesReviewedWorktree,
  npmGlobalNodeModules,
  gitCommand,
  executeHook,
  createDeadline,
  CURSOR_HOOK_TIMEOUT_MS,
  HOOK_INTERNAL_BUDGET_MS,
  HOOK_TIMEOUT_SAFETY_MARGIN_MS,
};
