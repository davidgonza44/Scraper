'use strict';

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { spawnWithDeadline } = require('./hook-deadline.cjs');

const CLI_ENTRY = 'gitnexus/dist/cli/index.js';

function pathFor(platform) {
  return platform === 'win32' ? path.win32 : path.posix;
}

function fileExists(fsApi, filePath) {
  try {
    return Boolean(fsApi.existsSync(filePath));
  } catch {
    return false;
  }
}

function findOnPath(pathVar, platform, fsApi) {
  if (!pathVar) return '';
  const p = pathFor(platform);
  const delimiter = platform === 'win32' ? ';' : ':';
  const names = platform === 'win32' ? ['gitnexus.cmd', 'gitnexus.exe', 'gitnexus'] : ['gitnexus'];
  for (const dir of String(pathVar).split(delimiter)) {
    if (!dir) continue;
    for (const name of names) {
      const candidate = p.join(dir, name);
      if (fileExists(fsApi, candidate)) return candidate;
    }
  }
  return '';
}

function homebrewPrefixFromExecPath(execPath, platform) {
  const parts = String(execPath).split(/[/\\]/);
  const idx = parts.indexOf('Cellar');
  if (idx <= 0) return '';
  const prefixParts = parts.slice(0, idx);
  if (platform === 'win32') return prefixParts.join('\\');
  const prefix = prefixParts.join('/');
  return prefix || '/';
}

function layoutFallbackRoots({ execPath, platform, env, realpathSync }) {
  const p = pathFor(platform);
  const roots = [];
  const seen = new Set();
  const add = (root) => {
    if (!root || seen.has(root)) return;
    seen.add(root);
    roots.push(root);
  };

  const delim = platform === 'win32' ? ';' : ':';
  if (env && env.NODE_PATH) {
    for (const part of String(env.NODE_PATH).split(delim)) {
      if (part) add(part);
    }
  }

  if (platform === 'win32') {
    if (env && env.APPDATA) add(p.join(env.APPDATA, 'npm', 'node_modules'));
  } else {
    const home = (env && (env.HOME || env.USERPROFILE)) || '';
    if (home) {
      add(p.join(home, '.npm-global', 'lib', 'node_modules'));
      add(p.join(home, '.local', 'lib', 'node_modules'));
    }
    add('/usr/local/lib/node_modules');
    add('/usr/lib/node_modules');
  }

  const execDir = p.dirname(execPath);
  add(p.join(execDir, 'node_modules'));
  add(p.join(execDir, 'lib', 'node_modules'));
  if (p.basename(execDir) === 'bin') {
    add(p.join(p.dirname(execDir), 'lib', 'node_modules'));
  }

  let resolvedExec = execPath;
  try {
    if (typeof realpathSync === 'function') resolvedExec = realpathSync(execPath);
  } catch {
    resolvedExec = execPath;
  }
  for (const candidate of [resolvedExec, execPath]) {
    const brew = homebrewPrefixFromExecPath(candidate, platform);
    if (brew) add(p.join(brew, 'lib', 'node_modules'));
  }

  return roots;
}

function queryNpmRootGlobal(spawnSyncFn, deadline, cwd, env) {
  const result = spawnWithDeadline(deadline, spawnSyncFn, 'npm', ['root', '-g'], {
    encoding: 'utf-8',
    cwd,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });
  if (!result || result.skipped || result.error || result.status !== 0) return '';
  return String(result.stdout || '').trim();
}

function discoverGitNexusCli(options = {}) {
  const fsApi = options.fs || fs;
  const env = options.env || process.env;
  const platform = options.platform || process.platform;
  const execPath = options.execPath || process.execPath;
  const pathVar = options.pathVar !== undefined ? options.pathVar : env.PATH || env.Path || '';
  const deadline = options.deadline;
  const requireResolve = options.requireResolve || require.resolve;
  const spawnSyncFn = options.spawnSync || spawnSync;
  const realpathSync =
    options.realpathSync ||
    ((target) => (fsApi.realpathSync ? fsApi.realpathSync(target) : fs.realpathSync(target)));
  const cwd = options.cwd;
  const p = pathFor(platform);

  const override = env.GITNEXUS_CLI != null ? String(env.GITNEXUS_CLI).trim() : '';
  if (override) {
    if (fileExists(fsApi, override)) {
      return {
        kind: /\.c?js$/i.test(override) ? 'js' : 'bin',
        path: override,
        source: 'override',
      };
    }
  }

  const onPath = findOnPath(pathVar, platform, fsApi);
  if (onPath) {
    return { kind: 'bin', path: onPath, source: 'path' };
  }

  try {
    const resolved = requireResolve(CLI_ENTRY);
    if (resolved) return { kind: 'js', path: resolved, source: 'local' };
  } catch {
    /* not installed next to this hook */
  }

  let npmRoot = options.npmRootGlobal;
  if (npmRoot === undefined) {
    npmRoot = queryNpmRootGlobal(spawnSyncFn, deadline, cwd, env);
  }
  if (npmRoot) {
    const candidate = p.join(npmRoot, 'gitnexus', 'dist', 'cli', 'index.js');
    if (fileExists(fsApi, candidate)) {
      return { kind: 'js', path: candidate, source: 'npm-root' };
    }
  }

  for (const root of layoutFallbackRoots({ execPath, platform, env, realpathSync })) {
    const candidate = p.join(root, 'gitnexus', 'dist', 'cli', 'index.js');
    if (fileExists(fsApi, candidate)) {
      return { kind: 'js', path: candidate, source: 'layout' };
    }
    try {
      const resolved = requireResolve(CLI_ENTRY, { paths: [root] });
      if (resolved) return { kind: 'js', path: resolved, source: 'layout' };
    } catch {
      /* continue */
    }
  }

  return null;
}

function npmGlobalNodeModules(executable = process.execPath, platform = process.platform, env = process.env) {
  return layoutFallbackRoots({
    execPath: executable,
    platform,
    env: env || {},
    realpathSync: (target) => target,
  });
}

module.exports = {
  CLI_ENTRY,
  discoverGitNexusCli,
  npmGlobalNodeModules,
  layoutFallbackRoots,
  findOnPath,
  homebrewPrefixFromExecPath,
  queryNpmRootGlobal,
};
