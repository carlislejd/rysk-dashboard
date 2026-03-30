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
            { x: dates, y: volumes, type: 'bar', name: 'Notional', marker: { color: 'rgba(52, 211, 153, 0.6)' } },
            { x: dates, y: premiums, type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#f59e0b', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
        ], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter, system-ui, sans-serif', color: '#71717a', size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Notional ($)', gridcolor: 'rgba(255,255,255,0.06)', tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#f59e0b' }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
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

    const currentPrice = detail.current_price;
    const strikeLabels = strikes.map(s => formatStrike(s.strike));

    // Build shapes + annotations for current price vertical line
    const shapes = [];
    const annotations = [];
    if (currentPrice != null) {
        // Find where current price falls relative to strike labels
        const cpLabel = formatStrike(currentPrice);
        // Use a vertical line at the closest strike index
        let closestIdx = 0;
        let closestDist = Infinity;
        strikes.forEach((s, i) => {
            const d = Math.abs(s.strike - currentPrice);
            if (d < closestDist) { closestDist = d; closestIdx = i; }
        });
        // Interpolate position between strikes for a precise line
        let xPos = closestIdx;
        if (strikes.length > 1) {
            // Find the two strikes that bracket the current price
            for (let i = 0; i < strikes.length - 1; i++) {
                const lo = strikes[i].strike, hi = strikes[i + 1].strike;
                if ((currentPrice >= lo && currentPrice <= hi) || (currentPrice <= lo && currentPrice >= hi)) {
                    const frac = (currentPrice - lo) / (hi - lo);
                    xPos = i + frac;
                    break;
                }
            }
            // If price is below all strikes or above all strikes, clamp
            if (currentPrice <= strikes[0].strike) xPos = -0.3;
            if (currentPrice >= strikes[strikes.length - 1].strike) xPos = strikes.length - 0.7;
        }

        // Count puts ITM (strike > price) and calls ITM (strike < price)
        let putsItm = 0, callsItm = 0, putsItmNotional = 0, callsItmNotional = 0;
        for (const s of strikes) {
            if (s.strike > currentPrice) { putsItm += s.put_volume > 0 ? 1 : 0; putsItmNotional += s.put_volume; }
            if (s.strike < currentPrice) { callsItm += s.call_volume > 0 ? 1 : 0; callsItmNotional += s.call_volume; }
        }
        const totalItmNotional = putsItmNotional + callsItmNotional;

        shapes.push({
            type: 'line', x0: xPos, x1: xPos, y0: 0, y1: 1, yref: 'paper',
            line: { color: 'rgba(244, 244, 245, 0.5)', width: 1.5, dash: 'dot' }
        });
        const itmLabel = totalItmNotional > 0 ? ` · ${compactCurrency(totalItmNotional)} ITM` : '';
        annotations.push({
            x: xPos, y: 1, yref: 'paper', yanchor: 'bottom',
            text: `Price ${cpLabel}${itmLabel}`,
            showarrow: false,
            font: { size: 10, color: '#f4f4f5', family: 'Inter, system-ui, sans-serif' },
            bgcolor: 'rgba(9,9,11,0.8)', borderpad: 4,
        });
    }

    Plotly.newPlot('detail-strike-chart', [
        { x: strikeLabels, y: strikes.map(s => s.put_volume), type: 'bar', name: 'Put', marker: { color: 'rgba(239, 112, 112, 0.7)' } },
        { x: strikeLabels, y: strikes.map(s => s.call_volume), type: 'bar', name: 'Call', marker: { color: 'rgba(56, 189, 248, 0.7)' } },
    ], {
        barmode: 'stack', paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'Inter, system-ui, sans-serif', color: '#71717a', size: 12 },
        margin: { l: 60, r: 20, t: 30, b: 60 },
        xaxis: { title: 'Strike', showgrid: false, tickfont: { size: 10 }, tickangle: -45 },
        yaxis: { title: 'Notional ($)', gridcolor: 'rgba(255,255,255,0.06)', tickprefix: '$' },
        legend: { orientation: 'h', y: -0.12, font: { size: 11 } }, bargap: 0.15,
        shapes, annotations,
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
        { x: vol.data.map(d => d.date), y: vol.data.map(d => d.volume), type: 'bar', name: 'Notional', marker: { color: 'rgba(52, 211, 153, 0.6)' } },
        { x: vol.data.map(d => d.date), y: vol.data.map(d => d.premium), type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#f59e0b', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
    ], {
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'Inter, system-ui, sans-serif', color: '#71717a', size: 12 },
        margin: { l: 60, r: 60, t: 20, b: 40 },
        xaxis: { showgrid: false, tickfont: { size: 11 } },
        yaxis: { title: 'Notional ($)', gridcolor: 'rgba(255,255,255,0.06)', tickfont: { size: 11 }, tickprefix: '$' },
        yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#f59e0b' }, tickprefix: '$' },
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

// ── Market Pulse ──

async function loadMarketPulse() {
    const loading = document.getElementById('pulse-loading');
    const content = document.getElementById('pulse-content');
    try {
        const resp = await fetch('/api/global/market-pulse');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const top = data.top_asset_24h;
        const act = data.activity;
        const dte = data.avg_dte;
        const active = data.active_positions;
        const volIndicator = act.volume_vs_daily_avg !== null
            ? (act.volume_vs_daily_avg > 0 ? `+${act.volume_vs_daily_avg}%` : `${act.volume_vs_daily_avg}%`)
            : '—';
        const volColor = act.volume_vs_daily_avg > 0 ? 'var(--accent)' : (act.volume_vs_daily_avg < 0 ? 'var(--color-error)' : 'var(--text-muted)');

        document.getElementById('pulse-grid').innerHTML = `
            <div class="summary-card">
                <div class="summary-label">Hottest Asset (24h)</div>
                <div class="summary-value">${top ? `<span class="token-badge ${shortSymbol(top.symbol).toLowerCase()}">${shortSymbol(top.symbol)}</span>` : '—'}</div>
                <div class="summary-subtext">${top ? `${top.trades} trades · ${compactCurrency(top.volume)}` : 'No activity'}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">24h Volume</div>
                <div class="summary-value">${compactCurrency(act.volume_24h)}</div>
                <div class="summary-subtext" style="color: ${volColor};">${volIndicator} vs 7d avg</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">24h Premium</div>
                <div class="summary-value">${compactCurrency(act.premium_24h)}</div>
                <div class="summary-subtext">${act.trades_24h} trades</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Avg DTE (7d)</div>
                <div class="summary-value">${dte.avg || '—'}d</div>
                <div class="summary-subtext">${dte.min || '—'}d — ${dte.max || '—'}d range</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Active Positions</div>
                <div class="summary-value">${formatNumber(active.count, 0)}</div>
                <div class="summary-subtext">${compactCurrency(active.notional)} notional</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">7d Volume</div>
                <div class="summary-value">${compactCurrency(act.volume_7d)}</div>
                <div class="summary-subtext">${act.trades_7d} trades</div>
            </div>
        `;

        // Popular strikes
        if (data.popular_strikes && data.popular_strikes.length) {
            document.getElementById('pulse-strikes').innerHTML = `
                <h3 class="subsection-title">Trending Strikes (7d)</h3>
                <table class="data-table">
                    <thead><tr><th>Asset</th><th>Strike</th><th>Trades</th><th>Notional</th></tr></thead>
                    <tbody>${data.popular_strikes.map(s => `<tr>
                        <td><span class="token-badge ${shortSymbol(s.symbol).toLowerCase()}">${shortSymbol(s.symbol)}</span></td>
                        <td>${formatStrike(s.strike)}</td>
                        <td>${s.count}</td>
                        <td>${compactCurrency(s.volume)}</td>
                    </tr>`).join('')}</tbody>
                </table>
            `;
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load market pulse: ' + e.message;
    }
}

// ── Premium PnL Chart ──

let pnlDays = 90;
async function loadPnlChart(days) {
    pnlDays = days;
    const loading = document.getElementById('pnl-loading');
    const chart = document.getElementById('pnl-chart');

    document.querySelectorAll('#pnl-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.pnlDays) === days);
    });

    try {
        const resp = await fetch(`/api/global/premium-over-time?days=${days}`);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const dates = data.data.map(d => d.date);
        const cumPremium = data.data.map(d => d.cumulative_premium);
        const cumReturned = data.data.map(d => d.cumulative_returned_premium);
        const dailyPremium = data.data.map(d => d.daily_premium);

        loading.style.display = 'none';
        chart.style.display = 'block';

        Plotly.newPlot('pnl-chart', [
            { x: dates, y: dailyPremium, type: 'bar', name: 'Daily Premium', marker: { color: 'rgba(52, 211, 153, 0.3)' }, yaxis: 'y2' },
            { x: dates, y: cumPremium, type: 'scatter', mode: 'lines', name: 'Cumulative Premium', line: { color: '#34d399', width: 2.5 } },
            { x: dates, y: cumReturned, type: 'scatter', mode: 'lines', name: 'Returned Position Premium', line: { color: '#f59e0b', width: 2, dash: 'dot' } },
        ], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter, system-ui, sans-serif', color: '#71717a', size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Cumulative ($)', gridcolor: 'rgba(255,255,255,0.06)', tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Daily ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11 }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
    } catch (e) {
        loading.textContent = 'Failed to load PnL: ' + e.message;
    }
}

// ── Put/Call Ratio Trend ──

let pcrDays = 90;
async function loadPutCallRatio(days) {
    pcrDays = days;
    const loading = document.getElementById('pcr-loading');
    const chart = document.getElementById('pcr-chart');

    document.querySelectorAll('#pcr-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.pcrDays) === days);
    });

    try {
        const resp = await fetch(`/api/global/put-call-ratio?days=${days}`);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const weeks = data.data.map(d => d.week);
        const putPcts = data.data.map(d => d.put_pct);
        const callPcts = data.data.map(d => 100 - d.put_pct);
        const ratios = data.data.map(d => d.ratio);

        loading.style.display = 'none';
        chart.style.display = 'block';

        Plotly.newPlot('pcr-chart', [
            { x: weeks, y: putPcts, type: 'bar', name: 'Put Volume', marker: { color: 'rgba(239, 112, 112, 0.6)' } },
            { x: weeks, y: callPcts, type: 'bar', name: 'Call Volume', marker: { color: 'rgba(56, 189, 248, 0.6)' } },
            { x: weeks, y: ratios, type: 'scatter', mode: 'lines+markers', name: 'P/C Ratio', line: { color: '#f0b940', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
        ], {
            barmode: 'stack',
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter, system-ui, sans-serif', color: '#71717a', size: 12 },
            margin: { l: 50, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Notional Share (%)', gridcolor: 'rgba(255,255,255,0.06)', tickfont: { size: 11 }, ticksuffix: '%', range: [0, 100] },
            yaxis2: { title: 'P/C Ratio', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#f0b940' } },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
    } catch (e) {
        loading.textContent = 'Failed to load put/call ratio: ' + e.message;
    }
}

// ── Assignment Rate Trend ──

// ── Outcomes Breakdown ──

async function loadOutcomes() {
    const loading = document.getElementById('outcomes-loading');
    const content = document.getElementById('outcomes-content');
    try {
        const resp = await fetch('/api/global/outcomes');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const t = data.totals;
        document.getElementById('outcomes-summary').innerHTML = `
            <div class="summary-card"><div class="summary-label">Expired Trades</div><div class="summary-value">${formatNumber(t.total, 0)}</div></div>
            <div class="summary-card"><div class="summary-label">Assigned</div><div class="summary-value" style="color: var(--color-error);">${formatNumber(t.assigned, 0)}</div><div class="summary-subtext">${formatPercentage(t.assigned_pct)}</div></div>
            <div class="summary-card"><div class="summary-label">Returned</div><div class="summary-value" style="color: var(--accent);">${formatNumber(t.returned, 0)}</div><div class="summary-subtext">${formatPercentage(t.returned_pct)}</div></div>
            <div class="summary-card"><div class="summary-label">Total Premium</div><div class="summary-value">${compactCurrency(t.total_premium)}</div></div>
            <div class="summary-card"><div class="summary-label">Returned Position Premium</div><div class="summary-value" style="color: var(--accent);">${compactCurrency(t.returned_premium)}</div><div class="summary-subtext">Pure profit</div></div>
        `;

        if (data.by_asset && data.by_asset.length) {
            document.getElementById('outcomes-by-asset').innerHTML = `
                <h3 class="subsection-title">By Asset</h3>
                <table class="data-table" id="outcomes-asset-table">
                    <thead><tr>
                        <th>Asset</th><th data-sort-key="total">Expired</th>
                        <th data-sort-key="assigned">Assigned</th><th data-sort-key="returned">Returned</th>
                        <th data-sort-key="assignedpct">Assign %</th>
                        <th data-sort-key="premium">Premium</th><th data-sort-key="notional">Notional</th>
                    </tr></thead>
                    <tbody>${data.by_asset.map(a => `<tr>
                        <td><span class="token-badge ${shortSymbol(a.symbol).toLowerCase()}">${shortSymbol(a.symbol)}</span></td>
                        <td data-sort-key="total" data-sort-value="${a.total}">${a.total}</td>
                        <td data-sort-key="assigned" data-sort-value="${a.assigned}">${a.assigned}</td>
                        <td data-sort-key="returned" data-sort-value="${a.returned}">${a.returned}</td>
                        <td data-sort-key="assignedpct" data-sort-value="${a.assigned_pct}">${formatPercentage(a.assigned_pct)}</td>
                        <td data-sort-key="premium" data-sort-value="${a.total_premium}">${compactCurrency(a.total_premium)}</td>
                        <td data-sort-key="notional" data-sort-value="${a.total_notional}">${compactCurrency(a.total_notional)}</td>
                    </tr>`).join('')}</tbody>
                </table>
            `;
            setupSortableTable('outcomes-asset-table');
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load outcomes: ' + e.message;
    }
}

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
    // Load all sections in parallel
    Promise.allSettled([
        loadMarketPulse(),
        loadOverview(0),
        loadPnlChart(90),
        loadRecent(),
        loadAssets(),
        loadPutCallRatio(90),
        loadOutcomes(),
        loadExpiryExplorer(),
    ]).then(() => {
        // Force Plotly to recalculate widths after all charts are visible
        document.querySelectorAll('.chart-container .js-plotly-plot').forEach(el => {
            Plotly.Plots.resize(el);
        });
    });

    // Overview time period tabs
    document.getElementById('overview-tabs').addEventListener('click', e => {
        const btn = e.target.closest('.tab-button');
        if (!btn) return;
        loadOverview(parseInt(btn.dataset.overviewDays));
    });

    // PnL time tabs
    document.getElementById('pnl-tabs').addEventListener('click', e => {
        const btn = e.target.closest('.tab-button');
        if (!btn) return;
        loadPnlChart(parseInt(btn.dataset.pnlDays));
    });

    // Put/Call ratio tabs
    document.getElementById('pcr-tabs').addEventListener('click', e => {
        const btn = e.target.closest('.tab-button');
        if (!btn) return;
        loadPutCallRatio(parseInt(btn.dataset.pcrDays));
    });

    document.getElementById('detail-close').addEventListener('click', closeAssetDetail);

    // Auto-refresh market pulse and recent activity every 60 seconds
    setInterval(() => {
        loadMarketPulse();
        loadRecent();
    }, 60000);

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
