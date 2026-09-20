/* Bounded interaction checks for the portfolio chart-linked table state. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/js/dashboard.js', 'utf8');

const nodes = new Map();
function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
        id, innerHTML: '', style: {}, hidden: false, classList: { add() {}, remove() {}, toggle() {} },
        querySelectorAll() { return []; }, querySelector() { return null; }, addEventListener() {},
    });
    return nodes.get(id);
}

const context = {
    console, setTimeout() {}, clearTimeout() {}, URLSearchParams,
    document: {
        getElementById: node, querySelectorAll() { return []; }, querySelector() { return null; },
        addEventListener() {}, body: { classList: { add() {}, remove() {} } },
    },
    window: {}, localStorage: { getItem() { return null; }, setItem() {} },
    fetch() { throw new Error('network is not used by this unit test'); },
    Plotly: { newPlot() { return Promise.resolve(); }, Plots: { resize() {} }, purge() {} },
    setupSortableTable() {}, formatDateLabel: value => String(value), formatNumber: value => String(value),
    formatStrike: value => String(value), formatCurrency: value => `$${value}`, formatPercentage: value => `${value}%`,
    strategyBadge: () => '', sideBadge: () => '', statusBadge: () => '', getPlotlyTheme: () => ({ fontColor: '', gridColor: '' }),
};
vm.createContext(context);
vm.runInContext(source, context, { filename: 'dashboard.js' });

vm.runInContext(`
    openPositionsData = [
      {symbol:'ETH', type:'Call', days_to_expiry:0, notional:10},
      {symbol:'ETH', type:'Put', days_to_expiry:3, notional:20},
      {symbol:'BTC', type:'Call', days_to_expiry:3.01, notional:30},
      {symbol:'BTC', type:'Put', days_to_expiry:7, notional:40},
      {symbol:'SOL', type:'Call', days_to_expiry:7.01, notional:50},
      {symbol:'SOL', type:'Put', days_to_expiry:14, notional:60},
      {symbol:'HYPE', type:'Call', days_to_expiry:14.01, notional:70}
    ];
    portfolioDteSelection = '0-3'; portfolioExposureSelection = null; renderOpenPositionsPage(1);
`, context);
assert.match(node('open-positions-container').innerHTML, /ETH/);
assert.doesNotMatch(node('open-positions-container').innerHTML, /BTC/);

vm.runInContext(`portfolioDteSelection = '3-7'; portfolioExposureSelection = {symbol:'BTC', type:'put'}; renderOpenPositionsPage(1);`, context);
assert.match(node('open-positions-container').innerHTML, /BTC/);
assert.doesNotMatch(node('open-positions-container').innerHTML, /SOL/);

vm.runInContext(`portfolioDteSelection = '7-14'; portfolioExposureSelection = null; renderOpenPositionsPage(1);`, context);
assert.match(node('open-positions-container').innerHTML, /SOL/);
assert.doesNotMatch(node('open-positions-container').innerHTML, /HYPE/);

vm.runInContext(`portfolioDteSelection = '14+'; renderOpenPositionsPage(1);`, context);
assert.match(node('open-positions-container').innerHTML, /HYPE/);

// The single outcome control owns Clear and no legacy card handler is invoked.
assert.match(source, /history-outcome-clear/);
assert.doesNotMatch(source, /setupOutcomeFilters\(expiredPositions, summary\);/);

// The clear path used by the selection chip removes both composed dimensions.
vm.runInContext(`portfolioDteSelection = ''; portfolioExposureSelection = null; renderOpenPositionsPage(2);`, context);
assert.match(node('open-positions-container').innerHTML, /SOL/);
assert.match(node('open-positions-container').innerHTML, /HYPE/);

console.log('portfolio visual filters: ok');
