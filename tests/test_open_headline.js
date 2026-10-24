const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const nodes = new Map();
function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
        textContent: '', innerHTML: '', style: {}, attributes: {},
        setAttribute(key, value) { this.attributes[key] = value; },
        classList: { toggle() {} }, replaceChildren() {}, setCustomValidity() {},
        querySelector() { return null; },
    });
    return nodes.get(id);
}
const pending = [];
const context = vm.createContext({
    document: { getElementById: node, addEventListener() {}, querySelectorAll() { return []; } },
    compactCurrency: value => `$${value}`, formatNumber: String, formatUnixDate: String,
    fetch: url => new Promise((resolve, reject) => pending.push({ url, resolve, reject })),
});
vm.runInContext(fs.readFileSync('static/js/global.js', 'utf8'), context);
vm.runInContext('renderOpenExposure = renderExpiryRunway = renderTrendingStrikes = loadGlobalDashboard = closeAssetDetail = () => {};', context);
const data = notional => ({ success: true, top_asset_24h: null, avg_dte: { avg: null, min: null },
    active_positions: { notional, count: 503, premium: 50000 },
    activity: { volume_vs_daily_avg: null, volume_24h: 0, premium_24h: 0, trades_24h: 0, volume_7d: 135860000, trades_7d: 1000 },
    observation: { last_trade_at: 1792796400 }, popular_strikes: [],
});
function settle(request, notional) { request.resolve({ ok: true, json: async () => data(notional) }); }

async function verifyHeadline() {
    node('protocol-tvl').textContent = '$37690000';
    const initial = context.loadMarketPulse();
    settle(pending[0], 40760000);
    await initial;
    assert.equal(node('hero-tvl').textContent, '$40760000', 'headline is independently calculated open notional');
    assert.equal(node('hero-tvl-sub').innerHTML, '503 open positions');
    assert.match(node('protocol-open-observed').textContent, /Last observed trade: .* UTC/);
    assert.equal(node('protocol-tvl').textContent, '$37690000', 'DeFiLlama remains a separate reference');

    context.setChainFilter('ethereum');
    assert.equal(node('hero-tvl').textContent, '—', 'network switch clears relocated headline immediately');
    assert.match(node('protocol-open-scope').textContent, /Ethereum/);
    const ethereum = context.loadMarketPulse();
    context.setChainFilter('hyperevm');
    const hyper = context.loadMarketPulse();
    settle(pending[2], 30000000);
    await hyper;
    settle(pending[1], 10760000);
    await ethereum;
    assert.equal(node('hero-tvl').textContent, '$30000000', 'old network response cannot overwrite new headline');

    const failing = context.loadMarketPulse();
    pending[3].reject(new Error('offline'));
    await failing;
    assert.equal(node('hero-tvl').textContent, '—');
    assert.match(node('hero-tvl-sub').innerHTML, /unavailable/);
    assert.equal(node('protocol-open-observed').textContent, '');
    assert.equal(node('protocol-open-panel').attributes['aria-busy'], 'false');
    assert.equal(node('protocol-tvl').textContent, '$37690000', 'source failure never substitutes the reference value');

    const old = context.loadMarketPulse();
    const latest = context.loadMarketPulse();
    settle(pending[5], 29000000);
    await latest;
    pending[4].reject(new Error('late failure'));
    await old;
    assert.equal(node('hero-tvl').textContent, '$29000000', 'late failure cannot erase a newer snapshot');

    const missing = context.loadMarketPulse();
    settle(pending[6], null);
    await missing;
    assert.equal(node('hero-tvl').textContent, '—', 'missing open notional is unavailable, never zero or reference TVL');

    const template = fs.readFileSync('templates/global.html', 'utf8');
    assert.equal((template.match(/id="hero-tvl"/g) || []).length, 1, 'headline has one source-bound DOM value');
    assert.ok(template.indexOf('id="hero-tvl"') < template.indexOf('id="protocol-tvl-panel"'));
    assert.match(template, /Open position notional/);
    assert.match(template, /DeFiLlama TVL reference/);
    console.log('Independent open headline, reference separation, network clearing, request races and failure states: ok');
}
verifyHeadline().catch(error => { console.error(error); process.exitCode = 1; });
