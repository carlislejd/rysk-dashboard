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

// ── Protocol Overview (summary + volume chart, driven by time tabs) ──

let overviewDays = 0; // 0 = all time
let historyDropdownPopulated = false;

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
                <div class="summary-label">Trades</div>
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

        // Populate history filter dropdown once
        if (!historyDropdownPopulated && data.assets) {
            const historySel = document.getElementById('history-symbol');
            if (historySel) {
                data.assets.forEach(asset => {
                    const opt = document.createElement('option');
                    opt.value = asset;
                    opt.textContent = shortSymbol(asset);
                    historySel.appendChild(opt);
                });
                historyDropdownPopulated = true;
            }
        }

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
            xaxis: { gridcolor: '#27272a', tickfont: { size: 11 } },
            yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#fb923c' }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.15, font: { size: 11 } },
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
        xaxis: { title: 'Strike', gridcolor: '#27272a', tickfont: { size: 10 }, tickangle: -45 },
        yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickprefix: '$' },
        legend: { orientation: 'h', y: -0.25, font: { size: 11 } }, bargap: 0.15,
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
        xaxis: { gridcolor: '#27272a', tickfont: { size: 11 } },
        yaxis: { title: 'Notional ($)', gridcolor: '#27272a', tickfont: { size: 11 }, tickprefix: '$' },
        yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#fb923c' }, tickprefix: '$' },
        legend: { orientation: 'h', y: -0.15, font: { size: 11 } }, bargap: 0.15,
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
            <td>${formatStrike(t.strike)}</td>
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
            <td data-sort-key="strike" data-sort-value="${t.strike}">${formatStrike(t.strike)}</td>
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
    loadOverview(0);
    loadInventory();
    loadAssets();
    loadOutcomes();
    loadRecent();
    loadHistory();

    // Overview time period tabs
    document.getElementById('overview-tabs').addEventListener('click', e => {
        const btn = e.target.closest('.tab-button');
        if (!btn) return;
        loadOverview(parseInt(btn.dataset.overviewDays));
    });

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
    wireCarousel('detail-expiry-tabs', 'expiry-carousel-left', 'expiry-carousel-right');
});
