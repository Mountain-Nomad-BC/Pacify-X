'use strict';

function activate() {
  return Object.freeze({ fixture: 'px-owned.fixture', version: '2.0.0' });
}

function deactivate() {}

module.exports = { activate, deactivate };
