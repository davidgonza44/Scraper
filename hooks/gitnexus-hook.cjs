#!/usr/bin/env node
/**
 * GitNexus Cursor postToolUse Hook
 *
 * Receives a JSON event on stdin describing a finished tool call, derives a
 * search pattern (Grep query, Read file basename, or rg/grep arg from a Shell
 * command), runs `gitnexus augment <pattern>`, and emits the enriched context
 * back as `{ additional_context: "..." }` so the agent sees it alongside the
 * tool result.
 *
 * Replaces the legacy beforeShellExecution / augment-shell.sh pipeline:
 *   - Cross-platform (no bash, no jq -- runs on Windows out of the box)
 *   - Covers Read and Grep, not just Shell rg/grep
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

function walkForGitNexusDir(startDir) {
  let dir = startDir;
  for (let i = 0; i < 5; i++) {
    const candidate = path.join(dir, '.gitnexus');
    if (fs.existsSync(candidate)) {
      if (!isGlobalRegistryDir(candidate)) return candidate;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function findCanonicalRepoRoot(cwd) {
  try {
    const result = spawnSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {
      encoding: 'utf-8',
      timeout: 2000,
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    if (result.error || result.status !== 0) return null;
    const commonDir = (result.stdout || '').trim();
    if (!commonDir || !path.isAbsolute(commonDir)) return null;
    return path.dirname(commonDir);
  } catch {
    return null;
  }
}

function findGitNexusDir(startDir) {
  const cwd = startDir || process.cwd();
  const fromCwd = walkForGitNexusDir(cwd);
  if (fromCwd) return fromCwd;
  const canonicalRoot = findCanonicalRepoRoot(cwd);
  if (canonicalRoot && canonicalRoot !== cwd) {
    return walkForGitNexusDir(canonicalRoot);
  }
  return null;
}

function parseRgGrepPattern(cmd) {
  const tokens = cmd.split(/\s+/);
  let foundCmd = false;
  let skipNext = false;
  const flagsWithValues = new Set([
    '-f',
    '-m',
    '-A',
    '-B',
    '-C',
    '-g',
    '--glob',
    '-t',
    '--type',
    '--include',
    '--exclude',
  ]);

  for (const token of tokens) {
    if (skipNext === 'pattern') {
      const pattern = token.replace(/['"]/g, '');
      return pattern.length >= 3 ? pattern : null;
    }
    if (skipNext) {
      skipNext = false;
      continue;
    }
    if (!foundCmd) {
      if (/\brg$|\bgrep$/.test(token)) foundCmd = true;
      continue;
    }
    if (token === '-e' || token === '--regexp') {
      skipNext = 'pattern';
      continue;
    }
    if (token.startsWith('--regexp=')) {
      const pattern = token.slice('--regexp='.length).replace(/['"]/g, '');
      return pattern.length >= 3 ? pattern : null;
    }
    if (token.startsWith('-e') && token.length > 2) {
      const pattern = token.slice(2).replace(/['"]/g, '');
      return pattern.length >= 3 ? pattern : null;
    }
    if (token.startsWith('-')) {
      if (flagsWithValues.has(token)) skipNext = true;
      continue;
    }
    const cleaned = token.replace(/['"]/g, '');
    return cleaned.length >= 3 ? cleaned : null;
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
    for (const a of aliases) {
      if (typeof a === 'string' && a.length >= 3) return a;
    }
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

  if (t === 'shell') {
    const cmd = toolInput.command || '';
    if (!/\brg\b|\bgrep\b/.test(cmd)) return null;
    // NOTE: parseRgGrepPattern uses split(/\s+/) and cannot handle shell
    // quoting. `rg "User Service" src/` returns "User" (the first token
    // after the rg/grep arg, with surrounding quotes stripped) -- the
    // multi-word pattern is intentionally not reconstructed since BM25 is
    // already token-tolerant. Quoted single tokens (`rg "validateUser"`)
    // work fine.
    return parseRgGrepPattern(cmd);
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
  npmGlobalNodeModules,
};
