'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const discovery = require('./gitnexus-cli-discovery.cjs');

function memFs(files) {
  const set = new Set(files.map((file) => String(file)));
  return {
    existsSync(filePath) {
      return set.has(String(filePath));
    },
    realpathSync(filePath) {
      return String(filePath);
    },
  };
}

test('explicit GITNEXUS_CLI override wins when the file exists', () => {
  const override = '/opt/custom/gitnexus/dist/cli/index.js';
  const found = discovery.discoverGitNexusCli({
    env: { GITNEXUS_CLI: override, PATH: '/usr/bin' },
    fs: memFs([override, '/usr/bin/gitnexus']),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath: '/usr/bin/node',
    platform: 'linux',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: '/usr/bin/node',
    argsPrefix: [override],
    path: override,
    source: 'override',
  });
});

test('PATH executable is discovered without downloading', () => {
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/home/test/.nvm/versions/node/v22.22.2/bin:/usr/bin' },
    pathVar: '/home/test/.nvm/versions/node/v22.22.2/bin:/usr/bin',
    fs: memFs(['/home/test/.nvm/versions/node/v22.22.2/bin/gitnexus']),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath: '/home/test/.nvm/versions/node/v22.22.2/bin/node',
    platform: 'linux',
  });
  assert.deepEqual(found, {
    kind: 'native',
    command: '/home/test/.nvm/versions/node/v22.22.2/bin/gitnexus',
    argsPrefix: [],
    path: '/home/test/.nvm/versions/node/v22.22.2/bin/gitnexus',
    source: 'path',
  });
});

test('local project installation is used when PATH has no gitnexus', () => {
  const local = '/workspace/node_modules/gitnexus/dist/cli/index.js';
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/usr/bin' },
    pathVar: '/usr/bin',
    fs: memFs([]),
    requireResolve(entry) {
      if (entry === discovery.CLI_ENTRY) return local;
      throw new Error('missing');
    },
    npmRootGlobal: '',
    execPath: '/usr/bin/node',
    platform: 'linux',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: '/usr/bin/node',
    argsPrefix: [local],
    path: local,
    source: 'local',
  });
});

test('npm root -g is queried without installing anything', () => {
  const npmRoot = '/usr/lib/node_modules';
  const cli = path.posix.join(npmRoot, 'gitnexus', 'dist', 'cli', 'index.js');
  const commands = [];
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/usr/bin' },
    pathVar: '/usr/bin',
    fs: memFs([cli]),
    requireResolve() {
      throw new Error('not local');
    },
    spawnSync(cmd, args) {
      commands.push([cmd, ...args]);
      return { status: 0, stdout: `${npmRoot}\n`, stderr: '' };
    },
    execPath: '/usr/bin/node',
    platform: 'linux',
  });
  assert.deepEqual(commands, [['npm', 'root', '-g']]);
  assert.deepEqual(found, {
    kind: 'js',
    command: '/usr/bin/node',
    argsPrefix: [cli],
    path: cli,
    source: 'npm-root',
  });
});

test('NVM layout fallback resolves the versioned node_modules root', () => {
  const execPath = '/home/test/.nvm/versions/node/v25.9.0/bin/node';
  const cli = '/home/test/.nvm/versions/node/v25.9.0/lib/node_modules/gitnexus/dist/cli/index.js';
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/usr/bin' },
    pathVar: '/usr/bin',
    fs: memFs([cli]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath,
    platform: 'linux',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: execPath,
    argsPrefix: [cli],
    path: cli,
    source: 'layout',
  });
});

test('Apple Silicon Homebrew Cellar uses the prefix global modules directory', () => {
  const execPath = '/opt/homebrew/Cellar/node/23.11.0/bin/node';
  const cli = '/opt/homebrew/lib/node_modules/gitnexus/dist/cli/index.js';
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/usr/bin' },
    pathVar: '/usr/bin',
    fs: memFs([cli]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath,
    platform: 'darwin',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: execPath,
    argsPrefix: [cli],
    path: cli,
    source: 'layout',
  });
  assert.ok(
    discovery
      .npmGlobalNodeModules(execPath, 'darwin', {})
      .includes('/opt/homebrew/lib/node_modules'),
  );
});

test('Intel Homebrew Cellar uses /usr/local/lib/node_modules', () => {
  const execPath = '/usr/local/Cellar/node/22.14.0/bin/node';
  const cli = '/usr/local/lib/node_modules/gitnexus/dist/cli/index.js';
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/usr/bin' },
    pathVar: '/usr/bin',
    fs: memFs([cli]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath,
    platform: 'darwin',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: execPath,
    argsPrefix: [cli],
    path: cli,
    source: 'layout',
  });
});

test('Windows global npm APPDATA layout is discovered', () => {
  const execPath = 'C:\\Program Files\\nodejs\\node.exe';
  const cli = 'C:\\Users\\test\\AppData\\Roaming\\npm\\node_modules\\gitnexus\\dist\\cli\\index.js';
  const found = discovery.discoverGitNexusCli({
    env: { APPDATA: 'C:\\Users\\test\\AppData\\Roaming', PATH: 'C:\\Windows\\System32' },
    pathVar: 'C:\\Windows\\System32',
    fs: memFs([cli]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath,
    platform: 'win32',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: execPath,
    argsPrefix: [cli],
    path: cli,
    source: 'layout',
  });
});

test('standard Linux global npm layout is discovered', () => {
  const cli = '/usr/lib/node_modules/gitnexus/dist/cli/index.js';
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/bin' },
    pathVar: '/bin',
    fs: memFs([cli]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath: '/usr/bin/node',
    platform: 'linux',
  });
  assert.deepEqual(found, {
    kind: 'js',
    command: '/usr/bin/node',
    argsPrefix: [cli],
    path: cli,
    source: 'layout',
  });
});

test('missing GitNexus is a clean fail-open result', () => {
  const found = discovery.discoverGitNexusCli({
    env: { PATH: '/empty' },
    pathVar: '/empty',
    fs: memFs([]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath: '/usr/bin/node',
    platform: 'linux',
  });
  assert.equal(found, null);
});

test('Windows PATH gitnexus.cmd resolves to the JavaScript CLI invocation, not the shim', () => {
  const execPath = 'C:\\Program Files\\nodejs\\node.exe';
  const cmd = 'C:\\Users\\test\\AppData\\Roaming\\npm\\gitnexus.cmd';
  const js = 'C:\\Users\\test\\AppData\\Roaming\\npm\\node_modules\\gitnexus\\dist\\cli\\index.js';
  const found = discovery.discoverGitNexusCli({
    env: { APPDATA: 'C:\\Users\\test\\AppData\\Roaming', PATH: 'C:\\Users\\test\\AppData\\Roaming\\npm' },
    pathVar: 'C:\\Users\\test\\AppData\\Roaming\\npm',
    fs: memFs([cmd, js]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath,
    platform: 'win32',
  });
  assert.ok(found);
  assert.notEqual(found.command, cmd);
  assert.notEqual(found.path, cmd);
  assert.equal(found.kind, 'js');
  assert.equal(found.command, execPath);
  assert.deepEqual(found.argsPrefix, [js]);
  assert.equal(found.path, js);
  assert.doesNotMatch(found.command, /\.cmd$/i);
});

test('Windows gitnexus.cmd with spaces still uses process.execPath and a JS entrypoint', () => {
  const execPath = 'C:\\Program Files\\nodejs\\node.exe';
  const cmd = 'C:\\Program Files\\nodejs\\gitnexus.cmd';
  const js = 'C:\\Program Files\\nodejs\\node_modules\\gitnexus\\dist\\cli\\index.js';
  const found = discovery.discoverGitNexusCli({
    env: { PATH: 'C:\\Program Files\\nodejs' },
    pathVar: 'C:\\Program Files\\nodejs',
    fs: memFs([cmd, js]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath,
    platform: 'win32',
  });
  assert.equal(found.kind, 'js');
  assert.equal(found.command, execPath);
  assert.deepEqual(found.argsPrefix, [js]);
  assert.match(found.path, /Program Files/);
});

test('unprovable Windows .cmd shim fails open instead of becoming a spawn target', () => {
  const cmd = 'C:\\Users\\test\\AppData\\Roaming\\npm\\gitnexus.cmd';
  const found = discovery.discoverGitNexusCli({
    env: { APPDATA: 'C:\\Users\\test\\AppData\\Roaming', PATH: 'C:\\Users\\test\\AppData\\Roaming\\npm' },
    pathVar: 'C:\\Users\\test\\AppData\\Roaming\\npm',
    fs: memFs([cmd]),
    requireResolve() {
      throw new Error('not local');
    },
    npmRootGlobal: '',
    execPath: 'C:\\Program Files\\nodejs\\node.exe',
    platform: 'win32',
  });
  assert.equal(found, null);
});

test('discovery never uses npx or npm install', () => {
  const source = require('node:fs').readFileSync(require('node:path').join(__dirname, 'gitnexus-cli-discovery.cjs'), 'utf8');
  assert.doesNotMatch(source, /\bnpx\b/);
  assert.doesNotMatch(source, /npm install/);
  assert.doesNotMatch(source, /npm exec/);
});
