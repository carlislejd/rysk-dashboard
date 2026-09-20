const assert = require('assert');
const vm = require('vm');
const fs = require('fs');
const nodes = new Map();
const node = id => {
  if (!nodes.has(id)) nodes.set(id, { id, innerHTML: '', textContent: '', hidden: false,
    style: {}, dataset: {}, classList: { contains(){ return false; }, toggle(){} },
    querySelector(){ return null; }, querySelectorAll(){ return []; }, scrollIntoView(){},
    replaceChildren(){}, parentElement: { appendChild(){} } });
  return nodes.get(id);
};
const c = vm.createContext({ console, URLSearchParams, Date,
  document: { getElementById: node, querySelectorAll(){ return []; }, addEventListener(){} },
  window: { matchMedia(){ return {matches:true}; } },
  formatUnixDate: String, formatUnixDateTime: String, formatStrike: String,
  escapeAttr: String, shortSymbol: String, chainLabel: row => String(row.chain_id),
  setInterval(){}, fetch(){throw Error('unexpected network');}
});
vm.runInContext(fs.readFileSync('static/js/global.js','utf8'),c);
vm.runInContext(`
  loadRecent = () => {}; loadGlobalDashboard = () => {}; closeAssetDetail = () => {};
  loadOpenPositionDetails = () => {}; renderExecutionTimeline = () => {};
  selectedChain = 'all';
  selectTrendingStrike({symbol:'ETH',strike:2000,chain_id:1});
`,c);
let query = new URL(vm.runInContext('recentQuery(1)',c),'https://example.test').searchParams;
assert.equal(query.get('chain'),'1');
assert.equal(query.get('strike'),'2000');
vm.runInContext('selectExecutionBucket(100,200)',c);
query = new URL(vm.runInContext('recentQuery(1)',c),'https://example.test').searchParams;
assert.equal(query.get('symbol'),'ETH');
assert.equal(query.get('from_ts'),'100');
assert.equal(query.get('to_ts'),'200');
vm.runInContext('selectExecutionBucket(100,200)',c);
query = new URL(vm.runInContext('recentQuery(1)',c),'https://example.test').searchParams;
assert.equal(query.get('from_ts'),null);
assert.equal(query.get('symbol'),'ETH');
vm.runInContext("setChainFilter('hyperevm')",c);
query = new URL(vm.runInContext('recentQuery(1)',c),'https://example.test').searchParams;
assert.equal(query.get('chain'),'hyperevm');
assert.equal(query.get('symbol'),null);
vm.runInContext(`
  exposureView='asset';
  selectOpenExposure({symbol:'ETH',chain_id:1});
  selectExpiryRunway({expiry:2000,chain_id:1});
`,c);
assert.equal(vm.runInContext('openPositionFilters.symbol',c),'ETH');
assert.equal(vm.runInContext('openPositionFilters.expiry',c),2000);
vm.runInContext('selectExpiryRunway({expiry:2000,chain_id:1})',c);
assert.equal(vm.runInContext('openPositionFilters.symbol',c),'ETH');
assert.equal(vm.runInContext('openPositionFilters.expiry',c),undefined);
vm.runInContext('clearOpenPositionFilters()',c);
assert.equal(vm.runInContext('Object.keys(openPositionFilters).length',c),0);
console.log('global chart filters: ok');
