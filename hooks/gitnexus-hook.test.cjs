const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const hook = require('./gitnexus-hook.cjs');

function tempDir(t, prefix) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function runGit(cwd, args) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  assert.equal(result.status, 0, `${args.join(' ')}\n${result.stderr || result.stdout}`);
  return result;
}

function initGitRepo(dir) {
  runGit(dir, ['init', '-q']);
  runGit(dir, ['config', 'user.email', 'hook@test.local']);
  runGit(dir, ['config', 'user.name', 'Hook Test']);
  runGit(dir, ['config', 'commit.gpgsign', 'false']);
}

function writeRepoIndex(dir, meta = {}) {
  const gitNexusDir = path.join(dir, '.gitnexus');
  fs.mkdirSync(gitNexusDir, { recursive: true });
  fs.writeFileSync(path.join(gitNexusDir, 'gitnexus.json'), `${JSON.stringify(meta)}\n`);
  return gitNexusDir;
}

function gitHead(dir) {
  return runGit(dir, ['rev-parse', 'HEAD']).stdout.trim();
}

function addLinkedWorktree(t, parent, prefix) {
  const worktree = tempDir(t, prefix);
  fs.rmSync(worktree, { recursive: true, force: true });
  runGit(parent, ['worktree', 'add', '--detach', worktree]);
  t.after(() => {
    spawnSync('git', ['worktree', 'remove', '--force', worktree], {
      cwd: parent,
      encoding: 'utf8',
    });
  });
  return worktree;
}

function runHook(payload, env = {}) {
  return spawnSync(process.execPath, [path.join(__dirname, 'gitnexus-hook.cjs')], {
    input: JSON.stringify(payload),
    encoding: 'utf8',
    env: { ...process.env, ...env },
    timeout: 8000,
  });
}

test('Unix executable prefixes contribute their global node_modules root', () => {
  for (const executable of [
    '/home/test/.nvm/versions/node/v25.9.0/bin/node',
    '/opt/node/bin/node',
  ]) {
    const expected = path.join(path.dirname(path.dirname(executable)), 'lib', 'node_modules');
    assert.ok(hook.npmGlobalNodeModules(executable, 'linux', {}).includes(expected));
  }
});

test('Windows APPDATA global root is preserved', () => {
  const roots = hook.npmGlobalNodeModules('C:\\node\\node.exe', 'win32', {
    APPDATA: 'C:\\Users\\test\\AppData\\Roaming',
  });
  assert.ok(roots.includes(path.win32.join('C:\\Users\\test\\AppData\\Roaming', 'npm', 'node_modules')));
});

test('Homebrew Cellar node prefixes resolve the prefix global node_modules root', () => {
  const apple = '/opt/homebrew/Cellar/node/23.11.0/bin/node';
  const intel = '/usr/local/Cellar/node/22.14.0/bin/node';
  const appleRoots = hook.npmGlobalNodeModules(apple, 'darwin', {});
  const intelRoots = hook.npmGlobalNodeModules(intel, 'darwin', {});
  assert.ok(appleRoots.includes('/opt/homebrew/lib/node_modules'));
  assert.ok(intelRoots.includes('/usr/local/lib/node_modules'));
});

test('sequential subprocess timeouts must fit inside the Cursor hook budget', () => {
  const hooksJson = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', '.cursor', 'hooks.json'), 'utf8'),
  );
  const outerMs = Number(hooksJson.hooks.postToolUse[0].timeout) * 1000;
  const source = fs.readFileSync(path.join(__dirname, 'gitnexus-hook.cjs'), 'utf8');
  const deadline = require('./hook-deadline.cjs');
  assert.match(source, /createDeadline/);
  assert.match(source, /spawnTimeoutMs|remainingMs/);
  assert.doesNotMatch(source, /timeout:\s*7000/);
  assert.equal(hooksJson.hooks.postToolUse[0].matcher, 'Read|Grep');
  assert.ok(deadline.HOOK_INTERNAL_BUDGET_MS + deadline.HOOK_TIMEOUT_SAFETY_MARGIN_MS <= outerMs);
  assert.ok(deadline.HOOK_TIMEOUT_SAFETY_MARGIN_MS >= 500);
});

test('project hook matcher is exactly Read|Grep', () => {
  const hooksJson = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', '.cursor', 'hooks.json'), 'utf8'),
  );
  assert.equal(hooksJson.hooks.postToolUse.length, 1);
  assert.equal(hooksJson.hooks.postToolUse[0].matcher, 'Read|Grep');
  assert.doesNotMatch(hooksJson.hooks.postToolUse[0].matcher, /Shell/);
});

test('structured Grep pattern aliases still work', () => {
  assert.equal(hook.extractPattern('Grep', { query: 'validateUser' }), 'validateUser');
  assert.equal(hook.extractPattern('Grep', { pattern: 'validateUser' }), 'validateUser');
  assert.equal(hook.extractPattern('Grep', { regex: 'validateUser' }), 'validateUser');
  assert.equal(hook.extractPattern('Grep', { q: 'validateUser' }), 'validateUser');
  assert.equal(hook.extractPattern('Grep', { search: 'validateUser' }), 'validateUser');
  assert.equal(hook.extractPattern('Grep', { searchQuery: 'validateUser' }), 'validateUser');
  assert.equal(
    hook.extractPattern('Grep', { query: 'id', pattern: 'validateUser' }),
    'validateUser',
  );
  assert.equal(hook.extractPattern('Grep', { pattern: 'identifier' }), 'identifier');
});

test('a present-but-unusable Grep pattern cannot fall through to a path', () => {
  assert.equal(hook.extractPattern('Grep', { pattern: 'id', path: 'src/' }), null);
  assert.equal(hook.extractPattern('Grep', { query: 'ok', path: 'file.py' }), null);
  assert.equal(hook.extractPattern('Grep', { regex: 'x', path: 'hooks/gitnexus-hook.cjs' }), null);
  assert.equal(hook.extractPattern('Grep', { q: '', glob: '**/*.py' }), null);
  assert.equal(hook.extractPattern('Grep', { pattern: 'identifier' }), 'identifier');
  assert.equal(
    hook.extractPattern('Grep', { query: 'id', pattern: 'validateUser' }),
    'validateUser',
  );
});

test('Read augmentation uses the cleaned file basename', () => {
  assert.equal(
    hook.extractPattern('Read', { target_file: 'src/validateUser.py' }),
    'validateUser',
  );
  assert.equal(hook.extractPattern('Read', { file_path: 'hooks/gitnexus-hook.cjs' }), 'gitnexushook');
  assert.equal(hook.extractPattern('Read', { filePath: 'src/fooBar.js' }), 'fooBar');
  assert.equal(hook.extractPattern('Read', { path: 'my_module.py' }), 'my_module');
  assert.equal(hook.extractPattern('Read', { file: 'ab.ts' }), null);
  assert.equal(hook.extractPattern('Read', {}), null);
});

test('Shell commands are not parsed, including compound boundaries and Windows executables', () => {
  const commands = [
    'rg validateUser src/',
    'grep validateUser file',
    'rg.exe validateUser src/',
    'grep.exe validateUser file',
    'C:\\Windows\\rg.exe validateUser src/',
    'rg primary src/ || grep -e secondary file',
    'rg primary src/ && grep secondary file',
    'rg primary src/ | grep secondary',
    'rg --files src/',
    'rg -f patterns.txt src/',
    'rg -e validateUser src/',
  ];
  for (const command of commands) {
    assert.equal(hook.extractPattern('Shell', { command }), null, command);
    assert.equal(hook.extractPattern('shell', { command }), null, command);
  }
});

test('hook implementation does not import or touch product application files', () => {
  const files = fs.readdirSync(__dirname).filter((name) => name.endsWith('.cjs') && !name.endsWith('.test.cjs'));
  for (const name of files) {
    const source = fs.readFileSync(path.join(__dirname, name), 'utf8');
    assert.doesNotMatch(source, /require\(['"]\.\.\/src/);
    assert.doesNotMatch(source, /from ['"]src\//);
    assert.doesNotMatch(source, /openspec/);
    assert.doesNotMatch(source, /docs\/architecture/);
  }
  const hookSource = fs.readFileSync(path.join(__dirname, 'gitnexus-hook.cjs'), 'utf8');
  assert.doesNotMatch(hookSource, /parseRgGrepPattern/);
  assert.doesNotMatch(hookSource, /detectSearchTool/);
  assert.doesNotMatch(hookSource, /t === 'shell'/);
  assert.doesNotMatch(hookSource, /function parseRgGrepPattern/);
});

test('missing GitNexus remains a local, fail-open result', () => {
  const result = hook.runGitNexusCli('', ['augment', '--', 'pattern'], process.cwd(), 100);
  assert.equal(result.error.code, 'ENOENT');
  assert.equal(result.stdout, '');
});

test('CASE A: cwd inside a repo finds that repo index', (t) => {
  const root = tempDir(t, 'gitnexus-a-');
  initGitRepo(root);
  const nested = path.join(root, 'src', 'app');
  fs.mkdirSync(nested, { recursive: true });
  const expected = writeRepoIndex(root);
  assert.equal(hook.findGitNexusDir(nested), expected);
  assert.equal(hook.findGitNexusDir(root), expected);
});

test('CASE B: nested repo index wins over parent index', (t) => {
  const parent = tempDir(t, 'gitnexus-b-parent-');
  initGitRepo(parent);
  const parentIndex = writeRepoIndex(parent);
  const nested = path.join(parent, 'nested');
  fs.mkdirSync(nested);
  initGitRepo(nested);
  const nestedIndex = writeRepoIndex(nested);
  assert.equal(hook.findGitNexusDir(nested), nestedIndex);
  assert.notEqual(hook.findGitNexusDir(nested), parentIndex);
});

test('CASE C: nested repo without an index must not use the parent index', (t) => {
  const parent = tempDir(t, 'gitnexus-c-parent-');
  initGitRepo(parent);
  const parentIndex = writeRepoIndex(parent);
  const nested = path.join(parent, 'nested');
  fs.mkdirSync(nested);
  initGitRepo(nested);
  assert.equal(hook.findGitNexusDir(nested), null);
  assert.notEqual(hook.findGitNexusDir(parent), null);
  assert.equal(hook.findGitNexusDir(parent), parentIndex);
});

test('Quality Gate runs both hook suites with the repository Node version', () => {
  const workflow = fs.readFileSync(
    path.join(__dirname, '..', '.github', 'workflows', 'quality-gate.yml'),
    'utf8',
  );
  assert.match(workflow, /uses:\s*actions\/setup-node@v4/);
  assert.match(workflow, /node-version-file:\s*"\.nvmrc"/);
  assert.match(workflow, /node --test hooks\/\*\.test\.cjs/);
  assert.doesNotMatch(workflow, /\bnpx\b/);
  assert.doesNotMatch(workflow, /npm install/);
});

test('non-git cwd does not inherit an ancestor .gitnexus', (t) => {
  const parent = tempDir(t, 'gitnexus-nongit-');
  writeRepoIndex(parent);
  const child = path.join(parent, 'plain');
  fs.mkdirSync(child);
  assert.equal(hook.findGitNexusDir(child), null);
});

test('submodule without an index must not use the superproject index', (t) => {
  const parent = tempDir(t, 'gitnexus-sub-parent-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const parentIndex = writeRepoIndex(parent);
  const subSrc = tempDir(t, 'gitnexus-sub-src-');
  initGitRepo(subSrc);
  fs.writeFileSync(path.join(subSrc, 'lib.txt'), 'lib\n');
  runGit(subSrc, ['add', 'lib.txt']);
  runGit(subSrc, ['commit', '-q', '-m', 'lib']);
  runGit(parent, ['-c', 'protocol.file.allow=always', 'submodule', 'add', '--quiet', subSrc, 'vendor']);
  const vendor = path.join(parent, 'vendor');
  assert.equal(hook.findGitNexusDir(vendor), null);
  assert.equal(hook.findGitNexusDir(parent), parentIndex);
  const vendorIndex = writeRepoIndex(vendor);
  assert.equal(hook.findGitNexusDir(vendor), vendorIndex);
});

test('CASE D: unproven canonical index is not reused; local worktree index wins', (t) => {
  const parent = tempDir(t, 'gitnexus-d-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const mainIndex = writeRepoIndex(parent);
  const worktree = addLinkedWorktree(t, parent, 'gitnexus-d-wt-');
  assert.equal(hook.findGitNexusDir(worktree), null);
  const worktreeIndex = writeRepoIndex(worktree);
  assert.equal(hook.findGitNexusDir(worktree), worktreeIndex);
  assert.notEqual(hook.findGitNexusDir(worktree), mainIndex);
});

test('linked worktree with a different HEAD must not use the canonical index', (t) => {
  const parent = tempDir(t, 'gitnexus-wt-diff-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const parentHead = gitHead(parent);
  writeRepoIndex(parent, { lastCommit: parentHead });
  const worktree = tempDir(t, 'gitnexus-wt-diff-wt-');
  fs.rmSync(worktree, { recursive: true, force: true });
  runGit(parent, ['worktree', 'add', '-b', 'feature', worktree]);
  t.after(() => {
    spawnSync('git', ['worktree', 'remove', '--force', worktree], {
      cwd: parent,
      encoding: 'utf8',
    });
  });
  fs.writeFileSync(path.join(worktree, 'README'), 'feature\n');
  runGit(worktree, ['add', 'README']);
  runGit(worktree, ['commit', '-q', '-m', 'feature']);
  assert.notEqual(gitHead(worktree), parentHead);
  assert.equal(hook.findGitNexusDir(worktree), null);
});

test('linked worktree with its own index uses the local index', (t) => {
  const parent = tempDir(t, 'gitnexus-wt-local-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const mainIndex = writeRepoIndex(parent, { lastCommit: gitHead(parent) });
  const worktree = addLinkedWorktree(t, parent, 'gitnexus-wt-local-wt-');
  const worktreeIndex = writeRepoIndex(worktree, { lastCommit: gitHead(worktree) });
  assert.equal(hook.findGitNexusDir(worktree), worktreeIndex);
  assert.notEqual(hook.findGitNexusDir(worktree), mainIndex);
});

test('canonical index is reused only when lastCommit matches a clean reviewed worktree', (t) => {
  const parent = tempDir(t, 'gitnexus-wt-match-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const parentHead = gitHead(parent);
  const mainIndex = writeRepoIndex(parent, { lastCommit: parentHead });
  const worktree = addLinkedWorktree(t, parent, 'gitnexus-wt-match-wt-');
  assert.equal(gitHead(worktree), parentHead);
  assert.equal(hook.findGitNexusDir(worktree), mainIndex);
});

test('ambiguous or dirty worktree identity fails open instead of reusing another checkout', (t) => {
  const parent = tempDir(t, 'gitnexus-wt-amb-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const parentHead = gitHead(parent);
  writeRepoIndex(parent, { lastCommit: parentHead });

  const unknown = addLinkedWorktree(t, parent, 'gitnexus-wt-unknown-');
  fs.writeFileSync(path.join(parent, '.gitnexus', 'gitnexus.json'), '{}\n');
  assert.equal(hook.findGitNexusDir(unknown), null);

  writeRepoIndex(parent, { lastCommit: parentHead });
  const dirty = addLinkedWorktree(t, parent, 'gitnexus-wt-dirty-');
  fs.writeFileSync(path.join(dirty, 'EXTRA'), 'dirty\n');
  assert.equal(hook.findGitNexusDir(dirty), null);

  const stale = addLinkedWorktree(t, parent, 'gitnexus-wt-stale-');
  writeRepoIndex(parent, { lastCommit: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' });
  assert.equal(hook.findGitNexusDir(stale), null);

  writeRepoIndex(parent, { lastCommit: parentHead });
  const corrupt = addLinkedWorktree(t, parent, 'gitnexus-wt-corrupt-');
  fs.writeFileSync(path.join(parent, '.gitnexus', 'gitnexus.json'), '{not-json\n');
  fs.writeFileSync(
    path.join(parent, '.gitnexus', 'meta.json'),
    `${JSON.stringify({ lastCommit: parentHead })}\n`,
  );
  assert.equal(hook.findGitNexusDir(corrupt), null);
});

test('legacy meta.json lastCommit is accepted when gitnexus.json is absent', (t) => {
  const parent = tempDir(t, 'gitnexus-wt-legacy-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const gitNexusDir = path.join(parent, '.gitnexus');
  fs.mkdirSync(gitNexusDir, { recursive: true });
  fs.writeFileSync(
    path.join(gitNexusDir, 'meta.json'),
    `${JSON.stringify({ lastCommit: gitHead(parent) })}\n`,
  );
  const worktree = addLinkedWorktree(t, parent, 'gitnexus-wt-legacy-wt-');
  assert.equal(hook.findGitNexusDir(worktree), gitNexusDir);
});

test('hook stdin: matching identity can emit additional_context without npx', (t) => {
  const parent = tempDir(t, 'gitnexus-hook-pos-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  writeRepoIndex(parent, { lastCommit: gitHead(parent) });

  const fakeRoot = tempDir(t, 'gitnexus-fake-cli-');
  const cliDir = path.join(fakeRoot, 'gitnexus', 'dist', 'cli');
  fs.mkdirSync(cliDir, { recursive: true });
  fs.writeFileSync(
    path.join(cliDir, 'index.js'),
    "console.log('[GitNexus] extra for ' + process.argv.slice(2).join(' '));\n",
  );

  const result = runHook(
    {
      cwd: parent,
      tool_name: 'Grep',
      tool_input: { pattern: 'ApifyAlibabaClient' },
    },
    { NODE_PATH: fakeRoot, GITNEXUS_CLI: path.join(cliDir, 'index.js') },
  );
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout.trim());
  assert.match(payload.additional_context, /^\[GitNexus\] /);
  assert.match(payload.additional_context, /ApifyAlibabaClient/);

  const readResult = runHook(
    {
      cwd: parent,
      tool_name: 'Read',
      tool_input: { target_file: 'src/ApifyAlibabaClient.py' },
    },
    { NODE_PATH: fakeRoot, GITNEXUS_CLI: path.join(cliDir, 'index.js') },
  );
  assert.equal(readResult.status, 0, readResult.stderr);
  const readPayload = JSON.parse(readResult.stdout.trim());
  assert.match(readPayload.additional_context, /^\[GitNexus\] /);
  assert.match(readPayload.additional_context, /ApifyAlibabaClient/);
});

test('hook stdin: Shell, unusable Grep, mismatched worktree, and missing GitNexus fail open', (t) => {
  const parent = tempDir(t, 'gitnexus-hook-neg-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  writeRepoIndex(parent, { lastCommit: gitHead(parent) });
  const worktree = tempDir(t, 'gitnexus-hook-neg-wt-');
  fs.rmSync(worktree, { recursive: true, force: true });
  runGit(parent, ['worktree', 'add', '-b', 'other', worktree]);
  t.after(() => {
    spawnSync('git', ['worktree', 'remove', '--force', worktree], {
      cwd: parent,
      encoding: 'utf8',
    });
  });
  fs.writeFileSync(path.join(worktree, 'README'), 'other\n');
  runGit(worktree, ['add', 'README']);
  runGit(worktree, ['commit', '-q', '-m', 'other']);

  const fakeRoot = tempDir(t, 'gitnexus-fake-cli-neg-');
  const cliDir = path.join(fakeRoot, 'gitnexus', 'dist', 'cli');
  fs.mkdirSync(cliDir, { recursive: true });
  fs.writeFileSync(
    path.join(cliDir, 'index.js'),
    "console.log('[GitNexus] should-not-run');\n",
  );
  const env = { NODE_PATH: fakeRoot, GITNEXUS_CLI: path.join(cliDir, 'index.js') };

  const shellIgnored = runHook(
    { cwd: parent, tool_name: 'Shell', tool_input: { command: 'rg.exe validateUser src/ || grep -e secondary file' } },
    env,
  );
  assert.equal(shellIgnored.status, 0, shellIgnored.stderr);
  assert.equal((shellIgnored.stdout || '').trim(), '');

  const unusableGrep = runHook(
    { cwd: parent, tool_name: 'Grep', tool_input: { pattern: 'id', path: 'src/' } },
    env,
  );
  assert.equal(unusableGrep.status, 0, unusableGrep.stderr);
  assert.equal((unusableGrep.stdout || '').trim(), '');

  const mismatched = runHook(
    {
      cwd: worktree,
      tool_name: 'Grep',
      tool_input: { pattern: 'ApifyAlibabaClient' },
    },
    env,
  );
  assert.equal(mismatched.status, 0, mismatched.stderr);
  assert.equal((mismatched.stdout || '').trim(), '');

  const missing = runHook(
    {
      cwd: parent,
      tool_name: 'Grep',
      tool_input: { pattern: 'ApifyAlibabaClient' },
    },
    { NODE_PATH: '' },
  );
  assert.equal(missing.status, 0, missing.stderr);
  assert.equal((missing.stdout || '').trim(), '');
});

test('hook runtime has no npx or npm network fallback', () => {
  const files = fs.readdirSync(__dirname).filter((name) => name.endsWith('.cjs') && !name.endsWith('.test.cjs'));
  for (const name of files) {
    const source = fs.readFileSync(path.join(__dirname, name), 'utf8');
    assert.doesNotMatch(source, /\bnpx\b/);
    assert.doesNotMatch(source, /npm install/);
    assert.doesNotMatch(source, /npm exec/);
  }
});

test('Windows .cmd discovery never reaches spawnSync as the command', (t) => {
  const parent = tempDir(t, 'gitnexus-cmd-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  writeRepoIndex(parent, { lastCommit: gitHead(parent) });

  const shimDir = tempDir(t, 'gitnexus-shim-');
  const jsDir = path.join(shimDir, 'node_modules', 'gitnexus', 'dist', 'cli');
  fs.mkdirSync(jsDir, { recursive: true });
  const cmdPath = path.join(shimDir, 'gitnexus.cmd');
  const jsPath = path.join(jsDir, 'index.js');
  fs.writeFileSync(cmdPath, '@echo off\r\necho pwned\r\n');
  fs.writeFileSync(jsPath, "console.log('js-cli');\n");
  const nodeDir = path.join(tempDir(t, 'gitnexus-node-dir-'), 'Program Files', 'nodejs');
  fs.mkdirSync(nodeDir, { recursive: true });
  const execPath = path.join(nodeDir, 'node.exe');
  fs.writeFileSync(execPath, '');

  const pattern = 'validateUser & dir | echo > %TEMP%\\pwned';
  const spawns = [];
  const originalLog = console.log;
  console.log = () => {};
  try {
    const result = hook.executeHook(
      { cwd: parent, tool_name: 'Grep', tool_input: { pattern } },
      {
        env: {
          ...process.env,
          PATH: '/nonexistent',
          GITNEXUS_CLI: cmdPath,
        },
        discoverOptions: {
          execPath,
          pathVar: '/nonexistent',
          npmRootGlobal: '',
          requireResolve() {
            throw new Error('not local');
          },
        },
        spawnSync(cmd, args, opts) {
          spawns.push({ cmd, args, opts });
          if (cmd === 'git') {
            return spawnSync(cmd, args, { ...opts, timeout: 2000 });
          }
          return { status: 0, stdout: '[GitNexus] extra', stderr: '' };
        },
      },
    );
    assert.equal(result.status, 'ok', JSON.stringify({ result, spawns }));
    const cli = spawns.filter((row) => row.cmd !== 'git' && row.cmd !== 'npm');
    assert.equal(cli.length, 1, JSON.stringify(spawns));
    assert.notEqual(cli[0].cmd, cmdPath);
    assert.doesNotMatch(String(cli[0].cmd), /\.cmd$/i);
    assert.equal(cli[0].cmd, execPath);
    assert.equal(cli[0].args[0], jsPath);
    assert.equal(cli[0].args[1], 'augment');
    assert.equal(cli[0].args[2], '--');
    assert.equal(cli[0].args[3], pattern);
    assert.equal(cli[0].args.length, 4);
    assert.equal(cli[0].opts.shell, false);
    assert.ok(cli[0].opts.timeout > 0);
    assert.ok(String(cli[0].cmd).includes('Program Files') || String(jsPath).includes('node_modules'));
  } finally {
    console.log = originalLog;
  }
});

test('runGitNexusCli never spawns a .cmd path and keeps the pattern as one argv cell', () => {
  const spawns = [];
  const cmdPath = 'C:\\Users\\test\\AppData\\Roaming\\npm\\gitnexus.cmd';
  const refused = hook.runGitNexusCli(cmdPath, ['augment', '--', 'x & y'], '/tmp', 1000, (cmd, args, opts) => {
    spawns.push({ cmd, args, opts });
    return { status: 0, stdout: '', stderr: '' };
  });
  assert.equal(refused.error.code, 'ENOENT');
  assert.deepEqual(spawns, []);

  const execPath = 'C:\\Program Files\\nodejs\\node.exe';
  const jsPath = 'C:\\Program Files\\nodejs\\node_modules\\gitnexus\\dist\\cli\\index.js';
  const pattern = 'foo & bar | baz > %TEMP%\\x < y';
  const ran = hook.runGitNexusCli(
    { kind: 'js', command: execPath, argsPrefix: [jsPath], path: jsPath, source: 'path' },
    ['augment', '--', pattern],
    '/tmp',
    4321,
    (cmd, args, opts) => {
      spawns.push({ cmd, args, opts });
      return { status: 0, stdout: '[GitNexus] extra', stderr: '' };
    },
  );
  assert.equal(ran.status, 0);
  assert.equal(spawns.length, 1);
  assert.equal(spawns[0].cmd, execPath);
  assert.deepEqual(spawns[0].args, [jsPath, 'augment', '--', pattern]);
  assert.equal(spawns[0].opts.shell, false);
  assert.equal(spawns[0].opts.timeout, 4321);
});

test('hook spawn paths never enable a shell for the Grep pattern', () => {
  const files = fs.readdirSync(__dirname).filter((name) => name.endsWith('.cjs') && !name.endsWith('.test.cjs'));
  for (const name of files) {
    const source = fs.readFileSync(path.join(__dirname, name), 'utf8');
    assert.doesNotMatch(source, /shell:\s*true/);
  }
});

test('executeHook spends remaining budget on the CLI after Git work', (t) => {
  const parent = tempDir(t, 'gitnexus-budget-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  writeRepoIndex(parent, { lastCommit: gitHead(parent) });
  const fakeRoot = tempDir(t, 'gitnexus-budget-cli-');
  const cliPath = path.join(fakeRoot, 'index.js');
  fs.writeFileSync(cliPath, "console.log('[GitNexus] extra');\n");
  let now = 0;
  const clock = hook.createDeadline({ budgetMs: 9000, nowFn: () => now, startedAt: 0 });
  const timeouts = [];
  const originalLog = console.log;
  const logs = [];
  console.log = (...args) => {
    logs.push(args.join(' '));
  };
  try {
    const result = hook.executeHook(
      { cwd: parent, tool_name: 'Grep', tool_input: { pattern: 'validateUser' } },
      {
        deadline: clock,
        env: { ...process.env, GITNEXUS_CLI: cliPath, PATH: '/nonexistent' },
        spawnSync(cmd, args, opts) {
          timeouts.push({ cmd, timeout: opts.timeout });
          if (cmd === 'git') {
            now += 400;
            return spawnSync(cmd, args, { ...opts, timeout: 2000 });
          }
          return { status: 0, stdout: '[GitNexus] extra for validateUser', stderr: '' };
        },
      },
    );
    assert.equal(result.status, 'ok');
    const cli = timeouts.filter((row) => row.cmd !== 'git' && row.cmd !== 'npm');
    assert.ok(cli.length >= 1, JSON.stringify(timeouts));
    assert.ok(cli[0].timeout < 9000, `cli timeout should shrink after git: ${cli[0].timeout}`);
    assert.ok(cli[0].timeout >= 7000, `cli should still have a reasonable budget: ${cli[0].timeout}`);
    assert.match(logs.join('\n'), /additional_context/);
  } finally {
    console.log = originalLog;
  }
});
