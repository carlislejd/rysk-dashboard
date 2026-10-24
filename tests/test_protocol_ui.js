const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const nodes = new Map();
function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
        textContent: '', innerHTML: '', className: '', attributes: {},
        setAttribute(key, value) { this.attributes[key] = value; },
        querySelector() { return { addEventListener() {} }; },
    });
    return nodes.get(id);
}
const pending = [];
const context = vm.createContext({
    document: { getElementById: node, querySelectorAll() { return [node('window-label')]; }, addEventListener() {} },
    withChain: path => path,
    fetch: url => new Promise((resolve, reject) => pending.push({ url, resolve, reject })),
});
vm.runInContext(fs.readFileSync('static/js/protocol.js', 'utf8'), context);
const call = (fn, ...args) => context[fn](...args);
assert.equal(call('protocolComparison', { change_pct: -100 }, 30, true), 'Recorded activity · collection may be incomplete');
assert.equal(call('protocolPercent', null), '—');
assert.equal(call('protocolPercent', 0), '0.0%');

async function verifySelectionIsolation() {
    vm.runInContext('var renders = []; renderProtocolOverview = data => renders.push(data.label);', context);
    const first = call('loadProtocolOverview');
    vm.runInContext('protocolDays = 90', context);
    const second = call('loadProtocolOverview');
    assert.equal(node('window-label').textContent, '90d', 'window labels track selection immediately, including while loading');
    assert.match(pending[0].url, /days=30/);
    assert.match(pending[1].url, /days=90/);
    pending[1].resolve({ ok: true, json: async () => ({ success: true, label: '90d' }) });
    await second;
    pending[0].resolve({ ok: true, json: async () => ({ success: true, label: '30d' }) });
    await first;
    assert.deepEqual(Array.from(vm.runInContext('renders', context)), ['90d'], 'a stale response cannot repaint a new selection');
    const failing = call('loadProtocolOverview');
    pending[2].reject(new Error('offline'));
    await failing;
    assert.equal(node('protocol-notional').textContent, '—', 'failed new scopes must not show old values');
    assert.match(node('protocol-status').innerHTML, /Try again/);
    assert.equal(node('protocol-kpis').attributes['aria-busy'], 'false');
    console.log('protocol freshness, missing values, request isolation and retry: ok');
}
verifySelectionIsolation().catch(error => { console.error(error); process.exitCode = 1; });
