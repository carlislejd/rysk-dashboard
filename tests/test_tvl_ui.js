const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const nodes = new Map();
function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
        textContent: '', innerHTML: '', className: '', hidden: false, attributes: {},
        style: {}, dataset: {}, listeners: {}, value: '',
        classList: { toggle() {}, contains() { return false; } },
        setAttribute(key, value) { this.attributes[key] = value; },
        addEventListener(name, listener) { this.listeners[name] = listener; },
        querySelector() { return null; }, querySelectorAll() { return []; },
        replaceChildren() {}, setCustomValidity() {},
    });
    return nodes.get(id);
}
const ranges = [7, 30, 90].map(days => {
    const button = node(`range-${days}`);
    button.dataset.protocolDays = String(days);
    return button;
});
const pending = [];
const ready = [];
const intervals = [];
const context = vm.createContext({
    document: {
        getElementById: node,
        querySelectorAll: selector => selector === '[data-protocol-days]' ? ranges : [],
        addEventListener(name, listener) { if (name === 'DOMContentLoaded') ready.push(listener); },
        hidden: false,
    },
    compactCurrency: value => `$${value}`,
    setInterval: listener => intervals.push(listener),
    fetch: url => new Promise((resolve, reject) => pending.push({ url, resolve, reject })),
});
vm.runInContext(fs.readFileSync('static/js/global.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('static/js/protocol.js', 'utf8'), context);
vm.runInContext(`
    var activityLoads = 0;
    loadProtocolOverview = () => { activityLoads += 1; };
    loadNextExpiryPositions = loadMarketPulse = loadExecutionTimeline = loadRecent =
        loadAssets = loadExpiryExplorer = loadFlowChart = closeAssetDetail =
        initActNavScrollSpy = initStrikeLens = () => {};
`, context);
const snapshot = (usd, stale = false) => ({
    success: true,
    tvl: { usd, as_of: 1792796400, fetched_at: 1792796401, is_stale: stale,
        source: 'DeFiLlama', source_url: 'https://defillama.com/protocol/rysk-v12', protocol: 'Rysk V12' },
    filters: { chain_id: null },
});
const settle = (request, data) => request.resolve({ ok: true, json: async () => data });
const flush = () => new Promise(resolve => setImmediate(resolve));

async function verifyTvl() {
    ready.forEach(listener => listener());
    assert.equal(pending.length, 1, 'initial dashboard load requests TVL once');
    assert.equal(pending[0].url, '/api/global/tvl');
    settle(pending[0], snapshot(37690000));
    await flush();
    assert.equal(node('protocol-tvl').textContent, '$37690000');
    assert.equal(node('protocol-tvl-scope').textContent, 'Rysk V12 · all networks · USD');
    assert.equal(node('protocol-tvl-as-of').textContent, 'Source snapshot: 2026-10-23 23:00 UTC');
    assert.equal(node('protocol-tvl-status').className, '');
    assert.equal(node('protocol-tvl-retry').hidden, true);
    assert.equal(node('protocol-tvl-panel').attributes['aria-busy'], 'false');

    for (const button of [ranges[0], ranges[2], ranges[1]]) {
        node('protocol-range-tabs').listeners.click({ target: { closest: () => button } });
    }
    assert.equal(pending.length, 1, '7d/90d/30d activity changes do not request TVL');
    assert.equal(vm.runInContext('activityLoads', context), 4);
    assert.equal(node('protocol-tvl').textContent, '$37690000', 'activity windows cannot change TVL');

    context.setChainFilter('ethereum');
    assert.equal(pending[1].url, '/api/global/tvl?chain=ethereum');
    assert.equal(node('protocol-tvl').textContent, '—', 'previous network TVL clears immediately');
    context.setChainFilter('hyperevm');
    assert.equal(pending[2].url, '/api/global/tvl?chain=hyperevm');
    assert.equal(node('protocol-tvl-scope').textContent, 'Rysk V12 · HyperEVM · USD');
    settle(pending[2], snapshot(27000000));
    await flush();
    settle(pending[1], snapshot(10000000));
    await flush();
    assert.equal(node('protocol-tvl').textContent, '$27000000', 'late previous-network responses cannot repaint TVL');

    intervals[0]();
    assert.equal(pending[3].url, '/api/global/tvl?chain=hyperevm', 'visible-page refresh updates TVL');
    settle(pending[3], snapshot(26000000, true));
    await flush();
    assert.equal(node('protocol-tvl').textContent, '$26000000', 'stale source values remain explicitly dated');
    assert.equal(node('protocol-tvl-status').className, 'is-stale');
    assert.match(node('protocol-tvl-status').textContent, /Stale snapshot/);
    assert.equal(node('protocol-tvl-retry').hidden, false);
    context.document.hidden = true;
    intervals[0]();
    assert.equal(pending.length, 4, 'hidden pages do not poll TVL');
    context.document.hidden = false;

    const reload = context.loadGlobalDashboard();
    assert.equal(pending.length, 5, 'global reload refreshes TVL independently');
    pending[4].reject(new Error('offline'));
    await reload;
    assert.equal(node('protocol-tvl').textContent, '—', 'source failure does not retain an unlabelled previous value');
    assert.match(node('protocol-tvl-status').textContent, /temporarily unavailable/);
    assert.equal(node('protocol-tvl-retry').hidden, false);
    assert.equal(node('protocol-tvl-panel').attributes['aria-busy'], 'false');

    for (const invalid of [
        { success: true, metrics: { notional: { value: 135860000 } } },
        { ...snapshot(null), notional: 135860000 },
        snapshot(-10), snapshot(Infinity),
        { ...snapshot(1000), tvl: { usd: 1000, as_of: null } },
    ]) {
        const request = context.loadProtocolTvl();
        settle(pending.at(-1), invalid);
        await request;
        assert.equal(node('protocol-tvl').textContent, '—', 'missing or invalid TVL cannot fall back to turnover or zero');
        assert.match(node('protocol-tvl-status').textContent, /temporarily unavailable/);
    }

    const retry = node('protocol-tvl-retry').listeners.click();
    settle(pending.at(-1), snapshot(0));
    await retry;
    assert.equal(node('protocol-tvl').textContent, '$0', 'a valid empty network is zero, distinct from unavailable');
    assert.equal(node('protocol-tvl-retry').hidden, true);

    const oldFailure = context.loadProtocolTvl();
    const oldRequest = pending.at(-1);
    const newSuccess = context.loadProtocolTvl();
    settle(pending.at(-1), snapshot(5000000));
    await newSuccess;
    oldRequest.reject(new Error('late error'));
    await oldFailure;
    assert.equal(node('protocol-tvl').textContent, '$5000000', 'an obsolete failure cannot erase the latest snapshot');

    const template = fs.readFileSync('templates/global.html', 'utf8');
    assert.ok(template.indexOf('id="protocol-tvl-panel"') < template.indexOf('id="protocol-kpis"'));
    assert.match(template, /href="https:\/\/defillama\.com\/protocol\/rysk-v12"/);
    assert.match(template, /data-protocol-window>30d<\/span> traded notional/);
    assert.match(template, /Turnover can reuse the same capital/);
    console.log('TVL source freshness, chain races, range independence, refresh, retry and no turnover fallback: ok');
}

verifyTvl().catch(error => { console.error(error); process.exitCode = 1; });
