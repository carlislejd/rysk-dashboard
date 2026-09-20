// Anonymous historical trader record. This page intentionally never receives wallet addresses.

const TRADER_PAGE_SIZE = 50;
const traderId = decodeURIComponent(window.location.pathname.split('/').pop() || '');
const traderParams = new URLSearchParams(window.location.search);
let traderDays = Number(traderParams.get('days') ?? 0);
let traderChain = traderParams.get('chain_id') || 'all';
let traderPage = Number(traderParams.get('page') ?? 1);
let traderRequestId = 0;

function escapeTraderHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[char]));
}

function traderChainLabel(trade) {
    return trade.chain_name || (Number(trade.chain_id) === 1 ? 'Ethereum' : Number(trade.chain_id) === 999 ? 'HyperEVM' : 'Unknown');
}

function traderDate(timestamp, withTime = false) {
    if (!timestamp) return '—';
    return new Date(Number(timestamp) * 1000).toLocaleDateString('en-US', withTime ? { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' } : { month: 'short', day: 'numeric', year: 'numeric' });
}

function traderWindowLabel() {
    return traderDays === 0 ? 'all recorded history' : traderDays === 365 ? 'trailing year' : `trailing ${traderDays} days`;
}

function traderApiUrl() {
    const params = new URLSearchParams({ days: String(traderDays), page: String(traderPage), limit: String(TRADER_PAGE_SIZE) });
    if (traderChain !== 'all') params.set('chain_id', traderChain);
    return `/api/analytics/traders/${encodeURIComponent(traderId)}?${params.toString()}`;
}

function syncTraderUrl() {
    const params = new URLSearchParams({ days: String(traderDays) });
    if (traderChain !== 'all') params.set('chain_id', traderChain);
    if (traderPage > 1) params.set('page', String(traderPage));
    window.history.replaceState({}, '', `/trader/${encodeURIComponent(traderId)}?${params.toString()}`);
}

function setTraderFilters() {
    document.querySelectorAll('#trader-range-tabs [data-days]').forEach(button => button.classList.toggle('active', Number(button.dataset.days) === traderDays));
    document.querySelectorAll('#trader-chain-tabs [data-chain]').forEach(button => button.classList.toggle('active', button.dataset.chain === traderChain));
}

function clearTraderTotals() {
    ['trader-notional', 'trader-premium', 'trader-apr', 'trader-trades'].forEach(id => {
        document.getElementById(id).textContent = '—';
    });
}

function renderTraderTotals(data) {
    const totals = data.totals || {};
    document.getElementById('trader-title').textContent = data.identity?.alias || 'Trader history';
    document.getElementById('trader-notional').textContent = formatCurrency(totals.notional, 0);
    document.getElementById('trader-premium').textContent = formatCurrency(totals.premium);
    document.getElementById('trader-apr').textContent = formatPercentage(totals.weighted_apr, 1);
    document.getElementById('trader-trades').textContent = formatNumber(totals.trade_count || 0, 0);
}

function renderTraderTrades(data) {
    const body = document.getElementById('trader-trades-body');
    const trades = data.trades || [];
    if (!trades.length) {
        body.innerHTML = '<tr><td colspan="11" class="trader-empty">No recorded executions match these filters.</td></tr>';
    } else {
        body.innerHTML = trades.map(trade => {
            const outcome = trade.outcome === 'Assigned' ? '<span class="trader-outcome trader-assigned">Assigned</span>'
                : trade.outcome === 'Returned' ? '<span class="trader-outcome trader-returned">Returned</span>'
                : trade.outcome ? escapeTraderHtml(trade.outcome) : '—';
            return `<tr><td>${traderDate(trade.created_at, true)}</td><td><span class="chain-badge ${escapeTraderHtml(trade.chain_slug || '')}">${escapeTraderHtml(traderChainLabel(trade))}</span></td><td>${escapeTraderHtml(trade.symbol || '—')}</td><td>${escapeTraderHtml(trade.type || '—')}</td><td>${formatStrike(trade.strike)}</td><td>${formatNumber(trade.quantity, 4)}</td><td>${formatCurrency(trade.premium)}</td><td>${formatCurrency(trade.notional, 0)}</td><td>${formatPercentage(trade.apr, 1)}</td><td>${traderDate(trade.expiry)}</td><td>${outcome}</td></tr>`;
        }).join('');
    }
    const pagination = data.pagination || {};
    const page = Number(pagination.page) || 1;
    const pages = Math.max(1, Number(pagination.pages) || 1);
    document.getElementById('trader-pagination').innerHTML = `<button class="pager-btn" type="button" data-trader-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>Prev</button><span class="pager-info">Page ${page} of ${pages}</span><button class="pager-btn" type="button" data-trader-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>Next</button>`;
}

async function loadTraderHistory() {
    const requestId = ++traderRequestId;
    const status = document.getElementById('trader-status');
    const loading = document.getElementById('trader-trades-loading');
    const content = document.getElementById('trader-trades-content');
    status.textContent = 'Loading recorded history…';
    loading.textContent = 'Loading executions…';
    loading.hidden = false;
    content.hidden = true;
    clearTraderTotals();
    try {
        const response = await fetch(traderApiUrl());
        const data = await response.json();
        if (requestId !== traderRequestId) return;
        if (!response.ok || !data.success) throw new Error(data.error || 'Request failed');
        renderTraderTotals(data);
        renderTraderTrades(data);
        const coverage = data.coverage;
        status.textContent = `${traderWindowLabel()} · ${traderChain === 'all' ? 'all chains' : traderChain === 'ethereum' ? 'Ethereum' : 'HyperEVM'}${coverage?.coverage_pct != null ? ` · ${Number(coverage.coverage_pct).toFixed(1)}% attribution coverage` : ''}`;
        loading.hidden = true;
        content.hidden = false;
    } catch (error) {
        if (requestId !== traderRequestId) return;
        status.textContent = `Trader history unavailable: ${error.message}`;
        loading.textContent = 'This anonymous historical record is unavailable.';
        loading.hidden = false;
        content.hidden = true;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (![0, 30, 90, 365].includes(traderDays)) traderDays = 0;
    if (traderChain === '1') traderChain = 'ethereum';
    if (traderChain === '999') traderChain = 'hyperevm';
    if (!['all', 'ethereum', 'hyperevm'].includes(traderChain)) traderChain = 'all';
    if (!Number.isInteger(traderPage) || traderPage < 1) traderPage = 1;
    setTraderFilters();
    syncTraderUrl();
    loadTraderHistory();
    document.getElementById('trader-range-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-days]');
        if (!button) return;
        traderDays = Number(button.dataset.days);
        traderPage = 1;
        setTraderFilters(); syncTraderUrl(); loadTraderHistory();
    });
    document.getElementById('trader-chain-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-chain]');
        if (!button) return;
        traderChain = button.dataset.chain;
        traderPage = 1;
        setTraderFilters(); syncTraderUrl(); loadTraderHistory();
    });
    document.getElementById('trader-pagination').addEventListener('click', event => {
        const button = event.target.closest('[data-trader-page]');
        if (!button || button.disabled) return;
        traderPage = Number(button.dataset.traderPage);
        syncTraderUrl(); loadTraderHistory();
    });
});
