/* Wallet history filters, payoff boundaries, and account-switch isolation. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/dashboard.js', 'utf8');
const nodes = new Map();
function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
        id, innerHTML: '', textContent: '', style: {}, hidden: false,
        classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
        querySelectorAll() { return []; }, querySelector() { return null; },
        addEventListener() {}, setAttribute() {}, removeAttribute() {},
    });
    return nodes.get(id);
}
const pending = [];
const store = new Map();
const context = {
    console, URLSearchParams, AbortController,
    setTimeout() { return 1; }, clearTimeout() {},
    document: {
        getElementById: node, querySelectorAll() { return []; }, querySelector() { return null; },
        addEventListener() {}, body: { classList: { add() {}, remove() {} } },
    },
    window: {},
    localStorage: { getItem: key => store.get(key), setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) },
    fetch(url, options) { return new Promise((resolve, reject) => pending.push({ url, options, resolve, reject })); },
    Plotly: { Plots: { resize() {} } }, setupSortableTable() {},
    formatDateLabel: String, formatNumber: String, formatCurrency: value => `$${value}`,
    formatTileCurrency: value => `$${value}`, formatPercentage: value => `${value}%`,
    formatStrike: String, strategyBadge() { return ''; }, sideBadge() { return ''; }, statusBadge() { return ''; },
};
vm.createContext(context);
vm.runInContext(source, context);
const call = (name, ...args) => {
    context.args = args;
    return vm.runInContext(`${name}(...args)`, context);
};

const now = Date.parse('2026-10-23T12:00:00Z');
const day = 86400000;
const rows = [
    { symbol: 'ETH', type: 'Put', expiry: (now - day) / 1000, outcome: 'Assigned', premium: 40, apr: 18 },
    { symbol: 'ETH', type: 'Call', expiry: (now - 31 * day) / 1000, outcome: 'Returned', premium: 100, apr: 40 },
    { symbol: 'BTC', type: 'Put', expiry: (now - 2 * day) / 1000, outcome: 'Unknown', premium: 5, apr: null },
    { symbol: 'ETH', type: 'Put', expiry: (now - 3 * day) / 1000, outcome: 'Returned', premium: 10, apr: 0 },
    { symbol: 'ETH', type: 'Put', expiry: (now + day) / 1000, outcome: 'Assigned', premium: 900 },
    { symbol: 'ETH', type: 'Put', expiry: null, expiry_date: 'invalid', outcome: 'Assigned', premium: 1000 },
];
const defaults = { asset: '', outcome: '', type: '', days: 0, sort: 'recent' };
assert.equal(call('filterWalletHistory', rows, { ...defaults, asset: 'ETH', type: 'put', outcome: 'assigned', days: 30 }, now).length, 1);
assert.equal(call('filterWalletHistory', rows, { ...defaults, outcome: 'pending' }, now)[0].symbol, 'BTC');
assert.equal(call('filterWalletHistory', rows, { ...defaults, days: 30, sort: 'premium' }, now)[0].premium, 40);
assert.equal(call('filterWalletHistory', rows, { ...defaults, days: 30, sort: 'apr' }, now)[1].apr, 0);
assert.equal(call('filterWalletHistory', rows, { ...defaults, sort: 'oldest' }, now)[0].premium, 100);
assert.equal(rows[0].premium, 40, 'filtering must not sort the original source array');

const shortPut = { side: 'Sell', type: 'Put', outcome: 'Assigned', premium: 20, strike: 100, expiry_price: 90, quantity: 3 };
assert.equal(call('settledOptionPayoff', [shortPut]).value, -10);
assert.equal(call('settledOptionPayoff', [{ ...shortPut, side: 'Buy' }]).value, 10);
assert.equal(call('settledOptionPayoff', [{ ...shortPut, type: 'Call', expiry_price: 110 }]).value, -10);
assert.equal(call('settledOptionPayoff', [{ ...shortPut, outcome: 'Returned', premium: 0 }]).value, 0, 'a known zero is valid');
assert.equal(call('settledOptionPayoff', [{ ...shortPut, expiry_price: null }]).value, null, 'missing settlement price cannot imply zero cost');
assert.equal(call('settledOptionPayoff', [{ ...shortPut, quantity: 'no data' }]).missingCount, 1);
assert.equal(call('settledOptionPayoff', [{ ...shortPut, side: null }]).value, null, 'unknown direction cannot imply a short');
assert.equal(call('settledOptionPayoff', [{ ...shortPut, outcome: 'Unknown' }]).value, null);
assert.equal(call('settledOptionPayoff', [shortPut, { ...shortPut, outcome: 'active', premium: 500 }]).value, -10, 'open premium is excluded from settled payoff');

const csv = call('walletHistoryCsv', [{ ...shortPut, symbol: '=HYPERLINK("bad")', wallet_address: 'private-address', tx_hash: 'private-tx', expiry_price: null }]);
assert.match(csv, /"'=HYPERLINK\(""bad""\)"/);
assert.doesNotMatch(csv, /private-address|private-tx/);
assert.match(csv, /"Assigned",""$/);
assert.equal(call('walletHistoryCsv', rows).split('\r\n').length, rows.length + 1, 'exports cover every filtered row, not the current page');

const walletA = '0x1111111111111111111111111111111111111111';
const walletB = '0x2222222222222222222222222222222222222222';
store.set('dashboardAccounts', JSON.stringify([walletA, walletA.toUpperCase().replace('0X', '0x'), 'bad', 12]));
assert.equal(call('readSavedWallets').length, 1);
store.set('dashboardAccounts', 'malformed'); store.set('dashboardAccount', walletB);
assert.equal(call('readSavedWallets')[0], walletB);
const savedStorage = context.localStorage;
context.localStorage = { getItem() { throw new Error('blocked storage'); } };
assert.equal(call('readSavedWallets').length, 0);
context.localStorage = savedStorage;

// Keep real fetch/cache behavior while excluding chart rendering from this test.
vm.runInContext(`
    renderHistoryOutcomeComposition = () => {};
    setupHistoryExplorer = () => {};
    renderDeepDiveInline = () => {};
    renderPortfolioHealth = () => {};
    var premiumRuns = [];
    renderAccountPnl = (history, positions) => premiumRuns.push({ history, positions });
    var heroRuns = [];
    populateAccountHero = (positions, history) => heroRuns.push({ account: currentAccount, positions, history });
    accountStatusEl = document.getElementById('account-status');
`, context);

const response = body => ({ ok: true, json: async () => body });
async function verifyRequests() {
    vm.runInContext(`currentAccount = '${walletA}'; walletAddresses = ['${walletA}'];`, context);
    const first = call('loadAllData');
    const firstRequests = pending.splice(0);
    vm.runInContext(`currentAccount = '${walletB}'; walletAddresses = ['${walletB}'];`, context);
    const second = call('loadAllData');
    const secondRequests = pending.splice(0);
    assert.equal(firstRequests.length, 2);
    assert.ok(firstRequests.every(request => request.options.signal.aborted));
    secondRequests[0].resolve(response({ success: true, positions: { open_positions: [], summary: { marker: 'B' } } }));
    secondRequests[1].resolve(response({ success: true, history: { expired_positions: [], summary: { marker: 'B' } } }));
    await second;
    firstRequests[0].resolve(response({ success: true, positions: { open_positions: [], summary: { marker: 'A' } } }));
    firstRequests[1].resolve(response({ success: true, history: { expired_positions: [], summary: { marker: 'A' } } }));
    await first;
    assert.equal(vm.runInContext('historyDataCache.summary.marker', context), 'B');
    assert.equal(vm.runInContext('heroRuns.length', context), 1);
    assert.equal(vm.runInContext('heroRuns[0].account', context), walletB);
    assert.equal(vm.runInContext(`_positions_cache.has('${walletA}')`, context), false);

    const failedRefresh = call('loadAllData');
    const failedRequests = pending.splice(0);
    failedRequests.forEach(request => request.reject(new Error('source unavailable')));
    await failedRefresh;
    assert.equal(vm.runInContext('historyDataCache.summary.marker', context), 'B', 'failed refresh retains the known snapshot');
    assert.match(node('account-status').textContent, /Some data could not refresh/);
    assert.equal(node('account-refresh').disabled, false);

    const partialRefresh = call('loadAllData');
    const partialRequests = pending.splice(0);
    partialRequests[0].resolve(response({ success: true, positions: { open_positions: [], summary: { marker: 'B-new' } } }));
    partialRequests[1].reject(new Error('history unavailable'));
    await partialRefresh;
    assert.equal(vm.runInContext('premiumRuns.length', context), 1, 'combined premium chart must not combine a new open book with old history');
    assert.equal(vm.runInContext('heroRuns.at(-1).history', context), null, 'combined headline is unavailable during a partial refresh');
    assert.equal(node('pnl-data-status').hidden, false);
    console.log('wallet history, payoff, storage and account isolation: ok');
}
verifyRequests().catch(error => { console.error(error); process.exitCode = 1; });
