const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const hook = require('./gitnexus-hook.cjs');

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

test('missing GitNexus remains a local, fail-open result', () => {
  const result = hook.runGitNexusCli('', ['augment', '--', 'pattern'], process.cwd(), 100);
  assert.equal(result.error.code, 'ENOENT');
  assert.equal(result.stdout, '');
});

