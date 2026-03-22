// Global Dashboard JavaScript — Asset-focused with Inventory & Outcomes

let selectedAsset = null;
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

// ── Protocol Overview (summary + volume chart, driven by time tabs) ──

let overviewDays = 0; // 0 = all time
async function loadOverview(days) {
    overviewDays = days;
    const loading = document.getElementById('summary-loading');
    const content = document.getElementById('summary-content');

    // Update active tab
    document.querySelectorAll('#overview-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.overviewDays) === days);
    });

    // Fetch summary + volume in parallel
    const summaryParams = days > 0 ? `?days=${days}` : '';
    const volumeDays = days > 0 ? days : 365;
    const [summaryResp, volumeResp] = await Promise.all([
        fetch('/api/global/summary' + summaryParams),
        fetch(`/api/global/volume?days=${volumeDays}`),
    ]);
    const [summaryData, volumeData] = await Promise.all([summaryResp.json(), volumeResp.json()]);

    if (summaryData.success) {
        const data = summaryData;
        const periodLabel = days > 0 ? `${days}d` : 'All Time';
        document.getElementById('summary-grid').innerHTML = `
            <div class="summary-card">
                <div class="summary-label">Orders</div>
                <div class="summary-value">${formatNumber(data.total_trades, 0)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Notional</div>
                <div class="summary-value">${compactCurrency(data.total_volume)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Premium</div>
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

        loading.style.display = 'none';
        content.style.display = 'block';
    }

    if (volumeData.success) {
        const dates = volumeData.data.map(d => d.date);
        const volumes = volumeData.data.map(d => d.volume);
        const premiums = volumeData.data.map(d => d.premium);

        Plotly.newPlot('volume-chart', [
            { x: dates, y: volumes, type: 'bar', name: 'Notional', marker: { color: 'rgba(74, 222, 128, 0.6)' } },
            { x: dates, y: premiums, type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#fb923c', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
        ], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter, sans-serif', color: '#a1a1aa', size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#fb923c' }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
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
            const indexDisplay = a.index != null ? formatStrike(a.index) : '—';
            const renderRows = (options) => options.map(o => {
                const strikeDisplay = formatStrike(o.strike);
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
            const expiredTotal = a.expired_count || 0;
            const returnedPct = expiredTotal > 0 ? ((a.returned / expiredTotal) * 100).toFixed(0) : '—';
            return `
                <div class="asset-card" data-asset="${a.symbol}" onclick="showAssetDetail('${a.symbol}')">
                    <div class="asset-card-header">
                        <span class="asset-symbol"><span class="token-badge ${base.toLowerCase()}">${base}</span></span>
                        <span class="asset-count">${formatNumber(a.trade_count, 0)} orders</span>
                    </div>
                    <div class="asset-card-metrics">
                        <div class="asset-metric"><span class="asset-metric-label">Notional</span><span class="asset-metric-value">${compactCurrency(a.total_volume)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Premium</span><span class="asset-metric-value">${compactCurrency(a.total_premium)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Avg APR</span><span class="asset-metric-value asset-summary-apr">${formatPercentage(a.avg_apr)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Put / Call</span><span class="asset-metric-value">${putPct}% / ${callPct}%</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Active</span><span class="asset-metric-value">${formatNumber(a.active_count, 0)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Expired</span><span class="asset-metric-value">${formatNumber(expiredTotal, 0)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Returned</span><span class="asset-metric-value" style="color: var(--accent);">${returnedPct}%</span></div>
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

let detailExpiries = []; // cached expiry list for the current asset
let selectedExpiry = null; // null = All

async function showAssetDetail(symbol) {
    selectedAsset = symbol;
    selectedExpiry = null;
    const panel = document.getElementById('asset-detail');
    const base = shortSymbol(symbol);

    document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('selected'));
    const card = document.querySelector(`.asset-card[data-asset="${symbol}"]`);
    if (card) card.classList.add('selected');

    document.getElementById('detail-asset-name').textContent = `${symbol}`;
    panel.style.display = 'block';
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // First fetch detail to get expiry list, then load the rest
    const detailResp = await fetch(`/api/global/asset/${encodeURIComponent(symbol)}`);
    const detail = await detailResp.json();

    if (detail.success) {
        detailExpiries = detail.expiries || [];
        renderExpiryTabs(symbol);
        renderDetailSummary(detail);
        renderExpiryBreakdown(detail);
    }

    // Load volume + trades in parallel (unfiltered initially)
    loadDetailData(symbol, null);
}

function renderExpiryTabs(symbol) {
    const tabs = document.getElementById('detail-expiry-tabs');
    const sorted = [...detailExpiries].sort((a, b) => b.expiry - a.expiry);
    tabs.innerHTML = `<button class="tab-button active" data-detail-expiry="all">All</button>` +
        sorted.map(e =>
            `<button class="tab-button" data-detail-expiry="${e.expiry}">${formatUnixDate(e.expiry)}</button>`
        ).join('');

    tabs.onclick = async (ev) => {
        const btn = ev.target.closest('.tab-button');
        if (!btn) return;
        tabs.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const val = btn.dataset.detailExpiry;
        selectedExpiry = val === 'all' ? null : parseInt(val);

        // Re-fetch detail (filtered strikes) + volume + trades
        const expiryParam = selectedExpiry ? `&expiry=${selectedExpiry}` : '';
        const detailResp = await fetch(`/api/global/asset/${encodeURIComponent(symbol)}?${selectedExpiry ? 'expiry=' + selectedExpiry : ''}`);
        const detail = await detailResp.json();

        if (detail.success) {
            renderDetailSummary(detail);
            // Show expiry breakdown only for All, hide for single expiry
            if (selectedExpiry) {
                document.getElementById('detail-expiry-content').style.display = 'none';
            } else {
                document.getElementById('detail-expiry-content').style.display = '';
                renderExpiryBreakdown(detail);
            }
        }
        loadDetailData(symbol, selectedExpiry);
    };
}

async function loadDetailData(symbol, expiry) {
    const sym = encodeURIComponent(symbol);
    const expiryParam = expiry ? `&expiry=${expiry}` : '';
    const [volResp, tradesResp] = await Promise.all([
        fetch(`/api/global/volume?symbol=${sym}&days=365${expiryParam}`),
        fetch(`/api/global/trades?symbol=${sym}&limit=${DETAIL_TRADES_PER_PAGE}&page=1${expiryParam}`),
    ]);
    const [vol, trades] = await Promise.all([volResp.json(), tradesResp.json()]);
    if (vol.success) renderDetailVolumeChart(vol);

    // Also re-fetch strike chart with expiry filter
    const detailResp = await fetch(`/api/global/asset/${encodeURIComponent(symbol)}${expiry ? '?expiry=' + expiry : ''}`);
    const detail = await detailResp.json();
    if (detail.success) renderStrikeChart(detail);

    if (trades.success) renderDetailTrades(trades, symbol, expiry);
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

    // Outcome totals from expiry data (use filtered or all)
    const expirySource = selectedExpiry ? expiries.filter(e => e.expiry === selectedExpiry) : expiries;
    const totalAssigned = expirySource.reduce((s, e) => s + (e.assigned || 0), 0);
    const totalReturned = expirySource.reduce((s, e) => s + (e.returned || 0), 0);
    const outcomeTotal = totalAssigned + totalReturned;
    const assignedPct = outcomeTotal > 0 ? (totalAssigned / outcomeTotal * 100).toFixed(1) : '—';

    document.getElementById('detail-summary').innerHTML = `
        <div class="summary-card"><div class="summary-label">Trades</div><div class="summary-value">${formatNumber(totalTrades, 0)}</div></div>
        <div class="summary-card"><div class="summary-label">Notional</div><div class="summary-value">${compactCurrency(totalVol)}</div></div>
        <div class="summary-card"><div class="summary-label">Premium</div><div class="summary-value">${compactCurrency(totalPrem)}</div></div>
        <div class="summary-card"><div class="summary-label">Avg APR</div><div class="summary-value">${formatPercentage(avgApr)}</div></div>
        <div class="summary-card"><div class="summary-label">Put / Call</div><div class="summary-value">${compactCurrency(totalPutVol)} / ${compactCurrency(totalCallVol)}</div></div>
        <div class="summary-card"><div class="summary-label">Assignment Rate</div><div class="summary-value">${assignedPct}%</div><div class="summary-subtext">${totalAssigned} assigned / ${totalReturned} returned</div></div>
    `;
}

function renderStrikeChart(detail) {
    const strikes = detail.strikes || [];
    if (!strikes.length) { document.getElementById('detail-strike-chart').innerHTML = '<div class="loading">No strike data</div>'; return; }
    Plotly.newPlot('detail-strike-chart', [
        { x: strikes.map(s => formatStrike(s.strike)), y: strikes.map(s => s.put_volume), type: 'bar', name: 'Put', marker: { color: 'rgba(248, 113, 113, 0.7)' } },
        { x: strikes.map(s => formatStrike(s.strike)), y: strikes.map(s => s.call_volume), type: 'bar', name: 'Call', marker: { color: 'rgba(34, 211, 238, 0.7)' } },
    ], {
        barmode: 'stack', paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'Inter, sans-serif', color: '#a1a1aa', size: 12 },
        margin: { l: 60, r: 20, t: 20, b: 60 },
        xaxis: { title: 'Strike', showgrid: false, tickfont: { size: 10 }, tickangle: -45 },
        yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickprefix: '$' },
        legend: { orientation: 'h', y: -0.12, font: { size: 11 } }, bargap: 0.15,
    }, { responsive: true, displayModeBar: false });
}

function renderExpiryBreakdown(detail) {
    const expiries = detail.expiries || [];
    if (!expiries.length) { document.getElementById('detail-expiry-content').innerHTML = '<div class="loading">No expiry data</div>'; return; }
    const now = Date.now() / 1000;
    document.getElementById('detail-expiry-content').style.display = '';
    document.getElementById('detail-expiry-content').innerHTML = `
        <h3 class="subsection-title">Expiry Breakdown</h3>
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
        xaxis: { showgrid: false, tickfont: { size: 11 } },
        yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickfont: { size: 11 }, tickprefix: '$' },
        yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#fb923c' }, tickprefix: '$' },
        legend: { orientation: 'h', y: -0.08, font: { size: 11 } }, bargap: 0.15,
    }, { responsive: true, displayModeBar: false });
}

function renderDetailTrades(data, symbol, expiry) {
    const now = Date.now() / 1000;
    document.getElementById('detail-trades-content').innerHTML = `
        <table class="data-table" id="detail-trades-table"><thead><tr>
            <th data-sort-key="created">Date</th><th>Type</th><th data-sort-key="strike">Strike</th>
            <th data-sort-key="quantity">Qty</th><th data-sort-key="premium">Premium</th>
            <th data-sort-key="notional">Notional</th><th data-sort-key="apr">APR</th>
            <th>Expiry</th><th>Outcome</th>
        </tr></thead><tbody>${data.trades.map(t => {
            const expired = t.expiry && t.expiry < now;
            let outcomeHtml;
            if (t.outcome === 'Assigned') outcomeHtml = '<span style="color: var(--color-error);">Assigned</span>';
            else if (t.outcome === 'Returned') outcomeHtml = '<span style="color: var(--accent);">Returned</span>';
            else if (t.outcome) outcomeHtml = t.outcome;
            else if (!expired) outcomeHtml = '<span style="color: var(--text-muted);">Active</span>';
            else outcomeHtml = '—';
            return `<tr>
            <td data-sort-key="created" data-sort-value="${t.created_at}">${formatUnixDateTime(t.created_at)}</td>
            <td>${t.type}</td>
            <td data-sort-key="strike" data-sort-value="${t.strike}">${formatStrike(t.strike)}</td>
            <td data-sort-key="quantity" data-sort-value="${t.quantity}">${formatNumber(t.quantity, 4)}</td>
            <td data-sort-key="premium" data-sort-value="${t.premium}">${formatCurrency(t.premium)}</td>
            <td data-sort-key="notional" data-sort-value="${t.notional}">${formatCurrency(t.notional, 0)}</td>
            <td data-sort-key="apr" data-sort-value="${t.apr || 0}">${formatPercentage(t.apr)}</td>
            <td>${formatUnixDate(t.expiry)}</td>
            <td>${outcomeHtml}</td>
        </tr>`;
        }).join('')}</tbody></table>`;
    const expiryParam = expiry ? `&expiry=${expiry}` : '';
    const pager = document.getElementById('detail-trades-pager');
    pager.innerHTML = `
        <button class="pager-btn" onclick="loadDetailTrades('${symbol}', ${data.page - 1}, ${expiry || 'null'})" ${data.page <= 1 ? 'disabled' : ''}>Prev</button>
        <span class="pager-info">Page ${data.page} of ${data.pages} (${formatNumber(data.total, 0)})</span>
        <button class="pager-btn" onclick="loadDetailTrades('${symbol}', ${data.page + 1}, ${expiry || 'null'})" ${data.page >= data.pages ? 'disabled' : ''}>Next</button>`;
    setupSortableTable('detail-trades-table');
}

async function loadDetailTrades(symbol, page, expiry) {
    const expiryParam = expiry ? `&expiry=${expiry}` : '';
    const resp = await fetch(`/api/global/trades?symbol=${encodeURIComponent(symbol)}&limit=${DETAIL_TRADES_PER_PAGE}&page=${page}${expiryParam}`);
    const data = await resp.json();
    if (data.success) renderDetailTrades(data, symbol, expiry);
}

function closeAssetDetail() {
    document.getElementById('asset-detail').style.display = 'none';
    document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('selected'));
    selectedAsset = null;
    selectedExpiry = null;
}

// ── Expiry Explorer ──

let expiryData = [];
let selectedExplorerExpiry = null; // null = All

async function loadExpiryExplorer() {
    const loading = document.getElementById('expiry-loading');
    const content = document.getElementById('expiry-content');
    try {
        const resp = await fetch('/api/global/expiries');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);
        expiryData = data.expiries;

        // Build tabs — All + each expiry date (most recent first, already sorted)
        const tabs = document.getElementById('expiry-explorer-tabs');
        tabs.innerHTML = `<button class="tab-button active" data-exp-tab="all">All</button>` +
            expiryData.map(e =>
                `<button class="tab-button" data-exp-tab="${e.expiry}">${formatUnixDate(e.expiry)}${e.expired ? '' : ' *'}</button>`
            ).join('');

        tabs.onclick = (ev) => {
            const btn = ev.target.closest('.tab-button');
            if (!btn) return;
            tabs.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const val = btn.dataset.expTab;
            selectedExplorerExpiry = val === 'all' ? null : parseInt(val);
            renderExpiryExplorer();
        };

        renderExpiryExplorer();
        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load expiries: ' + e.message;
    }
}

function renderExpiryExplorer() {
    const selected = selectedExplorerExpiry;
    const filtered = selected ? expiryData.filter(e => e.expiry === selected) : expiryData;

    // Aggregate stats across filtered expiries
    const totalOrders = filtered.reduce((s, e) => s + e.total_orders, 0);
    const totalNotional = filtered.reduce((s, e) => s + e.total_notional, 0);
    const totalPremium = filtered.reduce((s, e) => s + e.total_premium, 0);
    const totalAssigned = filtered.reduce((s, e) => s + e.assigned, 0);
    const totalReturned = filtered.reduce((s, e) => s + e.returned, 0);
    const outcomeTotal = totalAssigned + totalReturned;
    const returnRate = outcomeTotal > 0 ? (totalReturned / outcomeTotal * 100).toFixed(1) : '—';
    const premiumYield = totalNotional > 0 ? (totalPremium / totalNotional * 100).toFixed(2) : '—';
    const avgDte = filtered.length > 0
        ? (filtered.reduce((s, e) => s + e.avg_dte_days * e.total_orders, 0) / totalOrders).toFixed(1)
        : '—';
    const allAssets = [...new Set(filtered.flatMap(e => e.assets))];
    const putCount = filtered.reduce((s, e) => s + e.put_count, 0);
    const callCount = filtered.reduce((s, e) => s + e.call_count, 0);
    const putPct = totalOrders > 0 ? ((putCount / totalOrders) * 100).toFixed(0) : 0;

    // For single expiry, show richer detail
    const single = selected ? filtered[0] : null;

    document.getElementById('expiry-summary').innerHTML = `
        <div class="summary-card"><div class="summary-label">Orders</div><div class="summary-value">${formatNumber(totalOrders, 0)}</div>${!selected ? `<div class="summary-subtext">${filtered.length} expiry dates</div>` : ''}</div>
        <div class="summary-card"><div class="summary-label">Notional</div><div class="summary-value">${compactCurrency(totalNotional)}</div></div>
        <div class="summary-card"><div class="summary-label">Premium</div><div class="summary-value">${compactCurrency(totalPremium)}</div><div class="summary-subtext">${premiumYield}% yield</div></div>
        <div class="summary-card"><div class="summary-label">Avg DTE</div><div class="summary-value">${avgDte}d</div></div>
        <div class="summary-card"><div class="summary-label">Put / Call</div><div class="summary-value">${putPct}% / ${100 - putPct}%</div></div>
        ${outcomeTotal > 0
            ? `<div class="summary-card"><div class="summary-label">Returned</div><div class="summary-value" style="color: var(--accent);">${returnRate}%</div><div class="summary-subtext">${totalReturned} of ${outcomeTotal}</div></div>`
            : `<div class="summary-card"><div class="summary-label">Status</div><div class="summary-value" style="color: var(--text-muted);">Active</div></div>`
        }
    `;

    // Detail content
    const detail = document.getElementById('expiry-detail-content');
    if (single) {
        // Single expiry — show assets breakdown, settlement prices
        detail.innerHTML = `
            <div style="display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 16px;">
                <div style="flex: 1; min-width: 200px;">
                    <div class="subsection-title">Assets Traded</div>
                    <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;">
                        ${single.assets.map(a => `<span class="token-badge ${shortSymbol(a).toLowerCase()}">${shortSymbol(a)}</span>`).join('')}
                    </div>
                </div>
                <div style="flex: 1; min-width: 200px;">
                    <div class="subsection-title">Top Stats</div>
                    <div class="asset-card-metrics" style="margin-top: 8px;">
                        <div class="asset-metric"><span class="asset-metric-label">Most Traded</span><span class="asset-metric-value">${single.top_asset || '—'}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Largest Premium</span><span class="asset-metric-value">${formatCurrency(single.max_single_premium)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Largest Notional</span><span class="asset-metric-value">${compactCurrency(single.max_single_notional)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Avg APR</span><span class="asset-metric-value asset-summary-apr">${formatPercentage(single.avg_apr)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Put Notional</span><span class="asset-metric-value">${compactCurrency(single.put_notional)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Call Notional</span><span class="asset-metric-value">${compactCurrency(single.call_notional)}</span></div>
                    </div>
                </div>
            </div>
        `;
    } else {
        // All view — show per-expiry table
        detail.innerHTML = `
            <table class="data-table" id="expiry-overview-table">
                <thead><tr>
                    <th data-sort-key="expiry">Expiry</th>
                    <th data-sort-key="orders">Orders</th>
                    <th>Assets</th>
                    <th data-sort-key="notional">Notional</th>
                    <th data-sort-key="premium">Premium</th>
                    <th>Yield</th>
                    <th>DTE</th>
                    <th>Put/Call</th>
                    <th>Returned</th>
                </tr></thead>
                <tbody>${expiryData.map(e => {
                    const rr = (e.assigned + e.returned) > 0
                        ? `<span style="color: var(--accent);">${e.return_rate}%</span>`
                        : (e.expired ? '—' : '<span style="color: var(--text-muted);">Active</span>');
                    const pc = e.total_orders > 0 ? `${((e.put_count / e.total_orders) * 100).toFixed(0)}/${((e.call_count / e.total_orders) * 100).toFixed(0)}` : '—';
                    return `<tr>
                        <td data-sort-key="expiry" data-sort-value="${e.expiry}">${formatUnixDate(e.expiry)}${e.expired ? '' : ' *'}</td>
                        <td data-sort-key="orders" data-sort-value="${e.total_orders}">${e.total_orders}</td>
                        <td>${e.asset_count}</td>
                        <td data-sort-key="notional" data-sort-value="${e.total_notional}">${compactCurrency(e.total_notional)}</td>
                        <td data-sort-key="premium" data-sort-value="${e.total_premium}">${compactCurrency(e.total_premium)}</td>
                        <td>${e.premium_yield}%</td>
                        <td>${e.avg_dte_days}d</td>
                        <td>${pc}</td>
                        <td>${rr}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table>
        `;
        setupSortableTable('expiry-overview-table');
    }
}

// ── Recent Activity (top 10) ──

async function loadRecent() {
    const loading = document.getElementById('recent-loading');
    const content = document.getElementById('recent-content');
    try {
        const resp = await fetch('/api/global/trades?limit=10&iv=true');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        document.getElementById('recent-body').innerHTML = data.trades.map(t => `<tr>
            <td>${formatUnixDateTime(t.created_at)}</td>
            <td><span class="token-badge ${shortSymbol(t.symbol).toLowerCase()}">${shortSymbol(t.symbol)}</span></td>
            <td>${t.type}</td>
            <td>${formatStrike(t.strike)}</td>
            <td>${formatCurrency(t.premium)}</td>
            <td>${formatCurrency(t.notional, 0)}</td>
            <td>${formatPercentage(t.apr)}</td>
            <td>${t.iv != null ? formatPercentage(t.iv, 1) : '—'}</td>
        </tr>`).join('');

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load recent trades: ' + e.message;
    }
}

// ── Trade History (paginated) ──

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
    loadOverview(0);
    loadAssets();
    loadExpiryExplorer();
    loadRecent();

    // Overview time period tabs
    document.getElementById('overview-tabs').addEventListener('click', e => {
        const btn = e.target.closest('.tab-button');
        if (!btn) return;
        loadOverview(parseInt(btn.dataset.overviewDays));
    });

    document.getElementById('detail-close').addEventListener('click', closeAssetDetail);

    // Carousel arrows
    function wireCarousel(trackId, leftId, rightId) {
        const t = document.getElementById(trackId);
        const step = 240;

        function initLoop() {
            const items = Array.from(t.children);
            if (items.length < 2) return;

            // Clone a screenful of items at each end
            const cloneCount = Math.min(items.length, Math.ceil(t.clientWidth / step) + 1);
            const tail = items.slice(-cloneCount);
            const head = items.slice(0, cloneCount);
            tail.forEach(el => {
                const clone = el.cloneNode(true);
                clone.setAttribute('data-carousel-clone', 'true');
                t.insertBefore(clone, t.firstChild);
            });
            head.forEach(el => {
                const clone = el.cloneNode(true);
                clone.setAttribute('data-carousel-clone', 'true');
                t.appendChild(clone);
            });

            // Start scrolled to the first real item (after prepended clones)
            const prependWidth = tail.reduce((sum, el) => sum + el.offsetWidth, 0);
            t.scrollLeft = prependWidth;

            // When scroll stops near a clone boundary, teleport to the real items
            let scrollTimer;
            t.addEventListener('scroll', () => {
                clearTimeout(scrollTimer);
                scrollTimer = setTimeout(() => {
                    const maxReal = t.scrollWidth - head.reduce((sum, el) => sum + el.offsetWidth, 0);
                    if (t.scrollLeft <= 2) {
                        t.style.scrollBehavior = 'auto';
                        t.scrollLeft = maxReal - t.clientWidth;
                        t.style.scrollBehavior = '';
                    } else if (t.scrollLeft + t.clientWidth >= t.scrollWidth - 2) {
                        t.style.scrollBehavior = 'auto';
                        t.scrollLeft = prependWidth;
                        t.style.scrollBehavior = '';
                    }
                }, 100);
            });
        }

        // Observe for content changes (cards are loaded async)
        const observer = new MutationObserver(() => {
            // Only init once real (non-clone) items exist
            if (t.children.length > 0 && !t.querySelector('[data-carousel-clone]')) {
                initLoop();
            }
        });
        observer.observe(t, { childList: true });
        if (t.children.length > 0) initLoop();

        document.getElementById(leftId).addEventListener('click', () => {
            t.scrollBy({ left: -step, behavior: 'smooth' });
        });
        document.getElementById(rightId).addEventListener('click', () => {
            t.scrollBy({ left: step, behavior: 'smooth' });
        });
    }
    wireCarousel('asset-grid', 'asset-carousel-left', 'asset-carousel-right');
    wireCarousel('detail-expiry-tabs', 'expiry-carousel-left', 'expiry-carousel-right');
    wireCarousel('expiry-explorer-tabs', 'expiry-explorer-left', 'expiry-explorer-right');
});
