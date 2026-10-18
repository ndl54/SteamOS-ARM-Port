// Extract actual QML JavaScript; synthetic points/timers/transport, no Qt/device.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const { test } = require('node:test');
const path = 'dualscreen-overlay/usr/lib/steamos-arm/bottom-screen/qml/RemotePad.qml';
const qml = process.env.REMOTE_PAD_REV
    ? execFileSync('git', ['show', `${process.env.REMOTE_PAD_REV}:${path}`], { encoding: 'utf8' })
    : fs.readFileSync(path, 'utf8');

function block(marker) {
    const start = qml.indexOf('{', qml.indexOf(marker));
    assert.ok(qml.includes(marker) && start >= 0, marker);
    let depth = 1, end = start + 1;
    while (depth && end < qml.length) {
        if (qml[end] === '{') depth++;
        if (qml[end] === '}') depth--;
        end++;
    }
    assert.equal(depth, 0, marker);
    return qml.slice(start + 1, end - 1);
}

function pad(scale = 1) {
    const events = [];
    const surface = { width: 1000 * scale, stripW: 96 * scale, slop: 14 * scale,
        fine: false, holding: false, most: 0, activeCount: 0, travelled: false, fromTap: false,
        inStrip: false, t0: 0, origin: {x: 0, y: 0}, lastC: {x: 0, y: 0},
        spread0: 0, swipeCarry: 0, mx: 0, my: 0, wx: 0, wy: 0, vx: 0, vy: 0 };
    const clickDelay = { running: false, start() { this.running = true; },
        stop() { this.running = false; } };
    const slots = (qml.match(/TouchPoint\s*\{\s*\}/g) || []).length;
    const context = vm.createContext({ surface, clickDelay,
        rp: { speed: 1.6, natural: false, momentum: true },
        Ui: { s: scale, send: (route, body) => events.push([route, body]) },
        Qt: { point: (x, y) => ({x, y}) },
        Date: { now: () => 1000 }, touch: { touchPoints: [] } });
    for (const [name, args] of [['down', ''], ['centre', 'pts'], ['spread', 'pts'], ['wheelStep', '']]) {
        vm.runInContext(`function ${name}(${args}) { ${block(`function ${name}(`)} }`, context);
    }
    surface.letGo = vm.runInContext(`(function () { with (surface) { ${block('function letGo(')} } })`, context);
    const handlers = {};
    for (const name of ['Pressed', 'Updated', 'Released', 'Canceled'])
        handlers[name] = vm.runInContext(`(function () { ${block(`on${name}:`)} })`, context);
    const tick = vm.runInContext(`(function () { ${block('onTriggered: {')} })`, context);
    return { surface, context, events, clickDelay, tick,
        event(name, points) {
            context.touch.touchPoints = points.slice(0, slots).map(([x, y]) => ({x, y, pressed: true}));
            handlers[name]();
        } };
}

test('declared points restore motion; one/two/three active fingers are tracked', () => {
    for (const count of [1, 2, 3]) {
        const p = pad();
        p.event('Pressed', Array.from({length: count}, (_, i) => [100 + i * 40, 100]));
        assert.equal(p.surface.most, count);
    }
    const p = pad();
    p.event('Pressed', [[100, 100]]);
    p.event('Updated', [[130, 100]]);
    p.tick();
    assert.equal(p.events[0][0], '/remote/move');
    assert.equal(p.events[0][1].dx, 96);
    assert.equal(p.events[0][1].dy, 0);
});

test('canvas scaling, precise mode and movement slop', () => {
    for (const scale of [1, 768 / 1080]) {
        const p = pad(scale);
        p.event('Pressed', [[100 * scale, 100 * scale]]);
        p.event('Updated', [[105 * scale, 100 * scale]]);
        p.tick();
        assert.equal(p.events.length, 0);
        p.surface.fine = true;
        p.event('Updated', [[135 * scale, 100 * scale]]);
        p.tick();
        assert.equal(p.events[0][1].dx, 32);
    }
});

test('tap queues click; second tap double clicks; second stroke drags until release', () => {
    for (const drag of [false, true]) {
        const p = pad();
        p.event('Pressed', [[100, 100]]); p.event('Released', []);
        assert.equal(p.clickDelay.running, true);
        p.event('Pressed', [[100, 100]]);
        assert.equal(p.clickDelay.running, false);
        if (drag) { p.event('Updated', [[130, 100]]); p.tick(); }
        p.event('Released', []);
        const clicks = p.events.filter(e => e[0] === '/remote/click').map(e => e[1].state);
        assert.deepEqual(clicks, drag ? ['down', 'up'] : ['click', 'click']);
        assert.equal(p.surface.holding, false);
    }
});

test('two/three-finger taps send right/middle clicks after last release', () => {
    for (const [count, button] of [[2, 'right'], [3, 'middle']]) {
        const p = pad();
        p.event('Pressed', Array.from({length: count}, (_, i) => [100 + i * 40, 100]));
        p.event('Released', [[100, 100]]);
        assert.equal(p.events.length, 0);
        p.event('Released', []);
        assert.equal(p.events[0][1].button, button);
        assert.equal(p.events[0][1].state, 'click');
    }
});

test('two-finger scroll, natural direction and momentum opt-out', () => {
    for (const natural of [false, true]) {
        const p = pad(); p.context.rp.natural = natural;
        p.context.rp.momentum = false;
        p.event('Pressed', [[100, 100], [200, 100]]);
        p.event('Updated', [[100, 180], [200, 180]]); p.tick();
        assert.equal(p.events[0][0], '/remote/wheel');
        assert.equal(p.events[0][1].dy, natural ? -2 : 2);
        p.event('Released', []);
        assert.equal(p.surface.vy, 0);
    }
    const p = pad();
    p.event('Pressed', [[100, 100], [200, 100]]);
    p.event('Updated', [[100, 180], [200, 180]]); p.tick();
    p.event('Released', []); p.tick();
    assert.equal(p.events.length, 2);
    assert.ok(p.surface.vy > 0 && p.surface.vy < 2);
});

test('scroll strip and three-finger swipe use their own output paths', () => {
    const p = pad();
    p.event('Pressed', [[950, 100]]); p.event('Updated', [[950, 180]]); p.tick();
    assert.equal(p.events[0][0], '/remote/wheel');
    const q = pad();
    q.event('Pressed', [[100, 100], [200, 100], [300, 100]]);
    q.event('Updated', [[230, 100], [330, 100], [430, 100]]);
    assert.equal(q.events[0][0], '/remote/type');
    assert.equal(JSON.stringify(q.events[0][1].chord), '["alt","Tab"]');
});

test('lifting third finger rebases centroid: stationary remaining fingers cannot scroll', () => {
    const p = pad();
    p.event('Pressed', [[100, 100], [200, 100], [600, 100]]);
    p.event('Updated', [[120, 100], [220, 100], [620, 100]]);
    p.event('Released', [[120, 100], [220, 100]]);
    p.event('Updated', [[120, 100], [220, 100]]); p.tick();
    assert.equal(p.events.length, 0);
    assert.equal(p.surface.spread0, 100);
});

test('adding a finger rebases before Qt updated-then-pressed signal order', () => {
    const p = pad();
    p.event('Pressed', [[100, 100]]);
    // Qt updates all point properties, emits updated for the stationary old
    // finger, then pressed for the new finger. The centroid shift is not motion.
    p.event('Updated', [[100, 100], [400, 100]]);
    p.event('Pressed', [[100, 100], [400, 100]]);
    p.event('Updated', [[100, 100], [400, 100]]); p.tick();
    assert.equal(p.events.length, 0);
    assert.equal(p.surface.travelled, false);
});

test('symmetric pinch zooms even though its centroid does not move', () => {
    const p = pad();
    p.event('Pressed', [[100, 100], [200, 100]]);
    p.event('Updated', [[70, 100], [230, 100]]);
    assert.equal(p.events.length, 1);
    assert.equal(p.events[0][0], '/remote/type');
    assert.equal(JSON.stringify(p.events[0][1].chord), '["ctrl","="]');
});

test('letGo clears gesture state, pending click/movement and releases a drag', () => {
    const p = pad();
    p.event('Pressed', [[100, 100]]); p.event('Released', []);
    p.event('Pressed', [[100, 100]]); p.event('Updated', [[130, 100]]);
    p.surface.fine = true; p.surface.letGo();
    for (const prop of ['most', 'activeCount', 'mx', 'my', 'wx', 'wy', 'vx', 'vy']) assert.equal(p.surface[prop], 0, prop);
    assert.equal(p.surface.fine, false);
    assert.equal(p.surface.holding, false);
    assert.equal(p.clickDelay.running, false);
    assert.equal(p.events.at(-1)[0], '/remote/letgo');
    assert.equal(p.events.at(-2)[1].state, 'up');
});

test('cancellation cannot turn a late release into a click or a late update into movement', () => {
    const p = pad();
    p.event('Pressed', [[100, 100]]); p.event('Canceled', []);
    p.event('Updated', [[140, 100]]); p.event('Released', []); p.tick();
    assert.equal(p.clickDelay.running, false);
    assert.deepEqual(p.events.map(e => e[0]), ['/remote/letgo']);
});

test('surface visibility owns cleanup, including pad-to-keys while RemotePad stays visible', () => {
    const rect = qml.slice(qml.indexOf('id: surface'), qml.indexOf('Txt {'));
    assert.match(rect, /onVisibleChanged:\s*if\s*\(!visible && rp\.visible\)\s*surface\.letGo\(\)/);
    assert.match(qml.slice(0, qml.indexOf('ColumnLayout')), /onVisibleChanged: if \(!visible\) surface\.letGo\(\)/);
    assert.match(qml, /Ui\.contrastInk\(pb\.color\)/);
});
