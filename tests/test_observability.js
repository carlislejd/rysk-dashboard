/* The analytics loader's privacy and origin boundary must remain fail-closed. */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('static/js/observability.js', 'utf8');
const token = 'a'.repeat(32);
const wallet = '0x' + 'b'.repeat(40);
const alias = 'b'.repeat(64);
function load(options = {}) {
    const appended = [];
    const config = options.config === undefined ? {token, origin: 'https://rysk.example'} : options.config;
    const location = new URL(options.url || 'https://rysk.example/');
    const document = {
        referrer: options.referrer || '',
        getElementById() { return config ? {textContent: JSON.stringify(config)} : null; },
        querySelector() { return options.existing || appended[0] || null; },
        createElement() { return {setAttribute(key, value) { this[key] = value; }}; },
        head: {appendChild(script) { appended.push(script); }},
    };
    const context = vm.createContext({document, window: {location}, navigator: options.navigator || {}, URL, Set});
    vm.runInContext(source, context);
    if (options.twice) vm.runInContext(source, context);
    return appended;
}
const scripts = load({twice: true});
assert.equal(scripts.length, 1);
assert.equal(scripts[0].src, 'https://static.cloudflareinsights.com/beacon.min.js');
assert.equal(scripts[0].type, 'module');
assert.equal(scripts[0].defer, true);
assert.deepEqual(JSON.parse(scripts[0]['data-cf-beacon']), {token, spa: false});
assert.equal(load({url: 'https://rysk.example/analytics#act-retention'}).length, 1);
for (const url of [
    'http://rysk.example/', 'https://preview.example/', 'http://localhost:5001/',
    'https://rysk.example/account', `https://rysk.example/trader/${alias}`,
    'https://rysk.example/docs', `https://rysk.example/?address=${wallet}`,
    'https://rysk.example/analytics?chain=999', `https://rysk.example/#${wallet}`,
    `https://rysk.example/#${alias}`, `https://rysk.example/#%2530x${'b'.repeat(40)}`,
]) assert.equal(load({url}).length, 0, url);
for (const referrer of [
    `https://external.example/${wallet}`, `https://external.example/?wallet=${wallet}`,
    `https://rysk.example/account`, `https://rysk.example/trader/${alias}`, 'https://rysk.example/docs',
    `https://external.example/%30x${'b'.repeat(40)}`,
]) assert.equal(load({referrer}).length, 0, referrer);
assert.equal(load({referrer: 'https://external.example/article'}).length, 1);
assert.equal(load({referrer: 'https://rysk.example/'}).length, 1);
assert.equal(load({config: null}).length, 0);
assert.equal(load({config: {token: '<script>', origin: 'https://rysk.example'}}).length, 0);
assert.equal(load({config: {token, origin: 'http://rysk.example'}, url: 'http://rysk.example/'}).length, 0);
assert.equal(load({existing: {id: 'auto-injected-beacon'}}).length, 0);
assert.equal(load({navigator: {doNotTrack: '1'}}).length, 0);
assert.equal(load({navigator: {globalPrivacyControl: true}}).length, 0);
console.log('observability analytics privacy: ok');
