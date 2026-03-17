// Global Dashboard JavaScript — Asset-focused with Inventory & Outcomes

let selectedAsset = null;
let currentHistoryPage = 1;
const HISTORY_PER_PAGE = 20;
const DETAIL_TRADES_PER_PAGE = 25;

// ── Helpers ──

function formatUnixDate(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatUnixDateTime(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function shortSymbol(symbol) {
    if (!symbol) return '—';
    const dash = symbol.indexOf('-');
    return dash > 0 ? symbol.substring(0, dash) : symbol;
}

function compactCurrency(num) {
    if (num === null || num === undefined) return '$0';
    const abs = Math.abs(num);
    if (abs >= 1e6) return `$${(num / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `$${(num / 1e3).toFixed(0)}K`;
    return formatCurrency(num, 0);
}

function outcomeBadge(outcome) {
    if (outcome === 'Assigned') return '<span class="status-badge" style="background: var(--color-error-dim); color: var(--color-error);">Assigned</span>';
    if (outcome === 'Returned') return '<span class="status-badge" style="background: var(--accent-dim); color: var(--accent);">Returned</span>';
    return '<span class="status-badge status-default">Unknown</span>';
}

// ── Protocol Summary ──

async function loadSummary() {
    const loading = document.getElementById('summary-loading');
    const content = document.getElementById('summary-content');
    try {
        const resp = await fetch('/api/global/summary');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        document.getElementById('summary-grid').innerHTML = `
            <div class="summary-card">
                <div class="summary-label">Total Trades</div>
                <div class="summary-value">${formatNumber(data.total_trades, 0)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Total Notional</div>
                <div class="summary-value">${compactCurrency(data.total_volume)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Total Premium</div>
                <div class="summary-value">${compactCurrency(data.total_premium)}</div>
                <div class="summary-subtext">${compactCurrency(data.active_premium)} active</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Avg APR</div>
                <div class="summary-value">${formatPercentage(data.avg_apr)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">24h Volume</div>
                <div class="summary-value">${compactCurrency(data.last_24h.volume)}</div>
                <div class="summary-subtext">${data.last_24h.trades} trades</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">7d Volume</div>
                <div class="summary-value">${compactCurrency(data.last_7d.volume)}</div>
                <div class="summary-subtext">${data.last_7d.trades} trades</div>
            </div>
        `;

        // Populate filter dropdowns
        if (data.assets) {
            ['volume-symbol', 'history-symbol'].forEach(id => {
                const sel = document.getElementById(id);
                if (sel && sel.options.length <= 1) {
                    data.assets.forEach(asset => {
                        const opt = document.createElement('option');
                        opt.value = asset;
                        opt.textContent = shortSymbol(asset);
                        sel.appendChild(opt);
                    });
                }
            });
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load summary: ' + e.message;
    }
}

// ── Inventory ──

async function loadInventory() {
    const loading = document.getElementById('inventory-loading');
    const content = document.getElementById('inventory-content');
    try {
        const resp = await fetch('/api/global/inventory');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const tabs = document.getElementById('inventory-tabs');
        const panels = document.getElementById('inventory-panels');

        tabs.innerHTML = data.assets.map((a, i) =>
            `<button class="tab-button ${i === 0 ? 'active' : ''}" data-inv-tab="${a.asset}">${a.asset}</button>`
        ).join('');

        panels.innerHTML = data.assets.map((a, i) => {
            const indexDisplay = a.index != null ? (a.index >= 1 ? `$${formatNumber(a.index, 2)}` : `$${a.index.toFixed(6)}`) : '—';
            const renderRows = (options) => options.map(o => {
                const strikeDisplay = o.strike >= 1 ? formatCurrency(o.strike, 0) : `$${o.strike.toFixed(4)}`;
                const apyClass = o.apy >= 50 ? 'style="color: var(--accent);"' : '';
                return `<tr>
                    <td>${strikeDisplay}</td>
                    <td>${o.expiry_label || formatUnixDate(o.expiry)}</td>
                    <td>${formatNumber(o.days_to_expiry, 1)}</td>
                    <td ${apyClass}>${formatPercentage(o.apy, 1)}</td>
                    <td>${o.delta ? formatNumber(o.delta, 3) : '—'}</td>
                    <td>${o.bid_iv ? formatPercentage(o.bid_iv, 1) : '—'}</td>
                    <td>${o.ask_iv ? formatPercentage(o.ask_iv, 1) : '—'}</td>
                </tr>`;
            }).join('');
            const puts = a.options.filter(o => o.is_put);
            const calls = a.options.filter(o => !o.is_put);
            return `
                <div class="inventory-table ${i === 0 ? 'active' : ''}" data-inv-panel="${a.asset}">
                    <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px;">
                        <div class="tabs" style="margin-bottom: 0; border-bottom: none;">
                            <button class="tab-button active" data-type-tab="puts" data-type-asset="${a.asset}">Puts (${a.put_count})</button>
                            <button class="tab-button" data-type-tab="calls" data-type-asset="${a.asset}">Calls (${a.call_count})</button>
                        </div>
                        <span style="font-family: var(--font-mono); color: var(--text-primary);">
                            Index: ${indexDisplay}
                        </span>
                    </div>
                    <table class="data-table" data-type-panel="puts" data-type-asset="${a.asset}">
                        <thead><tr><th>Strike</th><th>Expiry</th><th>Days</th><th>APY</th><th>Delta</th><th>Bid IV</th><th>Ask IV</th></tr></thead>
                        <tbody>${puts.length ? renderRows(puts) : '<tr><td colspan="7" style="text-align:center; color: var(--text-muted);">No puts available</td></tr>'}</tbody>
                    </table>
                    <table class="data-table" data-type-panel="calls" data-type-asset="${a.asset}" style="display: none;">
                        <thead><tr><th>Strike</th><th>Expiry</th><th>Days</th><th>APY</th><th>Delta</th><th>Bid IV</th><th>Ask IV</th></tr></thead>
                        <tbody>${calls.length ? renderRows(calls) : '<tr><td colspan="7" style="text-align:center; color: var(--text-muted);">No calls available</td></tr>'}</tbody>
                    </table>
                </div>
            `;
        }).join('');

        // Asset tab switching
        tabs.addEventListener('click', e => {
            const btn = e.target.closest('.tab-button');
            if (!btn) return;
            const asset = btn.dataset.invTab;
            tabs.querySelectorAll('.tab-button').forEach(b => b.classList.toggle('active', b === btn));
            panels.querySelectorAll('.inventory-table').forEach(p => p.classList.toggle('active', p.dataset.invPanel === asset));
        });

        // Put/Call type switching within each panel
        panels.addEventListener('click', e => {
            const btn = e.target.closest('[data-type-tab]');
            if (!btn) return;
            const type = btn.dataset.typeTab;
            const asset = btn.dataset.typeAsset;
            const panel = panels.querySelector(`.inventory-table[data-inv-panel="${asset}"]`);
            if (!panel) return;
            panel.querySelectorAll('[data-type-tab]').forEach(b => b.classList.toggle('active', b === btn));
            panel.querySelectorAll('[data-type-panel]').forEach(t => {
                t.style.display = t.dataset.typePanel === type ? '' : 'none';
            });
        });

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load inventory: ' + e.message;
    }
}

// ── Volume Chart ──

async function loadVolumeChart() {
    const days = document.getElementById('volume-days').value;
    const symbol = document.getElementById('volume-symbol').value;
    const params = new URLSearchParams({ days });
    if (symbol) params.set('symbol', symbol);

    try {
        const resp = await fetch('/api/global/volume?' + params);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const dates = data.data.map(d => d.date);
        const volumes = data.data.map(d => d.volume);
        const premiums = data.data.map(d => d.premium);

        Plotly.newPlot('volume-chart', [
            { x: dates, y: volumes, type: 'bar', name: 'Notional', marker: { color: 'rgba(74, 222, 128, 0.6)' } },
            { x: dates, y: premiums, type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#fb923c', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
        ], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter, sans-serif', color: '#a1a1aa', size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { gridcolor: '#27272a', tickfont: { size: 11 } },
            yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#fb923c' }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.15, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
    } catch (e) {
        document.getElementById('volume-chart').innerHTML = `<div class="error">Failed to load chart: ${e.message}</div>`;
    }
}

// ── Asset Grid ──

async function loadAssets() {
    const loading = document.getElementById('assets-loading');
    const content = document.getElementById('assets-content');
    try {
        const resp = await fetch('/api/global/assets');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        document.getElementById('asset-grid').innerHTML = data.assets.map(a => {
            const base = shortSymbol(a.symbol);
            const putPct = a.trade_count > 0 ? ((a.put_count / a.trade_count) * 100).toFixed(0) : 0;
            const callPct = a.trade_count > 0 ? ((a.call_count / a.trade_count) * 100).toFixed(0) : 0;
            return `
                <div class="asset-card" data-asset="${a.symbol}" onclick="showAssetDetail('${a.symbol}')">
                    <div class="asset-card-header">
                        <span class="asset-symbol"><span class="token-badge ${base.toLowerCase()}">${base}</span></span>
                        <span class="asset-count">${formatNumber(a.trade_count, 0)} trades</span>
                    </div>
                    <div class="asset-card-metrics">
                        <div class="asset-metric"><span class="asset-metric-label">Notional</span><span class="asset-metric-value">${compactCurrency(a.total_volume)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Premium</span><span class="asset-metric-value">${compactCurrency(a.total_premium)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Avg APR</span><span class="asset-metric-value asset-summary-apr">${formatPercentage(a.avg_apr)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Put / Call</span><span class="asset-metric-value">${putPct}% / ${callPct}%</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">7d Vol</span><span class="asset-metric-value">${compactCurrency(a.last_7d.volume)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">24h Vol</span><span class="asset-metric-value">${compactCurrency(a.last_24h.volume)}</span></div>
                    </div>
                </div>
            `;
        }).join('');

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load assets: ' + e.message;
    }
}

// ── Asset Detail Panel ──

async function showAssetDetail(symbol) {
    selectedAsset = symbol;
    const panel = document.getElementById('asset-detail');
    const base = shortSymbol(symbol);

    document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('selected'));
    const card = document.querySelector(`.asset-card[data-asset="${symbol}"]`);
    if (card) card.classList.add('selected');

    document.getElementById('detail-asset-name').innerHTML = `<span class="token-badge ${base.toLowerCase()}">${base}</span> ${symbol} Detail`;
    panel.style.display = 'block';
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });

    const [detailResp, volResp, tradesResp] = await Promise.all([
        fetch(`/api/global/asset/${encodeURIComponent(symbol)}`),
        fetch(`/api/global/volume?symbol=${encodeURIComponent(symbol)}&days=90`),
        fetch(`/api/global/trades?symbol=${encodeURIComponent(symbol)}&limit=${DETAIL_TRADES_PER_PAGE}&page=1`),
    ]);
    const [detail, vol, trades] = await Promise.all([detailResp.json(), volResp.json(), tradesResp.json()]);

    if (detail.success) renderDetailSummary(detail);
    if (detail.success) renderStrikeChart(detail);
    if (detail.success) renderExpiryBreakdown(detail);
    if (vol.success) renderDetailVolumeChart(vol);
    if (trades.success) renderDetailTrades(trades, symbol);
}

function renderDetailSummary(detail) {
    const strikes = detail.strikes || [];
    const expiries = detail.expiries || [];
    const totalTrades = strikes.reduce((s, r) => s + r.trade_count, 0);
    const totalVol = strikes.reduce((s, r) => s + r.volume, 0);
    const totalPrem = strikes.reduce((s, r) => s + r.premium, 0);
    const totalPutVol = strikes.reduce((s, r) => s + r.put_volume, 0);
    const totalCallVol = strikes.reduce((s, r) => s + r.call_volume, 0);
    const avgApr = strikes.reduce((s, r) => s + (r.avg_apr || 0) * r.trade_count, 0) / (totalTrades || 1);

    // Outcome totals from expiry data
    const totalAssigned = expiries.reduce((s, e) => s + (e.assigned || 0), 0);
    const totalReturned = expiries.reduce((s, e) => s + (e.returned || 0), 0);
    const outcomeTotal = totalAssigned + totalReturned;
    const assignedPct = outcomeTotal > 0 ? (totalAssigned / outcomeTotal * 100).toFixed(1) : '—';

    document.getElementById('detail-summary').innerHTML = `
        <div class="summary-card"><div class="summary-label">Trades</div><div class="summary-value">${formatNumber(totalTrades, 0)}</div></div>
        <div class="summary-card"><div class="summary-label">Total Notional</div><div class="summary-value">${compactCurrency(totalVol)}</div></div>
        <div class="summary-card"><div class="summary-label">Total Premium</div><div class="summary-value">${compactCurrency(totalPrem)}</div></div>
        <div class="summary-card"><div class="summary-label">Avg APR</div><div class="summary-value">${formatPercentage(avgApr)}</div></div>
        <div class="summary-card"><div class="summary-label">Put / Call</div><div class="summary-value">${compactCurrency(totalPutVol)} / ${compactCurrency(totalCallVol)}</div></div>
        <div class="summary-card"><div class="summary-label">Assignment Rate</div><div class="summary-value">${assignedPct}%</div><div class="summary-subtext">${totalAssigned} assigned / ${totalReturned} returned</div></div>
    `;
}

function renderStrikeChart(detail) {
    const strikes = detail.strikes || [];
    if (!strikes.length) { document.getElementById('detail-strike-chart').innerHTML = '<div class="loading">No strike data</div>'; return; }
    Plotly.newPlot('detail-strike-chart', [
        { x: strikes.map(s => formatCurrency(s.strike, 0)), y: strikes.map(s => s.put_volume), type: 'bar', name: 'Put', marker: { color: 'rgba(248, 113, 113, 0.7)' } },
        { x: strikes.map(s => formatCurrency(s.strike, 0)), y: strikes.map(s => s.call_volume), type: 'bar', name: 'Call', marker: { color: 'rgba(34, 211, 238, 0.7)' } },
    ], {
        barmode: 'stack', paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'Inter, sans-serif', color: '#a1a1aa', size: 12 },
        margin: { l: 60, r: 20, t: 20, b: 60 },
        xaxis: { title: 'Strike', gridcolor: '#27272a', tickfont: { size: 10 }, tickangle: -45 },
        yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickprefix: '$' },
        legend: { orientation: 'h', y: -0.25, font: { size: 11 } }, bargap: 0.15,
    }, { responsive: true, displayModeBar: false });
}

function renderExpiryBreakdown(detail) {
    const expiries = detail.expiries || [];
    if (!expiries.length) { document.getElementById('detail-expiry-content').innerHTML = '<div class="loading">No expiry data</div>'; return; }
    const now = Date.now() / 1000;
    document.getElementById('detail-expiry-content').innerHTML = `
        <table class="data-table" id="detail-expiry-table">
            <thead><tr>
                <th data-sort-key="expiry">Expiry</th>
                <th data-sort-key="trades">Trades</th>
                <th>Puts</th><th>Calls</th>
                <th data-sort-key="volume">Notional</th>
                <th data-sort-key="premium">Premium</th>
                <th data-sort-key="apr">Avg APR</th>
                <th>Settlement</th>
                <th>Assigned</th><th>Returned</th>
            </tr></thead>
            <tbody>${expiries.map(e => {
                const expired = e.expiry && e.expiry < now;
                const pxDisplay = e.expiry_price != null ? formatCurrency(e.expiry_price, 2) : (expired ? '—' : '');
                return `<tr>
                    <td data-sort-key="expiry" data-sort-value="${e.expiry}">${formatUnixDate(e.expiry)}</td>
                    <td data-sort-key="trades" data-sort-value="${e.trade_count}">${e.trade_count}</td>
                    <td>${e.put_count}</td><td>${e.call_count}</td>
                    <td data-sort-key="volume" data-sort-value="${e.volume}">${compactCurrency(e.volume)}</td>
                    <td data-sort-key="premium" data-sort-value="${e.premium}">${formatCurrency(e.premium)}</td>
                    <td data-sort-key="apr" data-sort-value="${e.avg_apr || 0}">${formatPercentage(e.avg_apr)}</td>
                    <td>${pxDisplay}</td>
                    <td>${expired ? (e.assigned || 0) : ''}</td>
                    <td>${expired ? (e.returned || 0) : ''}</td>
                </tr>`;
            }).join('')}</tbody>
        </table>`;
    setupSortableTable('detail-expiry-table');
}

function renderDetailVolumeChart(vol) {
    Plotly.newPlot('detail-volume-chart', [
        { x: vol.data.map(d => d.date), y: vol.data.map(d => d.volume), type: 'bar', name: 'Notional', marker: { color: 'rgba(74, 222, 128, 0.6)' } },
        { x: vol.data.map(d => d.date), y: vol.data.map(d => d.premium), type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#fb923c', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
    ], {
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'Inter, sans-serif', color: '#a1a1aa', size: 12 },
        margin: { l: 60, r: 60, t: 20, b: 40 },
        xaxis: { gridcolor: '#27272a', tickfont: { size: 11 } },
        yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickfont: { size: 11 }, tickprefix: '$' },
        yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#fb923c' }, tickprefix: '$' },
        legend: { orientation: 'h', y: -0.15, font: { size: 11 } }, bargap: 0.15,
    }, { responsive: true, displayModeBar: false });
}

function renderDetailTrades(data, symbol) {
    document.getElementById('detail-trades-content').innerHTML = `
        <table class="data-table" id="detail-trades-table"><thead><tr>
            <th data-sort-key="created">Date</th><th>Type</th><th data-sort-key="strike">Strike</th>
            <th data-sort-key="quantity">Qty</th><th data-sort-key="premium">Premium</th>
            <th data-sort-key="notional">Notional</th><th data-sort-key="apr">APR</th><th>Expiry</th>
        </tr></thead><tbody>${data.trades.map(t => `<tr>
            <td data-sort-key="created" data-sort-value="${t.created_at}">${formatUnixDateTime(t.created_at)}</td>
            <td>${t.type}</td>
            <td data-sort-key="strike" data-sort-value="${t.strike}">${formatCurrency(t.strike, 0)}</td>
            <td data-sort-key="quantity" data-sort-value="${t.quantity}">${formatNumber(t.quantity, 4)}</td>
            <td data-sort-key="premium" data-sort-value="${t.premium}">${formatCurrency(t.premium)}</td>
            <td data-sort-key="notional" data-sort-value="${t.notional}">${formatCurrency(t.notional, 0)}</td>
            <td data-sort-key="apr" data-sort-value="${t.apr || 0}">${formatPercentage(t.apr)}</td>
            <td>${formatUnixDate(t.expiry)}</td>
        </tr>`).join('')}</tbody></table>`;
    const pager = document.getElementById('detail-trades-pager');
    pager.innerHTML = `
        <button class="pager-btn" onclick="loadDetailTrades('${symbol}', ${data.page - 1})" ${data.page <= 1 ? 'disabled' : ''}>Prev</button>
        <span class="pager-info">Page ${data.page} of ${data.pages} (${formatNumber(data.total, 0)})</span>
        <button class="pager-btn" onclick="loadDetailTrades('${symbol}', ${data.page + 1})" ${data.page >= data.pages ? 'disabled' : ''}>Next</button>`;
    setupSortableTable('detail-trades-table');
}

async function loadDetailTrades(symbol, page) {
    const resp = await fetch(`/api/global/trades?symbol=${encodeURIComponent(symbol)}&limit=${DETAIL_TRADES_PER_PAGE}&page=${page}`);
    const data = await resp.json();
    if (data.success) renderDetailTrades(data, symbol);
}

function closeAssetDetail() {
    document.getElementById('asset-detail').style.display = 'none';
    document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('selected'));
    selectedAsset = null;
}

// ── Outcomes ──

async function loadOutcomes() {
    const loading = document.getElementById('outcomes-loading');
    const content = document.getElementById('outcomes-content');
    try {
        const resp = await fetch('/api/global/outcomes');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);
        const t = data.totals;

        const unknownCard = t.unknown > 0
            ? `<div class="summary-card"><div class="summary-label">Unknown</div><div class="summary-value">${formatNumber(t.unknown, 0)}</div></div>`
            : '';
        document.getElementById('outcomes-summary').innerHTML = `
            <div class="summary-card"><div class="summary-label">Expired Trades</div><div class="summary-value">${formatNumber(t.total, 0)}</div></div>
            <div class="summary-card"><div class="summary-label">Returned</div><div class="summary-value" style="color: var(--accent);">${formatNumber(t.returned, 0)}</div><div class="summary-subtext">${t.returned_pct}%</div></div>
            <div class="summary-card"><div class="summary-label">Assigned</div><div class="summary-value" style="color: var(--color-error);">${formatNumber(t.assigned, 0)}</div><div class="summary-subtext">${t.assigned_pct}%</div></div>
            ${unknownCard}
            <div class="summary-card"><div class="summary-label">Expired Premium</div><div class="summary-value">${compactCurrency(t.total_premium)}</div></div>
            <div class="summary-card"><div class="summary-label">Premium Kept</div><div class="summary-value" style="color: var(--accent);">${compactCurrency(t.returned_premium)}</div></div>
        `;

        document.getElementById('outcomes-asset-grid').innerHTML = data.by_asset.map(a => {
            const base = shortSymbol(a.symbol);
            return `
                <div class="asset-card">
                    <div class="asset-card-header">
                        <span class="asset-symbol"><span class="token-badge ${base.toLowerCase()}">${base}</span></span>
                        <span class="asset-count">${a.total} expired</span>
                    </div>
                    <div class="asset-card-metrics">
                        <div class="asset-metric"><span class="asset-metric-label">Returned</span><span class="asset-metric-value" style="color: var(--accent);">${a.returned} (${(100 - a.assigned_pct).toFixed(0)}%)</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Assigned</span><span class="asset-metric-value" style="color: var(--color-error);">${a.assigned} (${a.assigned_pct}%)</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Premium</span><span class="asset-metric-value">${compactCurrency(a.total_premium)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Notional</span><span class="asset-metric-value">${compactCurrency(a.total_notional)}</span></div>
                    </div>
                </div>`;
        }).join('');

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load outcomes: ' + e.message;
    }
}

// ── Recent Activity (top 10) ──

async function loadRecent() {
    const loading = document.getElementById('recent-loading');
    const content = document.getElementById('recent-content');
    try {
        const resp = await fetch('/api/global/trades?limit=10');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        document.getElementById('recent-body').innerHTML = data.trades.map(t => `<tr>
            <td>${formatUnixDateTime(t.created_at)}</td>
            <td><span class="token-badge ${shortSymbol(t.symbol).toLowerCase()}">${shortSymbol(t.symbol)}</span></td>
            <td>${t.type}</td>
            <td>${formatCurrency(t.strike, 0)}</td>
            <td>${formatCurrency(t.premium)}</td>
            <td>${formatCurrency(t.notional, 0)}</td>
            <td>${formatPercentage(t.apr)}</td>
        </tr>`).join('');

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load recent trades: ' + e.message;
    }
}

// ── Trade History (paginated) ──

async function loadHistory(page = 1) {
    const loading = document.getElementById('history-loading');
    const content = document.getElementById('history-content');
    currentHistoryPage = page;
    const symbol = document.getElementById('history-symbol').value || '';

    try {
        const params = new URLSearchParams({ page, limit: HISTORY_PER_PAGE });
        if (symbol) params.set('symbol', symbol);
        const resp = await fetch('/api/global/trades?' + params);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const now = Date.now() / 1000;
        document.getElementById('history-body').innerHTML = data.trades.map(t => {
            const expired = t.expiry && t.expiry < now;
            let outcomeHtml;
            if (t.outcome === 'Assigned') outcomeHtml = '<span style="color: var(--color-error);">Assigned</span>';
            else if (t.outcome === 'Returned') outcomeHtml = '<span style="color: var(--accent);">Returned</span>';
            else if (t.outcome) outcomeHtml = t.outcome;
            else if (!expired) outcomeHtml = '<span style="color: var(--text-muted);">Active</span>';
            else outcomeHtml = '—';
            return `<tr>
            <td data-sort-key="created" data-sort-value="${t.created_at}">${formatUnixDateTime(t.created_at)}</td>
            <td data-sort-key="symbol" data-sort-value="${t.symbol}"><span class="token-badge ${shortSymbol(t.symbol).toLowerCase()}">${shortSymbol(t.symbol)}</span></td>
            <td>${t.type}</td>
            <td data-sort-key="strike" data-sort-value="${t.strike}">${formatCurrency(t.strike, 0)}</td>
            <td data-sort-key="premium" data-sort-value="${t.premium}">${formatCurrency(t.premium)}</td>
            <td data-sort-key="notional" data-sort-value="${t.notional}">${formatCurrency(t.notional, 0)}</td>
            <td data-sort-key="apr" data-sort-value="${t.apr || 0}">${formatPercentage(t.apr)}</td>
            <td>${formatUnixDate(t.expiry)}</td>
            <td>${outcomeHtml}</td>
        </tr>`;
        }).join('');

        const pager = document.getElementById('history-pager');
        pager.innerHTML = `
            <button class="pager-btn" onclick="loadHistory(${page - 1})" ${page <= 1 ? 'disabled' : ''}>Prev</button>
            <span class="pager-info">Page ${page} of ${data.pages} (${formatNumber(data.total, 0)} trades)</span>
            <button class="pager-btn" onclick="loadHistory(${page + 1})" ${page >= data.pages ? 'disabled' : ''}>Next</button>`;

        loading.style.display = 'none';
        content.style.display = 'block';
        setupSortableTable('history-table');
    } catch (e) {
        loading.textContent = 'Failed to load trades: ' + e.message;
    }
}

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
    loadSummary();
    loadInventory();
    loadVolumeChart();
    loadAssets();
    loadOutcomes();
    loadRecent();
    loadHistory();

    document.getElementById('volume-days').addEventListener('change', loadVolumeChart);
    document.getElementById('volume-symbol').addEventListener('change', loadVolumeChart);
    document.getElementById('history-symbol').addEventListener('change', () => loadHistory(1));
    document.getElementById('detail-close').addEventListener('click', closeAssetDetail);

    // Carousel arrows
    function wireCarousel(trackId, leftId, rightId) {
        const t = document.getElementById(trackId);
        document.getElementById(leftId).addEventListener('click', () => t.scrollBy({ left: -240, behavior: 'smooth' }));
        document.getElementById(rightId).addEventListener('click', () => t.scrollBy({ left: 240, behavior: 'smooth' }));
    }
    wireCarousel('asset-grid', 'asset-carousel-left', 'asset-carousel-right');
    wireCarousel('outcomes-asset-grid', 'outcomes-carousel-left', 'outcomes-carousel-right');
});
