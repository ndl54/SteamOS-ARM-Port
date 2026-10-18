// Exercise the shipped, hand-written JS with fake React/Decky. No browser/reboot.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../../external-and-mods/Decky/sm8650/konkr-control/dist/index.js', import.meta.url), 'utf8')
    .replace('export { index as default };', '');
let count = 0;
for (const [label, tablet] of [['Restart into Android', false], ['Restart into ZUI', true], ['Restart into ZUXOS', true], [undefined, false]]) {
    for (const result of [true, false, 'reject']) {
        const toasts = [];
        let calls = 0, hook = 0;
        const st = { has_dualboot: true, has_flip: tablet, dualboot_label: label, dualboot_text: 'test menu', rgb: {} };
        const api = {
            callable: (name) => async () => {
                assert.equal(name, 'boot_android'); calls++;
                if (result === 'reject') throw Error('fake failure');
                return result;
            },
            toaster: { toast: (message) => toasts.push(message) },
        };
        const jsx = (type, props) => ({ type, props });
        const window = {
            __DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit: { connect: () => api },
            DFL: new Proxy({}, { get: (_, key) => key === 'findModuleExport' ? () => null : key }),
            SP_REACT: {
                useState: () => [hook++ === 0 ? st : false, () => {}],
                useCallback: (fn) => fn, useEffect: () => {}, useRef: (v) => ({ current: v }),
            },
            SP_JSX: { jsx, jsxs: jsx, Fragment: 'fragment' },
        };
        const ctx = vm.createContext({ window, console, localStorage: { getItem: () => '0' } });
        vm.runInContext(source + '\nglobalThis.rendered = Content();', ctx);
        const findButton = (node) => {
            if (node?.type === 'ButtonItem') return node;
            for (const child of [node?.props?.children].flat().filter(Boolean)) {
                const found = findButton(child); if (found) return found;
            }
        };
        const button = findButton(ctx.rendered);
        assert.ok(button);
        assert.equal(button.props.children, label || 'Restart into Android');
        await button.props.onClick();
        assert.equal(calls, 1);
        assert.equal(toasts.length, result === true ? 0 : 1);
        if (toasts.length) {
            assert.equal(toasts[0].title, `${label || 'Restart into Android'} failed`);
            assert.equal(toasts[0].body.includes('storage may already have changed'), tablet);
        }
        count++;
    }
}
console.log(`${count} mocked UI label / RPC success / failure / rejection scenarios passed`);
