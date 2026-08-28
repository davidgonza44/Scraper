'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { normalizePath, pathsEqual, pathContains } = require('./path-identity.cjs');

const windowsCases = [
  {
    name: 'drive letter case and separators',
    a: 'C:\\repo',
    b: 'c:/repo',
    equal: true,
    contains: true,
  },
  {
    name: 'trailing separator',
    a: 'C:\\repo\\',
    b: 'C:\\repo',
    equal: true,
    contains: true,
  },
  {
    name: 'mixed separators and nested file',
    a: 'C:\\repo',
    b: 'C:/repo/src/app.js',
    equal: false,
    contains: true,
  },
  {
    name: 'sibling repo2 is not inside repo',
    a: 'C:\\repo',
    b: 'C:\\repo2',
    equal: false,
    contains: false,
  },
  {
    name: 'repo2 trailing slash is still outside repo',
    a: 'C:\\repo\\',
    b: 'C:\\repo2\\',
    equal: false,
    contains: false,
  },
  {
    name: 'alternate-cased nested path',
    a: 'c:\\Repo',
    b: 'C:\\REPO\\hooks\\gitnexus-hook.cjs',
    equal: false,
    contains: true,
  },
  {
    name: 'UNC share equality',
    a: '\\\\Server\\Share\\repo',
    b: '//server/share/repo',
    equal: true,
    contains: true,
  },
  {
    name: 'UNC nested containment',
    a: '\\\\Server\\Share\\repo',
    b: '\\\\server\\share\\repo\\src',
    equal: false,
    contains: true,
  },
  {
    name: 'UNC sibling is not contained',
    a: '\\\\Server\\Share\\repo',
    b: '\\\\Server\\Share\\repo2',
    equal: false,
    contains: false,
  },
  {
    name: 'different drive letters',
    a: 'C:\\repo',
    b: 'D:\\repo',
    equal: false,
    contains: false,
  },
];

const posixCases = [
  {
    name: 'exact path',
    a: '/repo',
    b: '/repo',
    equal: true,
    contains: true,
  },
  {
    name: 'trailing slash',
    a: '/repo/',
    b: '/repo',
    equal: true,
    contains: true,
  },
  {
    name: 'nested file',
    a: '/repo',
    b: '/repo/src/app.js',
    equal: false,
    contains: true,
  },
  {
    name: 'sibling repo2 is not inside repo',
    a: '/repo',
    b: '/repo2',
    equal: false,
    contains: false,
  },
  {
    name: 'case-sensitive on POSIX',
    a: '/repo',
    b: '/Repo',
    equal: false,
    contains: false,
  },
  {
    name: 'duplicate slashes normalize',
    a: '/repo/src',
    b: '/repo//src',
    equal: true,
    contains: true,
  },
];

test('Windows path identity is case-insensitive and prefix-safe', () => {
  for (const row of windowsCases) {
    assert.equal(pathsEqual(row.a, row.b, 'win32'), row.equal, `equal: ${row.name}`);
    assert.equal(pathContains(row.a, row.b, 'win32'), row.contains, `contains: ${row.name}`);
  }
  assert.equal(normalizePath('c:/repo\\', 'win32'), 'C:\\repo');
  assert.equal(normalizePath('\\\\Server\\\\Share\\\\repo\\', 'win32'), '\\\\Server\\Share\\repo');
});

test('POSIX path identity remains case-sensitive and prefix-safe', () => {
  for (const row of posixCases) {
    assert.equal(pathsEqual(row.a, row.b, 'linux'), row.equal, `equal: ${row.name}`);
    assert.equal(pathContains(row.a, row.b, 'linux'), row.contains, `contains: ${row.name}`);
  }
});
