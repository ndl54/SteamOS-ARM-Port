// Source-level colour regression: no Qt, desktop, backend service or device.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const qml = path.join(root, 'dualscreen-overlay/usr/lib/steamos-arm/bottom-screen/qml');
const read = name => readFileSync(path.join(qml, name), 'utf8');
const ui = read('Ui.qml');
const functions = ['linearChannel', 'contrastInk'].map(name => {
    const match = ui.match(new RegExp(`    function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n    \\}`));
    assert.ok(match, `Missing ${name}`);
    return match[0];
}).join('\n');
const ctx = vm.createContext({});
vm.runInContext(functions, ctx);
const rgb = hex => ({ r: parseInt(hex.slice(1, 3), 16) / 255,
    g: parseInt(hex.slice(3, 5), 16) / 255, b: parseInt(hex.slice(5, 7), 16) / 255 });
// Independent contrast calculation, not the implementation under test.
const luminance = c => [c.r, c.g, c.b].reduce((sum, v, i) => sum +
    [0.2126, 0.7152, 0.0722][i] * (v <= 0.04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4), 0);
const ratio = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) /
    (Math.min(luminance(a), luminance(b)) + .05);
let cases = 0;
for (const name of ['aura', 'pulse', 'gauges', 'black']) {
    const palette = JSON.parse(read(`skins/${name}/skin.json`)).colors;
    const accent = rgb(palette.accent);
    const pressed = rgb(palette.cardHi);
    // Active controls, pressed controls, darkened modifier/Precise fills,
    // and intermediate frames of the existing 140 ms colour animation.
    const fills = [accent, pressed, Object.fromEntries(Object.entries(accent).map(([k, v]) => [k, v / 1.9]))];
    for (let i = 0; i <= 20; i++) fills.push(Object.fromEntries(
        Object.keys(accent).map(k => [k, accent[k] * i / 20 + pressed[k] * (1 - i / 20)])));
    for (const fill of fills) {
        const ink = rgb(ctx.contrastInk(fill));
        assert.ok(ratio(ink, fill) >= 4.5, `${name} unreadable fill: ${JSON.stringify(fill)}`);
        cases++;
    }
    if (name === 'black' || name === 'gauges') {
        assert.ok(ratio(rgb('#ffffff'), accent) < 2, `${name}: original regression no longer represented`);
        assert.equal(ctx.contrastInk(accent), '#000000');
    }
}
// Guard the affected consumers: a correct helper alone cannot fix white ink.
for (const [name, expected] of [
    ['Btn.qml', ['active ? Ui.contrastInk(b.color) : Ui.text', 'color: b.ink']],
    ['Seg.qml', ['opt.on ? Ui.contrastInk(opt.color) : Ui.dim']],
    ['HomePage.qml', ['color: Ui.onAccent']],
    ['Tile.qml', ['text: "↓"; color: Ui.onAccent']],
    ['NotesPage.qml', ['selectedTextColor: Ui.onAccent']],
    ['KeyPad.qml', ['key.lit ? Ui.contrastInk(key.color) : Ui.text', 'key.lit ? Ui.contrastInk(key.color) : Ui.dim']],
    ['RemotePad.qml', ['hold.active && pb.isFine ? Ui.contrastInk(pb.color) : Ui.text']],
]) for (const binding of expected) assert.ok(read(name).includes(binding), `${name}: ${binding}`);
assert.equal((read('Btn.qml').match(/color: b\.ink/g) || []).length, 2, 'Both button text and icon need ink');
assert.ok(ui.includes('readonly property color onAccent: contrastInk(accent)'));
console.log(`PASS: ${cases} palette/state/animation contrast cases; original black/amber failures reproduced; 7 consumer bindings`);
