'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  installedFilesystemPathIdentity,
  installedFilesystemPathWithin,
} = require('../scripts/run-operational-ui-walk.js');

test('PX-AUD-014 win32 path identity lowercased on Windows platform override', () => {
  const id = installedFilesystemPathIdentity('C:\\Foo\\Bar', { platform: 'win32', realpath: (p) => p });
  assert.equal(id, 'c:\\foo\\bar');
});

test('PX-AUD-014 win32 path containment uses win32 path separators on Windows platform override', () => {
  const within = installedFilesystemPathWithin(
    'C:\\Project\\root', 'C:\\Project\\root\\sub\\file.txt',
    { platform: 'win32', realpath: (p) => p }
  );
  assert.equal(within, true);
});

test('PX-AUD-014 outside root returns false on Windows platform override', () => {
  const within = installedFilesystemPathWithin(
    'C:\\Project\\root', 'C:\\Other\\file.txt',
    { platform: 'win32', realpath: (p) => p }
  );
  assert.equal(within, false);
});

test('PX-AUD-014 traversal escape detected on Windows platform override', () => {
  const within = installedFilesystemPathWithin(
    'C:\\Project\\root', 'C:\\Project\\root\\..\\..\\escape.txt',
    { platform: 'win32', realpath: (p) => p }
  );
  assert.equal(within, false);
});
