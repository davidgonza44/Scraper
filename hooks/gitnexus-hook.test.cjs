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

test('pattern-file options do not treat remaining path operands as patterns', () => {
  const cases = [
    'rg -f patterns.txt src/',
    'rg --file patterns.txt src/',
    'rg --file=patterns.txt src/',
    'rg -fpatterns.txt src/',
    'grep -f patterns.txt src/',
    'grep --file patterns.txt src/',
    'grep --file=patterns.txt src/',
    'grep -fpatterns.txt src/',
    'grep -nf patterns.txt src/',
    'rg -nf patterns.txt src/',
  ];
  for (const command of cases) {
    assert.equal(hook.extractPattern('Shell', { command }), null, command);
  }
});

test('explicit -e/--regexp still supplies the single pattern when mixed with -f/--file', () => {
  const cases = [
    ['rg -f patterns.txt -e validateUser src/', 'validateUser'],
    ['rg -e validateUser -f patterns.txt src/', 'validateUser'],
    ['rg --file patterns.txt --regexp validateUser src/', 'validateUser'],
    ['rg --regexp=validateUser --file=patterns.txt src/', 'validateUser'],
    ['grep -f patterns.txt -e validateUser src/', 'validateUser'],
    ['grep -e validateUser -f patterns.txt src/', 'validateUser'],
    ['grep --file patterns.txt --regexp validateUser src/', 'validateUser'],
    ['grep --regexp=validateUser --file=patterns.txt src/', 'validateUser'],
  ];
  for (const [command, expected] of cases) {
    assert.equal(hook.extractPattern('Shell', { command }), expected, command);
  }
});

test('ripgrep no-pattern listing modes skip GitNexus augmentation', () => {
  const noPattern = [
    'rg --files src/',
    'rg --files',
    'rg --files --hidden src/',
    'rg --hidden --files src/',
    'rg --type-list',
    'rg --type-list python',
    'rg --pcre2-version',
    'rg --pcre2-version extraarg',
    'rg --generate man',
    'rg --generate man src/',
    'rg --files -e validateUser src/',
  ];
  for (const command of noPattern) {
    assert.equal(hook.extractPattern('Shell', { command }), null, command);
  }
  assert.equal(
    hook.extractPattern('Shell', { command: 'rg --files-with-matches validateUser src/' }),
    'validateUser',
  );
  assert.equal(
    hook.extractPattern('Shell', { command: 'rg --files-without-match validateUser src/' }),
    'validateUser',
  );
});

test('GNU grep bare --color/--colour does not consume the next token', () => {
  const cases = [
    ['grep --color auto file.txt', 'auto'],
    ['grep --colour always file.txt', 'always'],
    ['grep --color never file.txt', 'never'],
    ['grep --color=auto validateUser file.txt', 'validateUser'],
    ['grep --colour=always validateUser file.txt', 'validateUser'],
    ['grep --color always validateUser file', 'always'],
    ['rg --color auto validateUser src/', 'validateUser'],
    ['rg --color=auto validateUser src/', 'validateUser'],
    ['rg --color always validateUser src/', 'validateUser'],
  ];
  for (const [command, expected] of cases) {
    assert.equal(hook.extractPattern('Shell', { command }), expected, command);
  }
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
    { NODE_PATH: fakeRoot },
  );
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout.trim());
  assert.match(payload.additional_context, /^\[GitNexus\] /);
  assert.match(payload.additional_context, /ApifyAlibabaClient/);
});

test('hook stdin: no-pattern, pattern-file, mismatched worktree, and missing GitNexus fail open', (t) => {
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
  const env = { NODE_PATH: fakeRoot };

  const noPattern = runHook(
    { cwd: parent, tool_name: 'Shell', tool_input: { command: 'rg --files src/' } },
    env,
  );
  assert.equal(noPattern.status, 0, noPattern.stderr);
  assert.equal((noPattern.stdout || '').trim(), '');

  const filePattern = runHook(
    { cwd: parent, tool_name: 'Shell', tool_input: { command: 'rg -f patterns.txt src/' } },
    env,
  );
  assert.equal(filePattern.status, 0, filePattern.stderr);
  assert.equal((filePattern.stdout || '').trim(), '');

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
  const source = fs.readFileSync(path.join(__dirname, 'gitnexus-hook.cjs'), 'utf8');
  assert.doesNotMatch(source, /\bnpx\b/);
  assert.doesNotMatch(source, /npm install/);
  assert.doesNotMatch(source, /npm exec/);
});
