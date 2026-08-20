'use strict';

const fs = require('node:fs');

const CANDIDATES = Object.freeze({
  win32: Object.freeze({
    edge: Object.freeze([
      'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
      'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
    ]),
    chrome: Object.freeze([
      'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
    ])
  }),
  linux: Object.freeze({
    chromium: Object.freeze([
      '/usr/bin/google-chrome-stable', '/usr/bin/google-chrome',
      '/usr/bin/chromium', '/usr/bin/chromium-browser'
    ])
  }),
  darwin: Object.freeze({
    chrome: Object.freeze([
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium'
    ])
  })
});

function resolveBrowserLane() {
  const platform = CANDIDATES[process.platform];
  if (!platform) throw new Error(`unsupported-ui-browser-platform:${process.platform}`);
  const requested = String(process.env.PX_UI_BROWSER || '').trim().toLowerCase();
  if (requested && !Object.hasOwn(platform, requested)) {
    throw new Error(`unsupported-ui-browser-lane:${process.platform}:${requested}`);
  }
  const names = requested ? [requested] : Object.keys(platform);
  for (const name of names) {
    const executablePath = platform[name].find(candidate => fs.existsSync(candidate));
    if (executablePath) return { name, executablePath, platform: process.platform };
  }
  throw new Error(`required-ui-browser-missing:${process.platform}:${names.join(',')}`);
}

function requiredBrowserLanes() {
  if (process.platform === 'win32') return ['edge', 'chrome'];
  if (process.platform === 'darwin') return ['chrome'];
  if (process.platform === 'linux') return ['chromium'];
  throw new Error(`unsupported-ui-browser-platform:${process.platform}`);
}

module.exports = { CANDIDATES, requiredBrowserLanes, resolveBrowserLane };
