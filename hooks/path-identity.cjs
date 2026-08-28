'use strict';

function normalizePath(input, platform = process.platform) {
  if (input == null) return '';
  let s = String(input);
  if (platform === 'win32') {
    s = s.replace(/\//g, '\\');
    if (s.startsWith('\\\\')) {
      s = `\\\\${s.slice(2).replace(/\\+/g, '\\')}`;
    } else {
      s = s.replace(/\\+/g, '\\');
    }
    if (/^[a-zA-Z]:/.test(s)) {
      s = `${s[0].toUpperCase()}:${s.slice(2)}`;
    }
    return stripTrailingWindowsSeparators(s);
  }
  s = s.replace(/\/+/g, '/');
  if (s.length > 1) s = s.replace(/\/+$/, '');
  return s;
}

function stripTrailingWindowsSeparators(s) {
  if (/^[A-Z]:\\$/i.test(s)) return s;
  if (/^\\\\[^\\]+\\[^\\]+$/.test(s)) return s;
  return s.replace(/\\+$/, '');
}

function compareKey(input, platform = process.platform) {
  const normalized = normalizePath(input, platform);
  return platform === 'win32' ? normalized.toLowerCase() : normalized;
}

function pathsEqual(a, b, platform = process.platform) {
  return compareKey(a, platform) === compareKey(b, platform);
}

function pathContains(parent, child, platform = process.platform) {
  const parentKey = compareKey(parent, platform);
  const childKey = compareKey(child, platform);
  if (!parentKey) return false;
  if (childKey === parentKey) return true;
  const sep = platform === 'win32' ? '\\' : '/';
  const prefix = parentKey.endsWith(sep) ? parentKey : parentKey + sep;
  return childKey.startsWith(prefix);
}

module.exports = {
  normalizePath,
  compareKey,
  pathsEqual,
  pathContains,
};
