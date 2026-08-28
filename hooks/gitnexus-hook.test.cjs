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

function writeRepoIndex(dir) {
  const gitNexusDir = path.join(dir, '.gitnexus');
  fs.mkdirSync(gitNexusDir, { recursive: true });
  fs.writeFileSync(path.join(gitNexusDir, 'gitnexus.json'), '{}\n');
  return gitNexusDir;
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
  assert.ok(roots.includes(path.join('C:\\Users\\test\\AppData\\Roaming', 'npm', 'node_modules')));
});

test('explicit regexp options provide the single augmentation pattern', () => {
  const cases = [
    ['rg -e validateUser src/', 'validateUser'],
    ['grep -e validateUser src/', 'validateUser'],
    ['rg --regexp validateUser src/', 'validateUser'],
    ['grep --regexp validateUser src/', 'validateUser'],
    ['rg --regexp=validateUser src/', 'validateUser'],
    ['grep --regexp=validateUser src/', 'validateUser'],
    ["rg -e pattern --glob '*.py' src/", 'pattern'],
    ["rg --glob '*.py' -e pattern src/", 'pattern'],
    ['grep -n -e pattern file', 'pattern'],
    ['grep --regexp=pattern file', 'pattern'],
    ['rg -e first -e second src/', 'first'],
  ];
  for (const [command, expected] of cases) {
    assert.equal(hook.extractPattern('Shell', { command }), expected, command);
  }
});

test('ordinary patterns and value-bearing flags remain supported', () => {
  assert.equal(hook.extractPattern('Shell', { command: 'rg validateUser src/' }), 'validateUser');
  assert.equal(hook.extractPattern('Shell', { command: 'grep validateUser src/' }), 'validateUser');
  assert.equal(hook.extractPattern('Shell', { command: "rg --glob '*.py' validateUser src/" }), 'validateUser');
});

test('value-bearing rg/grep options are skipped in both space and attached forms', () => {
  const cases = [
    ['grep --exclude-dir cache validateUser .', 'validateUser'],
    ['grep --exclude-dir=cache validateUser .', 'validateUser'],
    ['rg --context 3 validateUser src/', 'validateUser'],
    ['rg --context=3 validateUser src/', 'validateUser'],
    ["rg --type-add 'web:*.html' validateUser src/", 'validateUser'],
    ["rg --type-add='web:*.html' validateUser src/", 'validateUser'],
    ['grep --exclude-from ignore.txt validateUser .', 'validateUser'],
    ['rg --max-count 4 validateUser src/', 'validateUser'],
    ['rg --encoding utf-8 validateUser src/', 'validateUser'],
    ['grep -C 3 validateUser file', 'validateUser'],
    ['grep --directories recurse validateUser .', 'validateUser'],
    ['rg --glob *.py validateUser src/', 'validateUser'],
    ['rg --glob=*.py validateUser src/', 'validateUser'],
    ['grep -r validateUser src/', 'validateUser'],
    ['rg -r foo validateUser src/', 'validateUser'],
    ['grep --color validateUser file', 'validateUser'],
    ['grep --color=always validateUser file', 'validateUser'],
    ['grep --color always validateUser file', 'validateUser'],
  ];
  for (const [command, expected] of cases) {
    assert.equal(hook.extractPattern('Shell', { command }), expected, command);
  }
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
  assert.match(workflow, /node --test hooks\/gitnexus-hook\.test\.cjs hooks\/hook-lock\.test\.cjs/);
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

test('CASE D: worktree without its own index uses the canonical repository index', (t) => {
  const parent = tempDir(t, 'gitnexus-d-main-');
  initGitRepo(parent);
  fs.writeFileSync(path.join(parent, 'README'), 'main\n');
  runGit(parent, ['add', 'README']);
  runGit(parent, ['commit', '-q', '-m', 'init']);
  const mainIndex = writeRepoIndex(parent);
  const worktree = tempDir(t, 'gitnexus-d-wt-');
  fs.rmSync(worktree, { recursive: true, force: true });
  runGit(parent, ['worktree', 'add', '--detach', worktree]);
  t.after(() => {
    spawnSync('git', ['worktree', 'remove', '--force', worktree], {
      cwd: parent,
      encoding: 'utf8',
    });
  });
  assert.equal(hook.findGitNexusDir(worktree), mainIndex);
  const worktreeIndex = writeRepoIndex(worktree);
  assert.equal(hook.findGitNexusDir(worktree), worktreeIndex);
  assert.notEqual(hook.findGitNexusDir(worktree), mainIndex);
});
