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

function gitCommand(cwd, args) {
  try {
    const result = spawnSync('git', args, {
      encoding: 'utf-8',
      timeout: 2000,
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    if (result.error || result.status !== 0) return null;
    return result.stdout == null ? '' : String(result.stdout);
  } catch {
    return null;
  }
}

function gitStdout(cwd, args) {
  const out = gitCommand(cwd, args);
  if (out == null) return null;
  const trimmed = out.trim();
  return trimmed || null;
}

function isReviewedWorktreeDirty(cwd) {
  const out = gitCommand(cwd, ['status', '--porcelain']);
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

function canonicalIndexMatchesReviewedWorktree(gitNexusDir, workTreeRoot) {
  const indexed = indexedCommitIdentity(loadGitNexusMeta(gitNexusDir));
  if (!indexed) return false;
  const head = gitStdout(workTreeRoot, ['rev-parse', 'HEAD']);
  if (!head || indexed !== head) return false;
  if (isReviewedWorktreeDirty(workTreeRoot)) return false;
  return true;
}

function findWorkingTreeRoot(cwd) {
  const toplevel = gitStdout(cwd, ['rev-parse', '--show-toplevel']);
  return toplevel ? path.resolve(toplevel) : null;
}

function findCanonicalRepoRoot(cwd) {
  const commonDir = gitStdout(cwd, ['rev-parse', '--path-format=absolute', '--git-common-dir']);
  if (!commonDir) return null;
  const resolved = path.resolve(commonDir.replace(/[/\\]+$/, ''));
  // Worktrees share the main repo's `.git`. Submodules use `.git/modules/<name>`,
  // which must not be treated as another repository root to walk from.
  if (path.basename(resolved) !== '.git') return null;
  return path.dirname(resolved);
}

function walkForGitNexusDir(startDir, stopDir) {
  const stop = path.resolve(stopDir);
  const stopPrefix = stop.endsWith(path.sep) ? stop : stop + path.sep;
  let dir = path.resolve(startDir);
  for (let i = 0; i < 64; i++) {
    const inBounds = dir === stop || dir.startsWith(stopPrefix);
    if (inBounds) {
      const candidate = path.join(dir, '.gitnexus');
      if (fs.existsSync(candidate) && !isGlobalRegistryDir(candidate)) {
        return candidate;
      }
    }
    if (dir === stop) break;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function findGitNexusDir(startDir) {
  const cwd = path.resolve(startDir || process.cwd());
  const workTreeRoot = findWorkingTreeRoot(cwd);
  if (!workTreeRoot) return null;
  const fromWorkTree = walkForGitNexusDir(cwd, workTreeRoot);
  if (fromWorkTree) return fromWorkTree;
  const canonicalRoot = findCanonicalRepoRoot(cwd);
  if (canonicalRoot && path.resolve(canonicalRoot) !== workTreeRoot) {
    const fromCanonical = walkForGitNexusDir(canonicalRoot, canonicalRoot);
    if (fromCanonical && canonicalIndexMatchesReviewedWorktree(fromCanonical, workTreeRoot)) {
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

function npmGlobalNodeModules(
  executable = process.execPath,
  platform = process.platform,
  env = process.env,
) {
  const roots = [];
  if (env.NODE_PATH) {
    for (const part of env.NODE_PATH.split(path.delimiter)) {
      if (part) roots.push(part);
    }
  }
  if (platform === 'win32') {
    if (env.APPDATA) {
      roots.push(path.join(env.APPDATA, 'npm', 'node_modules'));
    }
  } else {
    const home = env.HOME || '';
    if (home) {
      roots.push(path.join(home, '.npm-global', 'lib', 'node_modules'));
      roots.push(path.join(home, '.local', 'lib', 'node_modules'));
    }
    roots.push('/usr/local/lib/node_modules');
    roots.push('/usr/lib/node_modules');
  }
  const execDir = path.dirname(executable);
  roots.push(path.join(execDir, 'node_modules'));
  roots.push(path.join(execDir, 'lib', 'node_modules'));
  if (platform !== 'win32' && path.basename(execDir) === 'bin') {
    roots.push(path.join(path.dirname(execDir), 'lib', 'node_modules'));
  }
  return roots;
}

function resolveCliPath() {
  const entry = 'gitnexus/dist/cli/index.js';
  try {
    return require.resolve(entry);
  } catch {
    /* not installed next to this hook */
  }
  for (const root of npmGlobalNodeModules()) {
    try {
      return require.resolve(entry, { paths: [root] });
    } catch {
      const candidate = path.join(root, 'gitnexus', 'dist', 'cli', 'index.js');
      try {
        if (fs.existsSync(candidate)) return candidate;
      } catch {
        /* ignore unreadable roots */
      }
    }
  }
  return '';
}

function runGitNexusCli(cliPath, args, cwd, timeout) {
  if (!cliPath) {
    const error = new Error('gitnexus CLI JS entrypoint not found');
    error.code = 'ENOENT';
    return { error, status: 1, stdout: '', stderr: '' };
  }

  return spawnSync(process.execPath, [cliPath, ...args], {
    encoding: 'utf-8',
    timeout,
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });
}

function main() {
  try {
    const input = readInput();
    if (process.env.GITNEXUS_DEBUG) {
      // Echo the payload so users can capture Cursor's actual contract when
      // diagnosing why augmentation isn't firing. Stderr only -- stdout is
      // reserved for the JSON response Cursor consumes.
      try {
        process.stderr.write(
          `GitNexus Cursor hook stdin: ${JSON.stringify(input).slice(0, 500)}\n`,
        );
      } catch {
        /* never let debug logging break the hook */
      }
    }
    const cwd = input.cwd || process.cwd();
    if (!path.isAbsolute(cwd)) return;
    const gitNexusDir = findGitNexusDir(cwd);
    if (!gitNexusDir) return;

    const toolName = input.tool_name || '';
    const toolInput = input.tool_input || {};

    const pattern = extractPattern(toolName, toolInput);
    if (!pattern || pattern.length < 3) return;

    const release = acquireHookSlot(gitNexusDir);
    if (!release) {
      // Normal skip path: all per-repo hook slots are held by concurrent
      // sessions. Stays silent by default; surfaced only under the cursor
      // hook's own GITNEXUS_DEBUG (truthy) convention. NOTE: unlike the
      // claude/plugin/antigravity adapters this integration does not install
      // hook-db-lock-probe.cjs, so its augment child is not guard-wrapped
      // yet -- tracked on the #2163 follow-up list ("cursor probe").
      if (process.env.GITNEXUS_DEBUG) {
        process.stderr.write('[GitNexus] augment skipped: hook slots saturated\n');
      }
      return;
    }

    const cliPath = resolveCliPath();
    if (process.env.GITNEXUS_DEBUG) {
      process.stderr.write(`GitNexus Cursor hook cliPath: ${cliPath || '(empty)'}\n`);
    }
    let result = '';
    try {
      const child = runGitNexusCli(cliPath, ['augment', '--', pattern], cwd, 7000);
      if (process.env.GITNEXUS_DEBUG && child.error) {
        process.stderr.write(
          `GitNexus Cursor hook spawn error: ${child.error.code || ''} ${child.error.message || ''}\n`,
        );
      }
      if (!child.error && child.status === 0) {
        result = child.stdout || child.stderr || '';
      }
    } catch {
      /* graceful failure */
    } finally {
      release();
    }

    if (result && result.trim()) {
      console.log(JSON.stringify({ additional_context: result.trim() }));
    }
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
  extractPattern,
  findGitNexusDir,
  findCanonicalRepoRoot,
  walkForGitNexusDir,
  loadGitNexusMeta,
  canonicalIndexMatchesReviewedWorktree,
  npmGlobalNodeModules,
};
