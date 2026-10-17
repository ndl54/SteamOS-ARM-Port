#!/usr/bin/env node
// Source-level JS regressions only: no Qt, dashboard import, server or device.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { test } = require('node:test');

const repo = path.resolve(__dirname, '../..');
const qmlDir = 'dualscreen-overlay/usr/lib/steamos-arm/bottom-screen/qml/';
const source = '0307a71d8754506288f37368f81ab13561427982';
const read = name => fs.readFileSync(path.join(repo, qmlDir, name), 'utf8');
const historical = ref => execFileSync('git', ['show', `${ref}:${qmlDir}DashPage.qml`],
  { cwd: repo, encoding: 'utf8' });
function predicate(qml) {
  const expression = qml.match(/readonly property bool shown: ([^\n]+)/)[1];
  return st => vm.runInNewContext(expression, { dash: { st }, rows: st.sessions || [] });
}
const shown = predicate(read('DashPage.qml'));
const row = { appid: 42, name: 'Previous game', minutes: 2, wh: 0.3, fps: 60, end: 1000 };
const history = [row];
const frameRates = [undefined, null, 0, 60, null, 30, null];

test('Steam redraw FPS sequence no longer removes a populated Recent card', () => {
  const states = frameRates.map(fps => ({ sessions: history, game: { appid: 0, name: '' }, fps }));
  assert.deepEqual(states.map(predicate(historical(`${source}^`))),
    [true, true, false, false, true, false, true]);
  assert.deepEqual(states.map(shown), states.map(() => true));
});

test('focused game remains hidden even when paused or FPS is absent', () => {
  for (const fps of frameRates)
    assert.equal(shown({ sessions: history, game: { appid: 42, name: 'Game' }, fps }), false);
});

test('focused ID without a manifest name must still hide Recent', () => {
  const state = { sessions: history, game: { appid: 4294967295, name: '' }, fps: null };
  assert.equal(predicate(historical(source))(state), true, 'reproduce upstream metadata gap');
  assert.equal(shown(state), false);
  assert.equal(shown({ ...state, game: { appid: 42 } }), false);
});

test('empty or missing history stays hidden, including initial state', () => {
  for (const sessions of [undefined, null, []])
    for (const game of [undefined, null, { appid: 0 }, { appid: 42 }])
      assert.equal(shown({ sessions, game }), false);
  assert.equal(shown({}), false);
});

test('missing focus metadata is tolerated and new history becomes visible', () => {
  for (const game of [undefined, null, {}, { appid: 0, name: '' }])
    assert.equal(shown({ sessions: history, game }), true);
  assert.equal(shown({ sessions: history, game: { appid: 0, name: 'Stale label' } }), true);
});

test('focus enter, switch and leave controls visibility independently of FPS', () => {
  const games = [{ appid: 0 }, { appid: 42, name: 'A' }, { appid: 43, name: '' }, { appid: 0 }];
  assert.deepEqual(games.map(game => shown({ sessions: history, game, fps: 60 })),
    [true, false, false, true]);
});

// Exercise Main.qml's actual callback body with inert request/stat sinks.
// Qt binding/layout, images and network timing are deliberately not simulated.
function pollHarness(initial) {
  const qml = read('Main.qml');
  const start = qml.indexOf('    function pollState() {');
  const end = qml.indexOf('\n    Connections {', start);
  assert.ok(start >= 0 && end > start);
  let reply;
  const samples = [];
  const Ui = { st: initial, request: (method, route, body, done) => {
    assert.equal(method, 'GET'); assert.equal(route, '/state'); done(reply);
  } };
  const context = vm.createContext({ Ui, root: { shotFile: '', demo: false },
    dashPage: { pushFps: f => samples.push(['fps', f]), pushStats: n => samples.push(['stats', n]) } });
  vm.runInContext(qml.slice(start, end), context);
  return { Ui, samples, poll: value => { reply = value; vm.runInContext('pollState()', context); } };
}

test('null/error and hidden replies retain the last accepted state and rows', () => {
  const initial = { sessions: history, game: { appid: 0 }, fps: null };
  const h = pollHarness(initial);
  for (const response of [null, undefined, { hidden: true }]) {
    h.poll(response);
    assert.equal(h.Ui.st, initial);
    assert.equal(h.Ui.st.sessions, history);
    assert.equal(shown(h.Ui.st), true);
  }
  assert.equal(h.samples.length, 0);
});

test('successful polls replace snapshots but equal history keeps visibility stable', () => {
  const h = pollHarness({});
  for (const fps of frameRates) {
    const snapshot = { sessions: [{ ...row }], game: { appid: 0 }, fps };
    h.poll(snapshot);
    assert.equal(h.Ui.st, snapshot);
    assert.equal(shown(h.Ui.st), true);
  }
  const empty = { sessions: [], game: { appid: 0 }, fps: 60 };
  h.poll(empty);
  assert.equal(shown(h.Ui.st), false);
  assert.equal(h.samples.length, (frameRates.length + 1) * 2);
});
