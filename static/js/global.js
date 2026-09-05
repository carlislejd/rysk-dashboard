// Global Dashboard JavaScript — Asset-focused with Inventory & Outcomes

let selectedAsset = null;
let selectedAssetChain = null;
let selectedChain = 'all';
const DETAIL_TRADES_PER_PAGE = 5;
const HYPE_VOL_DEFAULT_DAYS = 365;
const LIST_PREVIEW_LIMIT = 5;
let globalAssetList = [];
let assetsExpanded = false;
let expiryExpanded = false;
let detailExpiryExpanded = false;
let outcomesExpanded = false;

// ── Helpers ──

function chainValueToId(value) {
    if (value === null || value === undefined || value === '' || value === 'all') return null;
    const text = String(value).toLowerCase();
    if (text === 'ethereum' || text === 'eth' || text === '1') return 1;
    if (text === 'hyperevm' || text === 'hyper-evm' || text === '999') return 999;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function withChain(url, chainOverride = undefined) {
    const chain = chainOverride === undefined ? selectedChain : chainOverride;
    if (chain === null || chain === undefined || chain === '' || chain === 'all') return url;
    const joiner = url.includes('?') ? '&' : '?';
    return `${url}${joiner}chain=${encodeURIComponent(chain)}`;
}

function chainLabel(item) {
    if (!item || item.chain_id === null || item.chain_id === undefined) return 'Unknown';
    return item.chain_name || (Number(item.chain_id) === 1 ? 'Ethereum' : Number(item.chain_id) === 999 ? 'HyperEVM' : `Chain ${item.chain_id}`);
}

function chainBadge(item) {
    const slug = item?.chain_slug || (Number(item?.chain_id) === 1 ? 'ethereum' : Number(item?.chain_id) === 999 ? 'hyperevm' : 'unknown');
    return `<span class="chain-badge ${slug}">${chainLabel(item)}</span>`;
}

function chainKey(item) {
    return item?.chain_id ?? 'all';
}

function escapeAttr(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));
}

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

function getNextExpiry(expiries) {
    const now = Date.now() / 1000;
    const future = (expiries || [])
        .map(e => Number(e.expiry))
        .filter(expiry => Number.isFinite(expiry) && expiry > now)
        .sort((a, b) => a - b);
    if (future.length) return future[0];

    const all = (expiries || [])
        .map(e => Number(e.expiry))
        .filter(Number.isFinite)
        .sort((a, b) => b - a);
    return all[0] ?? null;
}

function outcomeBadge(outcome) {
    if (outcome === 'Assigned') return '<span class="status-badge" style="background: var(--color-error-dim); color: var(--color-error);">Assigned</span>';
    if (outcome === 'Returned') return '<span class="status-badge" style="background: var(--accent-dim); color: var(--accent);">Returned</span>';
    return '<span class="status-badge status-default">Unknown</span>';
}

// ── Protocol Overview (summary + volume chart, driven by unified time-range selector) ──

let overviewDays = 90; // default — unified selector starts at 90d
async function loadOverview(days) {
    overviewDays = days;
    const loading = document.getElementById('summary-loading');
    const content = document.getElementById('summary-content');

    // Fetch summary + volume in parallel
    const summaryParams = days > 0 ? `?days=${days}` : '';
    const volumeDays = days > 0 ? days : 365;
    const [summaryResp, volumeResp] = await Promise.all([
        fetch(withChain('/api/global/summary' + summaryParams)),
        fetch(withChain(`/api/global/volume?days=${volumeDays}`)),
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
        renderChainBreakdown(data.chain_breakdown || []);
    }

    if (volumeData.success) {
        const dates = volumeData.data.map(d => d.date);
        const volumes = volumeData.data.map(d => d.volume);
        const premiums = volumeData.data.map(d => d.premium);
        const chainRows = volumeData.by_chain || [];

        const theme = getPlotlyTheme();
        const traces = [];
        if (selectedChain === 'all' && chainRows.length) {
            const byChain = new Map();
            chainRows.forEach(row => {
                const key = chainLabel(row);
                if (!byChain.has(key)) byChain.set(key, { dates: [], volumes: [], slug: row.chain_slug });
                byChain.get(key).dates.push(row.date);
                byChain.get(key).volumes.push(row.volume);
            });
            byChain.forEach((series, label) => {
                traces.push({
                    x: series.dates,
                    y: series.volumes,
                    type: 'bar',
                    name: `${label} Notional`,
                    marker: { color: series.slug === 'ethereum' ? 'rgba(98, 126, 234, 0.58)' : 'rgba(103, 153, 126, 0.52)' },
                });
            });
        } else {
            traces.push({ x: dates, y: volumes, type: 'bar', name: 'Notional', marker: { color: 'rgba(103, 153, 126, 0.55)' } });
        }
        traces.push({ x: dates, y: premiums, type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#b48c52', width: 2 }, marker: { size: 4 }, yaxis: 'y2' });

        Plotly.newPlot('volume-chart', traces, {
            barmode: 'stack',
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'DM Sans, sans-serif', color: theme.fontColor, size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Notional ($)', gridcolor: theme.gridColor, tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#b48c52' }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
    }
}

function renderChainBreakdown(chains) {
    const el = document.getElementById('chain-breakdown');
    if (!el) return;
    if (!chains.length) {
        el.innerHTML = '';
        return;
    }
    el.innerHTML = `
        <div class="chain-breakdown-title">By Chain</div>
        <div class="chain-breakdown-grid">
            ${chains.map(chain => `
                <div class="chain-breakdown-card">
                    <div class="chain-breakdown-head">${chainBadge(chain)}</div>
                    <div class="asset-card-metrics">
                        <div class="asset-metric"><span class="asset-metric-label">Orders</span><span class="asset-metric-value">${formatNumber(chain.trade_count, 0)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Notional</span><span class="asset-metric-value">${compactCurrency(chain.total_volume)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Premium</span><span class="asset-metric-value">${compactCurrency(chain.total_premium)}</span></div>
                        <div class="asset-metric"><span class="asset-metric-label">Assets</span><span class="asset-metric-value">${formatNumber(chain.asset_count, 0)}</span></div>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

// ── Asset Grid ──

async function loadAssets() {
    const requestChain = selectedChain;
    const loading = document.getElementById('assets-loading');
    const content = document.getElementById('assets-content');
    try {
        const resp = await fetch(withChain('/api/global/assets'));
        const data = await resp.json();
        if (requestChain !== selectedChain) return;
        if (!data.success) throw new Error(data.error);
        globalAssetList = data.assets || [];
        assetsExpanded = false;
        renderAssetCards();

        loading.style.display = 'none';
        content.style.display = 'block';

        selectedAsset = null;
    } catch (e) {
        if (requestChain !== selectedChain) return;
        loading.textContent = 'Failed to load assets: ' + e.message;
    }
}

function renderAssetCards() {
    const grid = document.getElementById('asset-grid');
    const toggle = document.getElementById('asset-list-toggle');
    if (!grid) return;
    if (!globalAssetList.length) {
        grid.innerHTML = '<div class="empty-state asset-empty-state">No assets for this chain yet.</div>';
        if (toggle) toggle.style.display = 'none';
        return;
    }
    const query = (document.getElementById('asset-search')?.value || '').trim().toLowerCase();
    const filtered = globalAssetList.filter(a => `${a.symbol} ${chainLabel(a)}`.toLowerCase().includes(query));
    const visible = query || assetsExpanded ? filtered : filtered.slice(0, LIST_PREVIEW_LIMIT);

    grid.innerHTML = visible.map(a => {
        const base = shortSymbol(a.symbol);
        const putPct = a.trade_count > 0 ? ((a.put_count / a.trade_count) * 100).toFixed(0) : 0;
        const callPct = a.trade_count > 0 ? ((a.call_count / a.trade_count) * 100).toFixed(0) : 0;
        const expiredTotal = a.expired_count || 0;
        const returnedPct = expiredTotal > 0 ? ((a.returned / expiredTotal) * 100).toFixed(0) : '—';
        return `
            <div class="asset-card" role="button" tabindex="0" aria-label="Inspect ${escapeAttr(a.symbol)} on ${escapeAttr(chainLabel(a))}" data-asset="${escapeAttr(a.symbol)}" data-chain-id="${escapeAttr(a.chain_id ?? '')}">
                <div class="asset-card-header">
                    <span class="asset-symbol"><span class="token-badge ${base.toLowerCase()}">${base}</span></span>
                    <span class="asset-count">${formatNumber(a.trade_count, 0)} orders</span>
                </div>
                <div class="asset-card-chain">${chainBadge(a)}</div>
                <div class="asset-card-metrics">
                    <div class="asset-metric"><span class="asset-metric-label">Notional</span><span class="asset-metric-value">${compactCurrency(a.total_volume)}</span></div>
                    <div class="asset-metric"><span class="asset-metric-label">Premium</span><span class="asset-metric-value">${compactCurrency(a.total_premium)}</span></div>
                    <div class="asset-metric"><span class="asset-metric-label">Avg APR</span><span class="asset-metric-value asset-summary-apr">${formatPercentage(a.avg_apr)}</span></div>
                    <div class="asset-metric"><span class="asset-metric-label">Put / Call</span><span class="asset-metric-value">${putPct}% / ${callPct}%</span></div>
                    <div class="asset-metric"><span class="asset-metric-label" title="Trades without a recorded outcome; may include past expiries">Unresolved</span><span class="asset-metric-value">${formatNumber(a.active_count, 0)}</span></div>
                    <div class="asset-metric"><span class="asset-metric-label">Outcomes recorded</span><span class="asset-metric-value">${formatNumber(expiredTotal, 0)}</span></div>
                    <div class="asset-metric"><span class="asset-metric-label">Returned</span><span class="asset-metric-value" style="color: var(--accent);">${returnedPct}%</span></div>
                </div>
            </div>
        `;
    }).join('');

    if (!visible.length) grid.innerHTML = '<div class="empty-state">No matching assets. Try a symbol such as BTC, ETH, or HYPE.</div>';
    if (toggle) {
        const needsToggle = !query && globalAssetList.length > LIST_PREVIEW_LIMIT;
        toggle.style.display = needsToggle ? 'inline-flex' : 'none';
        toggle.textContent = assetsExpanded ? 'Show fewer' : `Show all ${globalAssetList.length}`;
    }
}

// ── Asset Detail Panel ──

let detailExpiries = []; // cached expiry list for the current asset
let selectedExpiry = null; // null = All
let latestStrikeDetail = null;
let strikeLensState = {
    referencePrice: null,
    defaultReferencePrice: null,
    side: 'all',
    metric: 'volume',
    minNotional: 0,
    orders: [],
};

async function showAssetDetail(symbol, { scroll = true, preserveExpiry = false, preferredExpiry = undefined, chainId = undefined } = {}) {
    selectedAsset = symbol;
    selectedAssetChain = chainId !== undefined ? chainId : chainValueToId(selectedChain);
    if (!preserveExpiry) selectedExpiry = null;
    const panel = document.getElementById('asset-detail');
    const base = shortSymbol(symbol);

    document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('selected'));
    const card = Array.from(document.querySelectorAll(`.asset-card[data-asset="${CSS.escape(symbol)}"]`))
        .find(c => String(c.dataset.chainId || '') === String(selectedAssetChain ?? ''));
    if (card) card.classList.add('selected');

    document.getElementById('detail-asset-name').textContent = `${symbol}`;
    panel.style.display = 'flex';
    requestAnimationFrame(() => {
        panel.classList.add('is-open');
        document.body.classList.add('sidepanel-open');
    });

    // First fetch unfiltered to get full expiry list for this asset
    const detailResp = await fetch(withChain(`/api/global/asset/${encodeURIComponent(symbol)}`, selectedAssetChain));
    const detail = await detailResp.json();

    if (detail.success) {
        detailExpiries = detail.expiries || [];

        if (preferredExpiry !== undefined) {
            const parsed = preferredExpiry === null ? null : Number(preferredExpiry);
            selectedExpiry = parsed === null
                ? null
                : detailExpiries.some(e => e.expiry === parsed) ? parsed : getNextExpiry(detailExpiries);
        } else if (preserveExpiry && selectedExpiry !== null && !detailExpiries.some(e => e.expiry === selectedExpiry)) {
            selectedExpiry = getNextExpiry(detailExpiries);
        } else if (!preserveExpiry && selectedExpiry === null) {
            selectedExpiry = getNextExpiry(detailExpiries);
        }

        renderExpiryTabs(symbol);

        if (selectedExpiry !== null) {
            // Re-fetch summary data filtered by the preserved expiry
            const filteredResp = await fetch(withChain(`/api/global/asset/${encodeURIComponent(symbol)}?expiry=${selectedExpiry}`, selectedAssetChain));
            const filtered = await filteredResp.json();
            if (filtered.success) {
                renderDetailSummary(filtered);
                document.getElementById('detail-expiry-content').style.display = 'none';
            }
        } else {
            renderDetailSummary(detail);
            renderExpiryBreakdown(detail);
        }
    }

    loadDetailData(symbol, selectedExpiry);
}

function renderExpiryTabs(symbol) {
    const tabs = document.getElementById('detail-expiry-tabs');
    const sorted = [...detailExpiries].sort((a, b) => b.expiry - a.expiry);
    const allActive = selectedExpiry === null;
    tabs.innerHTML = `<button class="tab-button${allActive ? ' active' : ''}" data-detail-expiry="all">All</button>` +
        sorted.map(e =>
            `<button class="tab-button${e.expiry === selectedExpiry ? ' active' : ''}" data-detail-expiry="${e.expiry}">${formatUnixDate(e.expiry)}</button>`
        ).join('');

    // If a specific expiry is active (not "All"), scroll it into view in the carousel
    const activeBtn = tabs.querySelector('.tab-button.active:not([data-detail-expiry="all"])');
    if (activeBtn) activeBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });

    tabs.onclick = async (ev) => {
        const btn = ev.target.closest('.tab-button');
        if (!btn) return;
        tabs.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const val = btn.dataset.detailExpiry;
        selectedExpiry = val === 'all' ? null : parseInt(val);

        // Re-fetch detail (filtered strikes) + volume + trades
        const expiryParam = selectedExpiry ? `&expiry=${selectedExpiry}` : '';
        const detailResp = await fetch(withChain(`/api/global/asset/${encodeURIComponent(symbol)}?${selectedExpiry ? 'expiry=' + selectedExpiry : ''}`, selectedAssetChain));
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
        fetch(withChain(`/api/global/volume?symbol=${sym}&days=365${expiryParam}`, selectedAssetChain)),
        fetch(withChain(`/api/global/trades?symbol=${sym}&limit=${DETAIL_TRADES_PER_PAGE}&page=1${expiryParam}`, selectedAssetChain)),
    ]);
    const [vol, trades] = await Promise.all([volResp.json(), tradesResp.json()]);
    if (vol.success) renderDetailVolumeChart(vol);

    // Also re-fetch strike chart with expiry filter
    const detailResp = await fetch(withChain(`/api/global/asset/${encodeURIComponent(symbol)}${expiry ? '?expiry=' + expiry : ''}`, selectedAssetChain));
    const detail = await detailResp.json();
    if (detail.success) renderStrikeChart(detail);

    if (trades.success) renderDetailTrades(trades, symbol, expiry);
    setTimeout(() => {
        document.querySelectorAll('#asset-detail .js-plotly-plot').forEach(el => {
            Plotly.Plots.resize(el);
        });
    }, 220);
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

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));
}

function getStrikeReference(detail, overridePrice = null) {
    const now = Date.now() / 1000;
    const isSpecificExpiry = selectedExpiry !== null;
    const isActiveView = isSpecificExpiry && selectedExpiry > now;
    const isExpiredView = isSpecificExpiry && selectedExpiry <= now;

    if (overridePrice !== null && overridePrice !== undefined && Number.isFinite(Number(overridePrice))) {
        return {
            price: Number(overridePrice),
            label: `Reference ${formatStrike(overridePrice)}`,
            isExpiredView,
            isActiveView,
            hasContext: true,
            isCustom: true,
        };
    }

    if (isActiveView && detail.current_price != null) {
        return {
            price: Number(detail.current_price),
            label: `Price ${formatStrike(detail.current_price)}`,
            isExpiredView: false,
            isActiveView: true,
            hasContext: true,
            isCustom: false,
        };
    }

    if (isExpiredView) {
        const matchedExpiry = (detail.expiries || []).find(e => e.expiry === selectedExpiry);
        if (matchedExpiry && matchedExpiry.expiry_price != null) {
            return {
                price: Number(matchedExpiry.expiry_price),
                label: `Settlement ${formatStrike(matchedExpiry.expiry_price)}`,
                isExpiredView: true,
                isActiveView: false,
                hasContext: true,
                isCustom: false,
            };
        }
    }

    return {
        price: null,
        label: '',
        isExpiredView,
        isActiveView,
        hasContext: false,
        isCustom: false,
    };
}

function getStrikeMetricConfig(mode = 'volume') {
    if (mode === 'orders') {
        return { mode, field: 'count', label: 'Orders', yTitle: 'Orders', heading: 'Order count by strike' };
    }
    if (mode === 'premium') {
        return { mode, field: 'premium', label: 'Premium', yTitle: 'Premium Paid ($)', heading: 'Premium paid by strike' };
    }
    return { mode: 'volume', field: 'volume', label: 'Notional', yTitle: 'Notional ($)', heading: 'Notional by strike' };
}

function getStrikeMetric(row, side, mode = 'volume') {
    const prefix = side === 'call' ? 'call' : 'put';
    const metric = getStrikeMetricConfig(mode);
    return Number(row[`${prefix}_${metric.field}`] || 0);
}

function formatStrikeMetric(value, mode = 'volume') {
    return mode === 'orders' ? formatNumber(value, 0) : compactCurrency(value);
}

function buildStrikeValueLabels(values, mode, limit = 4) {
    const ranked = values
        .map((value, index) => ({ value: Number(value || 0), index }))
        .filter(item => item.value > 0)
        .sort((a, b) => b.value - a.value)
        .slice(0, limit);
    const visible = new Set(ranked.map(item => item.index));
    return values.map((value, index) => visible.has(index) ? formatStrikeMetric(value, mode) : '');
}

function summarizeStrikeExposure(strikes, referencePrice, mode = 'volume') {
    const summary = {
        callLevels: 0,
        putLevels: 0,
        callExposure: 0,
        putExposure: 0,
        totalCall: 0,
        totalPut: 0,
        totalExposure: 0,
    };

    for (const s of strikes) {
        const callValue = getStrikeMetric(s, 'call', mode);
        const putValue = getStrikeMetric(s, 'put', mode);
        summary.totalCall += callValue;
        summary.totalPut += putValue;
        if (referencePrice !== null && referencePrice !== undefined) {
            if (s.strike < referencePrice && callValue > 0) {
                summary.callLevels += 1;
                summary.callExposure += callValue;
            }
            if (s.strike > referencePrice && putValue > 0) {
                summary.putLevels += 1;
                summary.putExposure += putValue;
            }
        }
    }
    summary.totalExposure = summary.callExposure + summary.putExposure;
    return summary;
}

function buildStrikeChart(detail, options = {}) {
    const strikes = [...(detail.strikes || [])].sort((a, b) => (a.strike || 0) - (b.strike || 0));
    const strikeValues = strikes.map(s => s.strike);
    const barWidth = getStrikeBarWidth(strikeValues);
    const theme = getPlotlyTheme();
    const reference = getStrikeReference(detail, options.referencePrice);
    const shapes = [];
    const annotations = [];
    const metric = getStrikeMetricConfig(options.metricMode || 'volume');
    const mode = metric.mode;
    const side = options.side || 'all';
    const minNotional = Math.max(0, Number(options.minNotional || 0));
    const compact = options.compact !== false;
    const showPuts = side === 'all' || side === 'put';
    const showCalls = side === 'all' || side === 'call';
    const visibleStrikes = strikes.map(s => {
        const putNotional = Number(s.put_volume || 0);
        const callNotional = Number(s.call_volume || 0);
        const putVisible = showPuts && putNotional >= minNotional && putNotional > 0;
        const callVisible = showCalls && callNotional >= minNotional && callNotional > 0;
        return {
            ...s,
            put_volume: putVisible ? putNotional : 0,
            call_volume: callVisible ? callNotional : 0,
            put_count: putVisible ? Number(s.put_count || 0) : 0,
            call_count: callVisible ? Number(s.call_count || 0) : 0,
            put_premium: putVisible ? Number(s.put_premium || 0) : 0,
            call_premium: callVisible ? Number(s.call_premium || 0) : 0,
        };
    });

    if (strikeValues.length && reference.price !== null && Number.isFinite(reference.price)) {
        const minStrike = strikeValues[0];
        const maxStrike = strikeValues[strikeValues.length - 1];
        const xPad = barWidth;
        const xMin = minStrike - xPad;
        const xMax = maxStrike + xPad;
        const exposure = summarizeStrikeExposure(visibleStrikes, reference.price, mode);
        const suffix = reference.isExpiredView ? ' settled ITM' : ' at risk';

        shapes.push({
            type: 'rect', x0: xMin, x1: reference.price, y0: 0, y1: 1, yref: 'paper',
            fillcolor: theme.zoneCallBg, line: { width: 0 }, layer: 'below'
        });
        shapes.push({
            type: 'rect', x0: reference.price, x1: xMax, y0: 0, y1: 1, yref: 'paper',
            fillcolor: theme.zonePutBg, line: { width: 0 }, layer: 'below'
        });

        if (exposure.callLevels > 0 || exposure.callExposure > 0) {
            annotations.push({
                x: (xMin + reference.price) / 2, y: 1.0, yref: 'paper', yanchor: 'bottom',
                text: `<b>${formatStrikeMetric(exposure.callExposure, mode)} call ${metric.label.toLowerCase()}</b><br>${exposure.callLevels} target level${exposure.callLevels !== 1 ? 's' : ''}${suffix}`,
                showarrow: false,
                font: { size: compact ? 10 : 12, color: 'rgba(106, 157, 168, 0.88)', family: 'DM Sans, sans-serif' },
                bgcolor: theme.annotationBg, borderpad: compact ? 4 : 6,
            });
        }

        if (exposure.putLevels > 0 || exposure.putExposure > 0) {
            annotations.push({
                x: (reference.price + xMax) / 2, y: 1.0, yref: 'paper', yanchor: 'bottom',
                text: `<b>${formatStrikeMetric(exposure.putExposure, mode)} put ${metric.label.toLowerCase()}</b><br>${exposure.putLevels} target level${exposure.putLevels !== 1 ? 's' : ''}${suffix}`,
                showarrow: false,
                font: { size: compact ? 10 : 12, color: 'rgba(186, 112, 104, 0.88)', family: 'DM Sans, sans-serif' },
                bgcolor: theme.annotationBg, borderpad: compact ? 4 : 6,
            });
        }

        shapes.push({
            type: 'line', x0: reference.price, x1: reference.price, y0: 0, y1: 1, yref: 'paper',
            line: { color: 'rgba(242, 255, 247, 0.44)', width: compact ? 1.5 : 2, dash: reference.isExpiredView ? 'solid' : 'dot' }
        });

        annotations.push({
            x: reference.price, y: 0, yref: 'paper', yanchor: 'top', yshift: 6,
            text: `<b>${reference.label}</b>`,
            showarrow: false,
            font: { size: compact ? 10 : 12, color: theme.annotationColor, family: 'DM Sans, sans-serif' },
            bgcolor: theme.annotationBg, borderpad: compact ? 3 : 5,
        });
    }

    const data = [];
    if (showPuts) {
        const putValues = visibleStrikes.map(s => getStrikeMetric(s, 'put', mode));
        data.push({
            x: strikeValues,
            y: putValues,
            customdata: visibleStrikes.map(s => [s.put_volume || 0, s.put_count || 0, s.put_premium || 0]),
            type: 'bar',
            name: 'Put',
            offsetgroup: 'put',
            marker: { color: 'rgba(186, 112, 104, 0.72)', line: { color: 'rgba(186, 112, 104, 1)', width: 1 } },
            text: compact ? undefined : buildStrikeValueLabels(putValues, mode),
            textposition: 'outside',
            textfont: { color: 'rgba(255, 104, 132, 0.95)', family: 'DM Sans, sans-serif', size: 10 },
            cliponaxis: false,
            hovertemplate: `Put target %{x:$,.2f}<br>${metric.label} %{y:${mode === 'orders' ? ',.0f' : '$,.0f'}}<br>Notional %{customdata[0]:$,.0f}<br>Orders %{customdata[1]:,.0f}<br>Premium %{customdata[2]:$,.2f}<extra></extra>`,
        });
    }
    if (showCalls) {
        const callValues = visibleStrikes.map(s => getStrikeMetric(s, 'call', mode));
        data.push({
            x: strikeValues,
            y: callValues,
            customdata: visibleStrikes.map(s => [s.call_volume || 0, s.call_count || 0, s.call_premium || 0]),
            type: 'bar',
            name: 'Call',
            offsetgroup: 'call',
            marker: { color: 'rgba(106, 157, 168, 0.72)', line: { color: 'rgba(106, 157, 168, 1)', width: 1 } },
            text: compact ? undefined : buildStrikeValueLabels(callValues, mode),
            textposition: 'outside',
            textfont: { color: 'rgba(43, 220, 255, 0.95)', family: 'DM Sans, sans-serif', size: 10 },
            cliponaxis: false,
            hovertemplate: `Call target %{x:$,.2f}<br>${metric.label} %{y:${mode === 'orders' ? ',.0f' : '$,.0f'}}<br>Notional %{customdata[0]:$,.0f}<br>Orders %{customdata[1]:,.0f}<br>Premium %{customdata[2]:$,.2f}<extra></extra>`,
        });
    }

    const layout = {
        barmode: 'group',
        bargap: compact ? 0.16 : 0.2,
        bargroupgap: 0.08,
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { family: 'DM Sans, sans-serif', color: theme.fontColor, size: compact ? 12 : 13 },
        margin: compact ? { l: 60, r: 20, t: 48, b: 60 } : { l: 78, r: 28, t: 76, b: 70 },
        xaxis: {
            title: 'Strike Target',
            showgrid: !compact,
            gridcolor: theme.gridColor,
            nticks: compact ? 8 : 14,
            tickfont: { size: compact ? 10 : 11 },
            tickprefix: '$',
            tickangle: -35,
            automargin: true,
        },
        yaxis: {
            title: metric.yTitle,
            gridcolor: theme.gridColor,
            tickprefix: mode === 'orders' ? '' : '$',
            tickformat: mode === 'orders' ? ',.0f' : '~s',
            rangemode: 'tozero',
            automargin: true,
        },
        legend: { orientation: 'h', y: compact ? -0.12 : -0.1, font: { size: compact ? 11 : 12 } },
        hovermode: 'closest',
        uniformtext: { minsize: 9, mode: 'hide' },
        hoverlabel: {
            bgcolor: '#0c0e13',
            font: { color: '#f2fff7', family: 'DM Sans, sans-serif' },
            bordercolor: 'rgba(170,255,210,0.07)'
        },
        shapes,
        annotations,
    };

    return {
        data,
        layout,
        strikes: visibleStrikes,
        reference,
        metric,
        exposure: summarizeStrikeExposure(visibleStrikes, reference.price, mode),
        notionalExposure: summarizeStrikeExposure(visibleStrikes, reference.price, 'volume'),
    };
}

function updateStrikeCaption(detail, chartModel) {
    const caption = document.getElementById('detail-strike-caption');
    if (!caption) return;
    if (!chartModel.reference.hasContext) {
        caption.textContent = 'Select a single expiry to see which targets are above or below the reference price.';
        return;
    }
    const exposure = chartModel.exposure;
    caption.textContent = `${compactCurrency(exposure.putExposure)} put exposure above ${formatStrike(chartModel.reference.price)} and ${compactCurrency(exposure.callExposure)} call exposure below it.`;
}

function renderStrikeChart(detail) {
    const strikes = detail.strikes || [];
    latestStrikeDetail = detail;
    const expandBtn = document.getElementById('strike-expand');
    if (expandBtn) expandBtn.disabled = !strikes.length;
    if (!strikes.length) {
        document.getElementById('detail-strike-chart').innerHTML = '<div class="loading">No strike data</div>';
        updateStrikeCaption(detail, { reference: { hasContext: false } });
        return;
    }

    const chartModel = buildStrikeChart(detail, { compact: true });
    updateStrikeCaption(detail, chartModel);
    Plotly.newPlot('detail-strike-chart', chartModel.data, chartModel.layout, { responsive: true, displayModeBar: false });
}

function getStrikeSliderBounds(detail) {
    const strikes = [...(detail?.strikes || [])].map(s => Number(s.strike)).filter(Number.isFinite).sort((a, b) => a - b);
    if (!strikes.length) return { min: 0, max: 100, step: 1 };
    const min = strikes[0];
    const max = strikes[strikes.length - 1];
    const barWidth = getStrikeBarWidth(strikes);
    return {
        min: Math.max(0, min - barWidth),
        max: max + barWidth,
        step: Math.max(barWidth / 4, Math.abs(max - min) / 400, 0.0001),
    };
}

function setStrikeSlider(detail, referencePrice) {
    const slider = document.getElementById('strike-reference-slider');
    if (!slider) return;
    const bounds = getStrikeSliderBounds(detail);
    slider.min = String(bounds.min);
    slider.max = String(bounds.max);
    slider.step = String(bounds.step);
    slider.value = String(referencePrice ?? bounds.min);
}

async function fetchStrikeLensOrders() {
    if (!selectedAsset) return;
    const expiryParam = selectedExpiry ? `&expiry=${selectedExpiry}` : '';
    const resp = await fetch(withChain(`/api/global/trades?symbol=${encodeURIComponent(selectedAsset)}&limit=200&page=1${expiryParam}`, selectedAssetChain));
    const data = await resp.json();
    strikeLensState.orders = data.success ? (data.trades || []) : [];
    renderStrikeLens();
}

function getStrikeLensAssetSymbols() {
    const fromData = (globalAssetList || []).map(asset => asset.symbol).filter(Boolean);
    if (fromData.length) return fromData;

    return Array.from(document.querySelectorAll('.asset-card[data-asset]'))
        .map(card => card.dataset.asset)
        .filter(Boolean);
}

function updateStrikeLensTitle() {
    const title = document.getElementById('strike-modal-title');
    if (!title) return;
    title.textContent = `${selectedAsset || 'Asset'} Strike Distribution${selectedExpiry ? ` · ${formatUnixDate(selectedExpiry)}` : ' · All Expiries'}`;
}

function populateStrikeLensControls() {
    const assetSelect = document.getElementById('strike-asset-select');
    const expirySelect = document.getElementById('strike-expiry-select');
    if (assetSelect) {
        const symbols = getStrikeLensAssetSymbols();
        assetSelect.innerHTML = symbols.map(symbol =>
            `<option value="${escapeHtml(symbol)}"${symbol === selectedAsset ? ' selected' : ''}>${escapeHtml(shortSymbol(symbol))}</option>`
        ).join('');
    }
    if (expirySelect) {
        const sorted = [...(detailExpiries || [])].sort((a, b) => b.expiry - a.expiry);
        expirySelect.innerHTML = `<option value="all"${selectedExpiry === null ? ' selected' : ''}>All Expiries</option>` +
            sorted.map(expiry =>
                `<option value="${expiry.expiry}"${expiry.expiry === selectedExpiry ? ' selected' : ''}>${formatUnixDate(expiry.expiry)}</option>`
            ).join('');
    }
}

function resetStrikeLensReference(detail) {
    const defaultReference = getStrikeReference(detail);
    const strikes = detail.strikes || [];
    const fallback = strikes.length ? strikes[Math.floor(strikes.length / 2)].strike : 0;
    const referencePrice = defaultReference.price ?? fallback;
    strikeLensState.referencePrice = referencePrice;
    strikeLensState.defaultReferencePrice = referencePrice;
    setStrikeSlider(detail, referencePrice);
}

async function switchStrikeLensView(symbol, expiry, { resetReference = true } = {}) {
    if (!symbol) return;
    selectedAsset = symbol;

    const baseResp = await fetch(withChain(`/api/global/asset/${encodeURIComponent(symbol)}`, selectedAssetChain));
    const baseDetail = await baseResp.json();
    if (!baseDetail.success) return;

    detailExpiries = baseDetail.expiries || [];
    if (expiry === undefined) {
        selectedExpiry = getNextExpiry(detailExpiries);
    } else if (expiry === null) {
        selectedExpiry = null;
    } else {
        const parsed = Number(expiry);
        selectedExpiry = detailExpiries.some(e => e.expiry === parsed) ? parsed : getNextExpiry(detailExpiries);
    }

    const detail = selectedExpiry
        ? await fetch(withChain(`/api/global/asset/${encodeURIComponent(symbol)}?expiry=${selectedExpiry}`, selectedAssetChain)).then(resp => resp.json())
        : baseDetail;
    if (!detail.success) return;

    latestStrikeDetail = detail;
    populateStrikeLensControls();
    updateStrikeLensTitle();
    if (resetReference) resetStrikeLensReference(detail);
    renderStrikeLens();
    fetchStrikeLensOrders();
}

function openStrikeLens() {
    if (!latestStrikeDetail || !(latestStrikeDetail.strikes || []).length) return;
    const modal = document.getElementById('strike-modal');

    strikeLensState = {
        referencePrice: null,
        defaultReferencePrice: null,
        side: 'all',
        metric: 'volume',
        minNotional: 0,
        orders: [],
    };

    updateStrikeLensTitle();
    populateStrikeLensControls();
    resetStrikeLensReference(latestStrikeDetail);
    const minInput = document.getElementById('strike-min-notional');
    if (minInput) minInput.value = '0';
    document.querySelectorAll('#strike-type-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.strikeType === 'all');
    });
    document.querySelectorAll('#strike-metric-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.strikeMetric === 'volume');
    });

    modal.style.display = 'flex';
    const modalBody = modal.querySelector('.strike-modal-body');
    if (modalBody) modalBody.scrollTop = 0;
    document.body.style.overflow = 'hidden';
    renderStrikeLens();
    fetchStrikeLensOrders();
}

function closeStrikeLens() {
    const modal = document.getElementById('strike-modal');
    if (!modal) return;
    modal.style.display = 'none';
    document.body.style.overflow = '';
}

function filteredStrikeRows(detail) {
    const side = strikeLensState.side;
    const minNotional = Number(strikeLensState.minNotional || 0);
    const rows = [];
    for (const s of detail.strikes || []) {
        const put = Number(s.put_volume || 0);
        const call = Number(s.call_volume || 0);
        const includePut = (side === 'all' || side === 'put') && put >= minNotional && put > 0;
        const includeCall = (side === 'all' || side === 'call') && call >= minNotional && call > 0;
        if (includePut) rows.push({ side: 'Put', strike: s.strike, notional: put, orders: s.put_count || 0, premium: s.put_premium || 0 });
        if (includeCall) rows.push({ side: 'Call', strike: s.strike, notional: call, orders: s.call_count || 0, premium: s.call_premium || 0 });
    }
    const ref = Number(strikeLensState.referencePrice);
    rows.sort((a, b) => Math.abs(a.strike - ref) - Math.abs(b.strike - ref) || b.notional - a.notional);
    return rows;
}

function filteredStrikeOrders() {
    const side = strikeLensState.side;
    const minNotional = Number(strikeLensState.minNotional || 0);
    return (strikeLensState.orders || [])
        .filter(order => side === 'all' || String(order.type || '').toLowerCase() === side)
        .filter(order => Number(order.notional || 0) >= minNotional);
}

function summarizeStrikeRows(rows, side) {
    const selected = rows.filter(row => row.side.toLowerCase() === side);
    const largest = selected.reduce((best, row) => !best || row.notional > best.notional ? row : best, null);
    return {
        levels: selected.length,
        notional: selected.reduce((sum, row) => sum + Number(row.notional || 0), 0),
        orders: selected.reduce((sum, row) => sum + Number(row.orders || 0), 0),
        premium: selected.reduce((sum, row) => sum + Number(row.premium || 0), 0),
        largest,
    };
}

function formatLensCurrency(value) {
    const numeric = Number(value || 0);
    return Math.abs(numeric) >= 1000 ? compactCurrency(numeric, 2) : formatCurrency(numeric);
}

function renderStrikeStory(rows, chartModel, referencePrice) {
    const calls = summarizeStrikeRows(rows, 'call');
    const puts = summarizeStrikeRows(rows, 'put');
    const totalNotional = calls.notional + puts.notional;
    const totalOrders = calls.orders + puts.orders;
    const totalPremium = calls.premium + puts.premium;
    const callShare = totalNotional > 0 ? (calls.notional / totalNotional) * 100 : 0;
    const putShare = totalNotional > 0 ? 100 - callShare : 0;
    const larger = calls.notional >= puts.notional ? calls : puts;
    const smaller = calls.notional >= puts.notional ? puts : calls;
    const dominantSide = calls.notional === puts.notional ? 'Balanced' : calls.notional > puts.notional ? 'Call-heavy' : 'Put-heavy';
    const dominance = smaller.notional > 0 ? larger.notional / smaller.notional : larger.notional > 0 ? null : 1;
    const dominanceLabel = dominantSide === 'Balanced'
        ? 'Balanced book'
        : `${dominantSide}${dominance ? ` · ${formatNumber(dominance, 1)}×` : ' only'}`;
    const risk = chartModel.notionalExposure || { totalExposure: 0, callExposure: 0, putExposure: 0 };
    const atRiskShare = totalNotional > 0 ? (risk.totalExposure / totalNotional) * 100 : 0;

    const sideCard = (name, summary, share, tone) => {
        const topTarget = summary.largest
            ? `${formatStrike(summary.largest.strike)} · ${formatLensCurrency(summary.largest.notional)}`
            : 'No matching target';
        return `
            <article class="strike-story-card ${tone}">
                <div class="strike-story-card-header">
                    <span><i></i>${name} book</span>
                    <strong>${formatNumber(share, 0)}% of notional</strong>
                </div>
                <div class="strike-story-hero">${formatLensCurrency(summary.notional)}</div>
                <div class="strike-story-caption">notional across ${formatNumber(summary.levels, 0)} target level${summary.levels !== 1 ? 's' : ''}</div>
                <div class="strike-story-stats">
                    <div><span>Orders</span><strong>${formatNumber(summary.orders, 0)}</strong></div>
                    <div><span>Premium paid</span><strong>${formatLensCurrency(summary.premium)}</strong></div>
                    <div><span>Largest target</span><strong>${topTarget}</strong></div>
                </div>
            </article>`;
    };

    return `
        ${sideCard('Call', calls, callShare, 'call')}
        <article class="strike-story-card thesis">
            <div class="strike-story-card-header">
                <span><i></i>The read</span>
                <strong>${formatNumber(totalOrders, 0)} orders</strong>
            </div>
            <div class="strike-story-hero">${dominanceLabel}</div>
            <div class="strike-story-caption">${formatLensCurrency(totalNotional)} total notional · ${formatLensCurrency(totalPremium)} premium paid</div>
            <div class="strike-book-balance" aria-label="${formatNumber(callShare, 0)} percent calls and ${formatNumber(putShare, 0)} percent puts">
                <span class="call" style="width: ${callShare}%"></span>
                <span class="put" style="width: ${putShare}%"></span>
            </div>
            <div class="strike-story-stats">
                <div><span>Reference</span><strong>${formatStrike(referencePrice)}</strong></div>
                <div><span>At risk</span><strong>${formatLensCurrency(risk.totalExposure)}</strong></div>
                <div><span>Book at risk</span><strong>${formatNumber(atRiskShare, 0)}%</strong></div>
            </div>
        </article>
        ${sideCard('Put', puts, putShare, 'put')}
    `;
}

function renderStrikeLens() {
    if (!latestStrikeDetail) return;
    const chartEl = document.getElementById('strike-modal-chart');
    const readout = document.getElementById('strike-reference-value');
    const summaryEl = document.getElementById('strike-modal-summary');
    const levelsEl = document.getElementById('strike-modal-levels');
    const ordersEl = document.getElementById('strike-modal-orders');
    const chartHeading = document.getElementById('strike-chart-heading');
    const chartNote = document.getElementById('strike-chart-note');
    const levelCount = document.getElementById('strike-level-count');
    const orderCount = document.getElementById('strike-order-count');
    const referencePrice = Number(strikeLensState.referencePrice);
    const chartModel = buildStrikeChart(latestStrikeDetail, {
        compact: false,
        referencePrice,
        side: strikeLensState.side,
        minNotional: strikeLensState.minNotional,
        metricMode: strikeLensState.metric,
    });
    const rows = filteredStrikeRows(latestStrikeDetail);

    if (readout) readout.textContent = formatStrike(referencePrice);
    if (chartHeading) chartHeading.textContent = chartModel.metric.heading;
    if (chartNote) {
        const sideLabel = strikeLensState.side === 'all' ? 'Calls and puts' : `${strikeLensState.side === 'call' ? 'Calls' : 'Puts'}`;
        chartNote.textContent = `${sideLabel} grouped by strike on one shared scale. The largest visible levels are labeled.`;
    }
    if (summaryEl) {
        summaryEl.innerHTML = renderStrikeStory(rows, chartModel, referencePrice);
    }

    if (chartEl && typeof Plotly !== 'undefined') {
        const plot = chartEl.classList.contains('js-plotly-plot') ? Plotly.react : Plotly.newPlot;
        plot(chartEl, chartModel.data, chartModel.layout, { responsive: true, displayModeBar: false })
            .then(() => Plotly.Plots.resize(chartEl));
    }

    if (levelCount) levelCount.textContent = `${formatNumber(rows.length, 0)} level${rows.length !== 1 ? 's' : ''}`;
    if (levelsEl) {
        levelsEl.innerHTML = rows.length ? `
            <table class="data-table strike-data-table" id="strike-modal-levels-table">
                <thead><tr>
                    <th data-sort-key="side">Side</th>
                    <th data-sort-key="strike">Target</th>
                    <th data-sort-key="distance">Distance</th>
                    <th data-sort-key="notional">Notional</th>
                    <th data-sort-key="orders">Orders</th>
                    <th data-sort-key="premium">Premium</th>
                </tr></thead>
                <tbody>${rows.map(row => {
                    const distance = referencePrice ? ((row.strike - referencePrice) / referencePrice) * 100 : 0;
                    const sideClass = row.side === 'Call' ? 'strike-side-call' : 'strike-side-put';
                    return `<tr>
                        <td class="${sideClass}" data-sort-key="side" data-sort-value="${row.side}"><span class="strike-side-dot"></span>${row.side}</td>
                        <td data-sort-key="strike" data-sort-value="${row.strike}">${formatStrike(row.strike)}</td>
                        <td class="strike-distance" data-sort-key="distance" data-sort-value="${distance}">${distance >= 0 ? '+' : ''}${formatNumber(distance, 1)}%</td>
                        <td data-sort-key="notional" data-sort-value="${row.notional}">${formatLensCurrency(row.notional)}</td>
                        <td data-sort-key="orders" data-sort-value="${row.orders}">${formatNumber(row.orders, 0)}</td>
                        <td data-sort-key="premium" data-sort-value="${row.premium}">${formatLensCurrency(row.premium)}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table>
        ` : '<p class="empty-state">No target levels match the filters.</p>';
        setupSortableTable('strike-modal-levels-table');
    }

    const filteredOrders = filteredStrikeOrders();
    const orders = filteredOrders.slice(0, 80);
    if (orderCount) {
        orderCount.textContent = filteredOrders.length > orders.length
            ? `${formatNumber(orders.length, 0)} of ${formatNumber(filteredOrders.length, 0)} loaded`
            : `${formatNumber(orders.length, 0)} order${orders.length !== 1 ? 's' : ''}`;
    }
    if (ordersEl) {
        ordersEl.innerHTML = orders.length ? `
            <table class="data-table strike-data-table" id="strike-modal-orders-table">
                <thead><tr>
                    <th data-sort-key="created">Date</th>
                    <th data-sort-key="side">Side</th>
                    <th data-sort-key="type">Type</th>
                    <th data-sort-key="strike">Strike</th>
                    <th data-sort-key="notional">Notional</th>
                    <th data-sort-key="premium">Premium</th>
                    <th data-sort-key="apr">APR</th>
                    <th data-sort-key="expiry">Expiry</th>
                </tr></thead>
                <tbody>${orders.map(order => `
                    <tr>
                        <td data-sort-key="created" data-sort-value="${order.created_at || 0}">${formatUnixDateTime(order.created_at)}</td>
                        <td data-sort-key="side" data-sort-value="${escapeAttr(order.side || '')}">${escapeHtml(order.side || '—')}</td>
                        <td class="${String(order.type).toLowerCase() === 'call' ? 'strike-side-call' : 'strike-side-put'}" data-sort-key="type" data-sort-value="${escapeAttr(order.type || '')}"><span class="strike-side-dot"></span>${escapeHtml(order.type || '—')}</td>
                        <td data-sort-key="strike" data-sort-value="${order.strike || 0}">${formatStrike(order.strike)}</td>
                        <td data-sort-key="notional" data-sort-value="${order.notional || 0}">${formatLensCurrency(order.notional || 0)}</td>
                        <td data-sort-key="premium" data-sort-value="${order.premium || 0}">${formatCurrency(order.premium || 0)}</td>
                        <td data-sort-key="apr" data-sort-value="${order.apr || 0}">${formatPercentage(order.apr)}</td>
                        <td data-sort-key="expiry" data-sort-value="${order.expiry || 0}">${formatUnixDate(order.expiry)}</td>
                    </tr>
                `).join('')}</tbody>
            </table>
        ` : '<p class="empty-state">No recent orders match the filters.</p>';
        setupSortableTable('strike-modal-orders-table');
    }
}

function initStrikeLens() {
    const expandBtn = document.getElementById('strike-expand');
    const closeBtn = document.getElementById('strike-modal-close');
    const modal = document.getElementById('strike-modal');
    const slider = document.getElementById('strike-reference-slider');
    const resetBtn = document.getElementById('strike-reference-reset');
    const minInput = document.getElementById('strike-min-notional');
    const tabs = document.getElementById('strike-type-tabs');
    const metricTabs = document.getElementById('strike-metric-tabs');
    const assetSelect = document.getElementById('strike-asset-select');
    const expirySelect = document.getElementById('strike-expiry-select');

    if (expandBtn) expandBtn.addEventListener('click', openStrikeLens);
    if (closeBtn) closeBtn.addEventListener('click', closeStrikeLens);
    if (modal) {
        modal.addEventListener('click', event => {
            if (event.target === modal) closeStrikeLens();
        });
    }
    if (slider) {
        slider.addEventListener('input', event => {
            strikeLensState.referencePrice = Number(event.target.value);
            renderStrikeLens();
        });
    }
    if (metricTabs) {
        metricTabs.addEventListener('click', event => {
            const btn = event.target.closest('.tab-button');
            if (!btn) return;
            metricTabs.querySelectorAll('.tab-button').forEach(tab => tab.classList.remove('active'));
            btn.classList.add('active');
            strikeLensState.metric = btn.dataset.strikeMetric || 'volume';
            renderStrikeLens();
        });
    }
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            strikeLensState.referencePrice = strikeLensState.defaultReferencePrice;
            setStrikeSlider(latestStrikeDetail, strikeLensState.referencePrice);
            renderStrikeLens();
        });
    }
    if (minInput) {
        minInput.addEventListener('input', event => {
            strikeLensState.minNotional = Math.max(0, Number(event.target.value || 0));
            renderStrikeLens();
        });
    }
    if (tabs) {
        tabs.addEventListener('click', event => {
            const btn = event.target.closest('.tab-button');
            if (!btn) return;
            tabs.querySelectorAll('.tab-button').forEach(tab => tab.classList.remove('active'));
            btn.classList.add('active');
            strikeLensState.side = btn.dataset.strikeType || 'all';
            renderStrikeLens();
        });
    }
    if (assetSelect) {
        assetSelect.addEventListener('change', event => {
            switchStrikeLensView(event.target.value, undefined);
        });
    }
    if (expirySelect) {
        expirySelect.addEventListener('change', event => {
            const value = event.target.value;
            switchStrikeLensView(selectedAsset, value === 'all' ? null : Number(value));
        });
    }
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && modal && modal.style.display === 'flex') closeStrikeLens();
    });
}

function renderExpiryBreakdown(detail) {
    const expiries = detail.expiries || [];
    if (!expiries.length) { document.getElementById('detail-expiry-content').innerHTML = '<div class="loading">No expiry data</div>'; return; }
    const now = Date.now() / 1000;
    const visibleExpiries = detailExpiryExpanded ? expiries : expiries.slice(0, LIST_PREVIEW_LIMIT);
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
            <tbody>${visibleExpiries.map(e => {
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
        </table>
        ${expiries.length > LIST_PREVIEW_LIMIT ? `
            <div class="compact-list-actions">
                <button class="terminal-button small" type="button" onclick="detailExpiryExpanded = !detailExpiryExpanded; renderExpiryBreakdown(latestStrikeDetail);">${detailExpiryExpanded ? 'Show fewer' : `Show all ${expiries.length}`}</button>
            </div>
        ` : ''}`;
    setupSortableTable('detail-expiry-table');
}

function renderDetailVolumeChart(vol) {
    const theme = getPlotlyTheme();
    Plotly.newPlot('detail-volume-chart', [
        { x: vol.data.map(d => d.date), y: vol.data.map(d => d.volume), type: 'bar', name: 'Notional', marker: { color: 'rgba(103, 153, 126, 0.55)' } },
        { x: vol.data.map(d => d.date), y: vol.data.map(d => d.premium), type: 'scatter', mode: 'lines+markers', name: 'Premium', line: { color: '#b48c52', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
    ], {
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'DM Sans, sans-serif', color: theme.fontColor, size: 12 },
        margin: { l: 60, r: 60, t: 20, b: 40 },
        xaxis: { showgrid: false, tickfont: { size: 11 } },
        yaxis: { title: 'Notional ($)', gridcolor: theme.gridColor, tickfont: { size: 11 }, tickprefix: '$' },
        yaxis2: { title: 'Premium ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#b48c52' }, tickprefix: '$' },
        legend: { orientation: 'h', y: -0.08, font: { size: 11 } }, bargap: 0.15,
    }, { responsive: true, displayModeBar: false });
}

function renderDetailTrades(data, symbol, expiry) {
    const now = Date.now() / 1000;
    document.getElementById('detail-trades-content').innerHTML = `
        <table class="data-table" id="detail-trades-table"><thead><tr>
            <th data-sort-key="created">Date</th><th>Chain</th><th>Type</th><th data-sort-key="strike">Strike</th>
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
            <td>${chainBadge(t)}</td>
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
    const resp = await fetch(withChain(`/api/global/trades?symbol=${encodeURIComponent(symbol)}&limit=${DETAIL_TRADES_PER_PAGE}&page=${page}${expiryParam}`, selectedAssetChain));
    const data = await resp.json();
    if (data.success) renderDetailTrades(data, symbol, expiry);
}

function closeAssetDetail() {
    const panel = document.getElementById('asset-detail');
    if (panel) {
        panel.classList.remove('is-open');
        setTimeout(() => {
            if (!panel.classList.contains('is-open')) {
                panel.style.display = 'none';
            }
        }, 220);
    }
    document.body.classList.remove('sidepanel-open');
    document.querySelectorAll('.asset-card').forEach(c => c.classList.remove('selected'));
    selectedAsset = null;
    selectedAssetChain = null;
    selectedExpiry = null;
}

// ── Expiry Explorer ──

let expiryData = [];
let selectedExplorerExpiry = null; // null = All

async function loadExpiryExplorer() {
    const requestChain = selectedChain;
    const loading = document.getElementById('expiry-loading');
    const content = document.getElementById('expiry-content');
    try {
        const resp = await fetch(withChain('/api/global/expiries'));
        const data = await resp.json();
        if (requestChain !== selectedChain) return;
        if (!data.success) throw new Error(data.error);
        expiryData = data.expiries;

        // Build tabs — All + each expiry date (most recent first, already sorted)
        const tabs = document.getElementById('expiry-explorer-tabs');
        tabs.innerHTML = `<button class="tab-button active" data-exp-tab="all">All</button>` +
            expiryData.map(e =>
                `<button class="tab-button" data-exp-tab="${e.expiry}:${e.chain_id ?? ''}">${formatUnixDate(e.expiry)} · ${e.chain_short_name || e.chain_name || ''}${e.expired ? '' : ' *'}</button>`
            ).join('');

        tabs.onclick = (ev) => {
            const btn = ev.target.closest('.tab-button');
            if (!btn) return;
            tabs.querySelectorAll('.tab-button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const val = btn.dataset.expTab;
            selectedExplorerExpiry = val === 'all' ? null : val;
            renderExpiryExplorer();
        };

        renderExpiryExplorer();
        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        if (requestChain !== selectedChain) return;
        loading.textContent = 'Failed to load expiries: ' + e.message;
    }
}

function renderExpiryExplorer() {
    const selected = selectedExplorerExpiry;
    const filtered = selected
        ? expiryData.filter(e => `${e.expiry}:${e.chain_id ?? ''}` === selected)
        : expiryData;

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
                        ${chainBadge(single)}
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
        const visibleExpiries = expiryExpanded ? expiryData : expiryData.slice(0, LIST_PREVIEW_LIMIT);
        detail.innerHTML = `
            <table class="data-table" id="expiry-overview-table">
                <thead><tr>
                    <th data-sort-key="expiry">Expiry</th>
                    <th>Chain</th>
                    <th data-sort-key="orders">Orders</th>
                    <th>Assets</th>
                    <th data-sort-key="notional">Notional</th>
                    <th data-sort-key="premium">Premium</th>
                    <th>Yield</th>
                    <th>DTE</th>
                    <th>Put/Call</th>
                    <th>Returned</th>
                </tr></thead>
                <tbody>${visibleExpiries.map(e => {
                    const rr = (e.assigned + e.returned) > 0
                        ? `<span style="color: var(--accent);">${e.return_rate}%</span>`
                        : (e.expired ? '—' : '<span style="color: var(--text-muted);">Active</span>');
                    const pc = e.total_orders > 0 ? `${((e.put_count / e.total_orders) * 100).toFixed(0)}/${((e.call_count / e.total_orders) * 100).toFixed(0)}` : '—';
                    return `<tr>
                        <td data-sort-key="expiry" data-sort-value="${e.expiry}">${formatUnixDate(e.expiry)}${e.expired ? '' : ' *'}</td>
                        <td>${chainBadge(e)}</td>
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
            ${expiryData.length > LIST_PREVIEW_LIMIT ? `
                <div class="compact-list-actions">
                    <button class="terminal-button small" type="button" onclick="expiryExpanded = !expiryExpanded; renderExpiryExplorer();">${expiryExpanded ? 'Show fewer' : `Show all ${expiryData.length}`}</button>
                </div>
            ` : ''}
        `;
        setupSortableTable('expiry-overview-table');
    }
}

// ── Recent Activity (top 10) ──

async function loadRecent() {
    const requestChain = selectedChain;
    const loading = document.getElementById('recent-loading');
    const content = document.getElementById('recent-content');
    try {
        const resp = await fetch(withChain('/api/global/trades?limit=5&iv=true'));
        const data = await resp.json();
        if (requestChain !== selectedChain) return;
        if (!data.success) throw new Error(data.error);

        document.querySelector('[data-export-table="recent-table"]').disabled = !data.trades.length;
        if (!data.trades.length) {
            loading.textContent = 'No recorded trades for this chain.';
            loading.style.display = 'block'; content.style.display = 'none'; return;
        }
        document.getElementById('recent-body').innerHTML = data.trades.map(t => `<tr>
            <td>${formatUnixDateTime(t.created_at)}</td>
            <td>${chainBadge(t)}</td>
            <td><span class="token-badge ${shortSymbol(t.symbol).toLowerCase()}">${shortSymbol(t.symbol)}</span></td>
            <td>${t.type}</td>
            <td>${formatStrike(t.strike)}</td>
            <td>${formatUnixDate(t.expiry)}</td>
            <td>${formatCurrency(t.premium)}</td>
            <td>${formatCurrency(t.notional, 0)}</td>
            <td>${formatPercentage(t.apr)}</td>
            <td>${t.iv != null ? formatPercentage(t.iv, 1) : '—'}</td>
        </tr>`).join('');

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        if (requestChain !== selectedChain) return;
        loading.textContent = 'Failed to load recent trades: ' + e.message;
    }
}

// ── Market Pulse ──

async function loadMarketPulse() {
    const requestChain = selectedChain;
    const loading = document.getElementById('pulse-loading');
    const content = document.getElementById('pulse-content');
    try {
        const resp = await fetch(withChain('/api/global/market-pulse'));
        const data = await resp.json();
        if (requestChain !== selectedChain) return;
        if (!data.success) throw new Error(data.error);

        const top = data.top_asset_24h;
        const act = data.activity;
        const dte = data.avg_dte;
        const active = data.active_positions;
        const volIndicator = act.volume_vs_daily_avg !== null
            ? (act.volume_vs_daily_avg > 0 ? `+${act.volume_vs_daily_avg}%` : `${act.volume_vs_daily_avg}%`)
            : '—';
        const volColor = act.volume_vs_daily_avg > 0 ? 'var(--accent)' : (act.volume_vs_daily_avg < 0 ? 'var(--color-error)' : 'var(--text-muted)');

        // Populate hero KPIs (4 of 5 — next-expiry comes from loadNextExpiryPositions)
        populateGlobalHero({ act, top, active, dte, volIndicator, volColor });

        const freshness = data.observation || {};
        const latest = freshness.last_trade_at;
        const status = document.getElementById('observation-status');
        const stale = latest && (Date.now() / 1000 - latest > 86400);
        status.textContent = latest ? `Latest recorded trade · ${formatUnixDate(latest)}${stale ? ' · historical dataset' : ' · refreshes every minute'}` : 'No recorded trades for this chain';
        status.classList.toggle('fresh', Boolean(latest && !stale));
        document.getElementById('market-narrative').textContent = act.trades_24h > 0
            ? `${top ? shortSymbol(top.symbol) + ' leads recorded activity. ' : ''}${formatNumber(act.trades_24h, 0)} trades generated ${compactCurrency(act.premium_24h)} in premium over the past 24 hours.`
            : latest ? `The latest recorded trade is from ${formatUnixDate(latest)}. Explore the historical flow for context.` : 'A fresh view, waiting for its first recorded trades.';
        document.getElementById('pulse-grid').innerHTML = `
            <div class="summary-card"><div class="summary-label">7-day notional</div><div class="summary-value">${compactCurrency(act.volume_7d)}</div><div class="summary-subtext">${formatNumber(act.trades_7d, 0)} recorded trades</div></div>
            <div class="summary-card"><div class="summary-label">Average entry tenor</div><div class="summary-value">${dte.avg != null ? dte.avg + 'd' : '—'}</div><div class="summary-subtext">${dte.min != null ? `${dte.min}–${dte.max}d range · 7d` : 'No trades in past 7 days'}</div></div>
            <div class="summary-card"><div class="summary-label">24h vs daily average</div><div class="summary-value" style="color:${volColor}">${volIndicator}</div><div class="summary-subtext">Compared with past 7 days</div></div>
            <div class="summary-card"><div class="summary-label">Open premium</div><div class="summary-value">${compactCurrency(active.premium)}</div><div class="summary-subtext">Recorded unexpired positions</div></div>
        `;
        document.getElementById('pulse-strikes').innerHTML = data.popular_strikes?.length ? `
            <table class="data-table"><thead><tr><th>Asset</th><th>Chain</th><th>Strike</th><th>Type</th><th>Trades</th><th>Notional</th><th>Avg APR</th></tr></thead>
            <tbody>${data.popular_strikes.map(s => `<tr><td><span class="token-badge">${escapeAttr(shortSymbol(s.symbol))}</span></td><td>${chainBadge(s)}</td><td>${formatStrike(s.strike)}</td><td>${s.dominant_type || '—'}</td><td>${s.count}</td><td>${compactCurrency(s.volume)}</td><td>${formatPercentage(s.avg_apr)}</td></tr>`).join('')}</tbody></table>`
            : '<div class="empty-state"><strong>No trending strikes in the past 7 days</strong><p>Use the asset explorer to inspect the historical strike distribution.</p></div>';

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        if (requestChain !== selectedChain) return;
        loading.style.display = 'block';
        loading.textContent = 'Market activity is unavailable. Refresh the page to try again.';
        document.getElementById('observation-status').textContent = 'Activity unavailable · refresh to retry';
    }
}

// ── Premium PnL Chart ──

let pnlDays = 90;
async function loadPnlChart(days) {
    pnlDays = days;
    const loading = document.getElementById('pnl-loading');
    const chart = document.getElementById('pnl-chart');

    // Premium-over-time API treats 0 as "all" via large lookback
    const fetchDays = days > 0 ? days : 365;

    try {
        const resp = await fetch(withChain(`/api/global/premium-over-time?days=${fetchDays}`));
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const dates = data.data.map(d => d.date);
        const cumPremium = data.data.map(d => d.cumulative_premium);
        const cumReturned = data.data.map(d => d.cumulative_returned_premium);
        const dailyPremium = data.data.map(d => d.daily_premium);

        loading.style.display = 'none';
        chart.style.display = 'block';

        const theme = getPlotlyTheme();
        Plotly.newPlot('pnl-chart', [
            { x: dates, y: dailyPremium, type: 'bar', name: 'Daily Premium', marker: { color: 'rgba(103, 153, 126, 0.30)' }, yaxis: 'y2' },
            { x: dates, y: cumPremium, type: 'scatter', mode: 'lines', name: 'Cumulative Premium', line: { color: '#67997e', width: 2.5 } },
            { x: dates, y: cumReturned, type: 'scatter', mode: 'lines', name: 'Returned Position Premium', line: { color: '#b48c52', width: 2, dash: 'dot' } },
        ], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'DM Sans, sans-serif', color: theme.fontColor, size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Cumulative ($)', gridcolor: theme.gridColor, tickfont: { size: 11 }, tickprefix: '$' },
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

    const fetchDays = days > 0 ? days : 365;

    try {
        const resp = await fetch(withChain(`/api/global/put-call-ratio?days=${fetchDays}`));
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const weeks = data.data.map(d => d.week);
        const putPcts = data.data.map(d => d.put_pct);
        const callPcts = data.data.map(d => 100 - d.put_pct);
        const ratios = data.data.map(d => d.ratio);

        loading.style.display = 'none';
        chart.style.display = 'block';

        const theme = getPlotlyTheme();
        Plotly.newPlot('pcr-chart', [
            { x: weeks, y: putPcts, type: 'bar', name: 'Put Volume', marker: { color: 'rgba(186, 112, 104, 0.6)' } },
            { x: weeks, y: callPcts, type: 'bar', name: 'Call Volume', marker: { color: 'rgba(106, 157, 168, 0.6)' } },
            { x: weeks, y: ratios, type: 'scatter', mode: 'lines+markers', name: 'P/C Ratio', line: { color: '#bfa261', width: 2 }, marker: { size: 4 }, yaxis: 'y2' },
        ], {
            barmode: 'stack',
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'DM Sans, sans-serif', color: theme.fontColor, size: 12 },
            margin: { l: 50, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Notional Share (%)', gridcolor: theme.gridColor, tickfont: { size: 11 }, ticksuffix: '%', range: [0, 100] },
            yaxis2: { title: 'P/C Ratio', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11, color: '#bfa261' } },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
    } catch (e) {
        loading.textContent = 'Failed to load put/call ratio: ' + e.message;
    }
}

// ── HYPE Volatility Index ──

async function loadHypeVolatility(days = 365) {
    const loading = document.getElementById('hype-vol-loading');
    const content = document.getElementById('hype-vol-content');
    if (!loading || !content) return;

    try {
        const resp = await fetch(`/api/global/hype-volatility?days=${days}`);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const latest = data.latest || {};
        document.getElementById('hype-vol-summary').innerHTML = `
            <div class="summary-card">
                <div class="summary-label">HYPE Close</div>
                <div class="summary-value">${latest.close != null ? formatCurrency(latest.close) : '—'}</div>
                <div class="summary-subtext">${latest.date || '—'}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">3d RV</div>
                <div class="summary-value">${latest.rv_3d != null ? formatPercentage(latest.rv_3d) : '—'}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">7d RV</div>
                <div class="summary-value">${latest.rv_7d != null ? formatPercentage(latest.rv_7d) : '—'}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">30d RV</div>
                <div class="summary-value">${latest.rv_30d != null ? formatPercentage(latest.rv_30d) : '—'}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">1d Move</div>
                <div class="summary-value">${latest.return_1d_pct != null ? formatPercentage(latest.return_1d_pct) : '—'}</div>
            </div>
        `;

        const series = data.series || [];
        const dates = series.map(d => d.date);
        const rv3 = series.map(d => d.rv_3d);
        const rv7 = series.map(d => d.rv_7d);
        const rv30 = series.map(d => d.rv_30d);
        const close = series.map(d => d.close);

        loading.style.display = 'none';
        content.style.display = 'block';

        const theme = getPlotlyTheme();
        Plotly.newPlot('hype-vol-chart', [
            { x: dates, y: rv3, type: 'scatter', mode: 'lines', name: '3d RV', line: { color: '#ba7068', width: 1.5 } },
            { x: dates, y: rv7, type: 'scatter', mode: 'lines', name: '7d RV', line: { color: '#bfa261', width: 2 } },
            { x: dates, y: rv30, type: 'scatter', mode: 'lines', name: '30d RV', line: { color: '#67997e', width: 2.5 } },
            { x: dates, y: close, type: 'scatter', mode: 'lines', name: 'HYPE Close', line: { color: 'rgba(168, 178, 194, 0.55)', width: 1.5 }, yaxis: 'y2' },
        ], {
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { family: 'DM Sans, sans-serif', color: theme.fontColor, size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 40 },
            xaxis: { showgrid: false, tickfont: { size: 11 } },
            yaxis: { title: 'Realized Vol (%)', gridcolor: theme.gridColor, tickfont: { size: 11 }, ticksuffix: '%' },
            yaxis2: { title: 'Close ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11 }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.08, font: { size: 11 } },
        }, { responsive: true, displayModeBar: false });
    } catch (e) {
        loading.textContent = 'Failed to load HYPE volatility: ' + e.message;
    }
}

// ── Outcomes Breakdown ──

async function loadOutcomes() {
    const loading = document.getElementById('outcomes-loading');
    const content = document.getElementById('outcomes-content');
    try {
        const resp = await fetch(withChain('/api/global/outcomes'));
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
            const rows = outcomesExpanded ? data.by_asset : data.by_asset.slice(0, LIST_PREVIEW_LIMIT);
            document.getElementById('outcomes-by-asset').innerHTML = `
                <h3 class="subsection-title">By Asset</h3>
                <table class="data-table" id="outcomes-asset-table">
                    <thead><tr>
                        <th>Asset</th><th>Chain</th><th data-sort-key="total">Expired</th>
                        <th data-sort-key="assigned">Assigned</th><th data-sort-key="returned">Returned</th>
                        <th data-sort-key="assignedpct">Assign %</th>
                        <th data-sort-key="premium">Premium</th><th data-sort-key="notional">Notional</th>
                    </tr></thead>
                    <tbody>${rows.map(a => `<tr>
                        <td><span class="token-badge ${shortSymbol(a.symbol).toLowerCase()}">${shortSymbol(a.symbol)}</span></td>
                        <td>${chainBadge(a)}</td>
                        <td data-sort-key="total" data-sort-value="${a.total}">${a.total}</td>
                        <td data-sort-key="assigned" data-sort-value="${a.assigned}">${a.assigned}</td>
                        <td data-sort-key="returned" data-sort-value="${a.returned}">${a.returned}</td>
                        <td data-sort-key="assignedpct" data-sort-value="${a.assigned_pct}">${formatPercentage(a.assigned_pct)}</td>
                        <td data-sort-key="premium" data-sort-value="${a.total_premium}">${compactCurrency(a.total_premium)}</td>
                        <td data-sort-key="notional" data-sort-value="${a.total_notional}">${compactCurrency(a.total_notional)}</td>
                    </tr>`).join('')}</tbody>
                </table>
                ${data.by_asset.length > LIST_PREVIEW_LIMIT ? `
                    <div class="compact-list-actions">
                        <button class="terminal-button small" type="button" onclick="outcomesExpanded = !outcomesExpanded; loadOutcomes();">${outcomesExpanded ? 'Show fewer' : `Show all ${data.by_asset.length}`}</button>
                    </div>
                ` : ''}
            `;
            setupSortableTable('outcomes-asset-table');
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = 'Failed to load outcomes: ' + e.message;
    }
}

// ── Top Positions for Next Expiry ──

async function loadNextExpiryPositions() {
    const requestChain = selectedChain;
    const loading = document.getElementById('next-expiry-loading');
    const content = document.getElementById('next-expiry-content');
    try {
        const resp = await fetch(withChain('/api/global/next-expiry-positions?limit=5'));
        const data = await resp.json();
        if (requestChain !== selectedChain) return;
        if (!data.success) throw new Error(data.error);

        if (!data.next_expiry || !data.positions.length) {
            content.style.display = 'none';
            loading.style.display = 'block';
            loading.innerHTML = '<div class="empty-state"><strong>No upcoming expiries recorded</strong><p>There are no future settlements in the selected dataset. Explore historical expiries below.</p><a href="#act-explore">Open the expiry explorer →</a></div>';
            setHero('hero-next-expiry', '—', 'None recorded');
            return;
        }

        const expiryDate = formatUnixDate(data.next_expiry);
        const totalNotional = data.positions.reduce((s, p) => s + (p.total_notional || 0), 0);
        const totalPremium = data.positions.reduce((s, p) => s + (p.total_premium || 0), 0);

        // Populate hero next-expiry KPI
        populateGlobalHeroNextExpiry(data.next_expiry, data.total_orders);

        document.getElementById('next-expiry-header').innerHTML = `
            <div class="summary-card">
                <div class="summary-label">Next Expiry</div>
                <div class="summary-value">${expiryDate}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Top 5 groups · notional</div>
                <div class="summary-value">${compactCurrency(totalNotional)}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Top 5 groups · premium</div>
                <div class="summary-value">${compactCurrency(totalPremium)}</div>
            </div>
        `;

        document.getElementById('next-expiry-body').innerHTML = data.positions.map(p => `<tr>
            <td><span class="token-badge ${shortSymbol(p.symbol).toLowerCase()}">${shortSymbol(p.symbol)}</span></td>
            <td>${chainBadge(p)}</td>
            <td>${formatStrike(p.strike)}</td>
            <td>${p.dominant_type}</td>
            <td>${p.order_count}</td>
            <td>${compactCurrency(p.total_notional)}</td>
            <td>${compactCurrency(p.total_premium)}</td>
            <td>${p.avg_apr != null ? formatPercentage(p.avg_apr) : '—'}</td>
        </tr>`).join('');

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        if (requestChain !== selectedChain) return;
        loading.textContent = 'Failed to load next expiry positions: ' + e.message;
    }
}

// ── Hero KPI population ──

function setHero(id, value, sub) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
    if (sub !== undefined) {
        const subEl = document.getElementById(id + '-sub');
        if (subEl) subEl.innerHTML = sub || '&nbsp;';
    }
}

function populateGlobalHero({ act, top, active, volIndicator, volColor }) {
    setHero('hero-tvl', compactCurrency(active.notional),
        `${formatNumber(active.count, 0)} open positions`);
    setHero('hero-volume-24h', compactCurrency(act.volume_24h),
        `<span style="color: ${volColor};">${volIndicator}</span> vs 7d avg`);
    setHero('hero-premium-24h', compactCurrency(act.premium_24h),
        `${formatNumber(act.trades_24h, 0)} trades`);
    setHero('hero-active', formatNumber(active.count, 0),
        `${compactCurrency(active.notional)} notional`);
    if (top) {
        setHero('hero-hot', shortSymbol(top.symbol),
            `${chainLabel(top)} · ${formatNumber(top.trades, 0)} trades · ${compactCurrency(top.volume)}`);
    } else {
        setHero('hero-hot', '—', 'No 24h activity');
    }
}

function populateGlobalHeroNextExpiry(expiryTs, positionCount) {
    if (!expiryTs) return;
    const days = Math.max(0, Math.round((expiryTs * 1000 - Date.now()) / (1000 * 60 * 60 * 24)));
    const dayLabel = days === 0 ? 'today' : days === 1 ? '1 day' : `${days} days`;
    setHero('hero-next-expiry', dayLabel,
        `${formatUnixDate(expiryTs)} · ${formatNumber(positionCount, 0)} positions`);
}

// ── Unified time-range selector ──

function setTimeRange(days) {
    document.querySelectorAll('#time-range-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.rangeDays) === days);
    });
    // Cascade to all three historical sections
    loadOverview(days);
    loadPnlChart(days);
    loadPutCallRatio(days);
    loadHypeVolatility(days > 0 ? days : 365);
}

function loadGlobalDashboard() {
    return Promise.allSettled([
        loadNextExpiryPositions(),
        loadMarketPulse(),
        loadRecent(),
        loadAssets(),
        loadExpiryExplorer(),
        loadFlowChart(),
    ]).then(() => {
        document.querySelectorAll('.chart-container .js-plotly-plot').forEach(el => {
            Plotly.Plots.resize(el);
        });
    });
}

function setChainFilter(chain) {
    if (selectedChain === (chain || 'all')) return;
    selectedChain = chain || 'all';
    ['pulse', 'recent', 'assets', 'expiry', 'next-expiry'].forEach(prefix => {
        const content = document.getElementById(prefix + '-content');
        const loading = document.getElementById(prefix + '-loading');
        if (content) content.style.display = 'none';
        if (loading) { loading.style.display = 'block'; loading.textContent = 'Loading selected chain…'; }
    });
    document.querySelectorAll('#hero-kpis .hero-kpi-value').forEach(el => { el.textContent = '—'; });
    document.querySelectorAll('#hero-kpis .hero-kpi-sub').forEach(el => { el.textContent = ''; });
    document.getElementById('observation-status').textContent = 'Checking selected chain…';
    document.getElementById('pulse-strikes').replaceChildren();
    selectedAsset = null;
    selectedAssetChain = null;
    selectedExpiry = null;
    selectedExplorerExpiry = null;
    assetsExpanded = false;
    expiryExpanded = false;
    detailExpiryExpanded = false;
    outcomesExpanded = false;
    document.querySelectorAll('#chain-filter-tabs .tab-button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.chain === selectedChain);
    });
    closeAssetDetail();
    loadGlobalDashboard();
}

// ── Scroll-spy for sticky act-nav ──

function initActNavScrollSpy() {
    const navLinks = document.querySelectorAll('.act-nav a[data-act]');
    if (!navLinks.length) return;
    const targets = Array.from(navLinks)
        .map(a => document.getElementById(a.dataset.act))
        .filter(Boolean);
    if (!targets.length) return;

    const setActive = (id) => {
        navLinks.forEach(a => a.classList.toggle('active', a.dataset.act === id));
    };

    const observer = new IntersectionObserver((entries) => {
        // Pick the entry closest to the top that's currently intersecting
        const visible = entries
            .filter(e => e.isIntersecting)
            .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length) setActive(visible[0].target.id);
    }, { rootMargin: '-80px 0px -60% 0px', threshold: 0 });

    targets.forEach(t => observer.observe(t));

    // Also handle smooth scroll behavior so anchor jumps account for sticky nav
    navLinks.forEach(a => {
        a.addEventListener('click', (e) => {
            const target = document.getElementById(a.dataset.act);
            if (!target) return;
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            history.replaceState(null, '', '#' + a.dataset.act);
        });
    });
}

// ── Init ──

document.addEventListener('DOMContentLoaded', () => {
    loadGlobalDashboard();

    // Unified time-range selector — cascades to Overview, PnL, Put/Call
    const timeRangeTabs = document.getElementById('time-range-tabs');
    if (timeRangeTabs) {
        timeRangeTabs.addEventListener('click', e => {
            const btn = e.target.closest('.tab-button');
            if (!btn) return;
            setTimeRange(parseInt(btn.dataset.rangeDays));
        });
    }

    const chainTabs = document.getElementById('chain-filter-tabs');
    if (chainTabs) {
        chainTabs.addEventListener('click', e => {
            const btn = e.target.closest('.tab-button');
            if (!btn) return;
            setChainFilter(btn.dataset.chain || 'all');
        });
    }

    const assetToggle = document.getElementById('asset-list-toggle');
    if (assetToggle) {
        assetToggle.addEventListener('click', () => {
            assetsExpanded = !assetsExpanded;
            renderAssetCards();
        });
    }

    const assetGrid = document.getElementById('asset-grid');
    if (assetGrid) {
        assetGrid.addEventListener('click', event => {
            const card = event.target.closest('.asset-card[data-asset]');
            if (!card) return;
            showAssetDetail(card.dataset.asset, { chainId: chainValueToId(card.dataset.chainId) });
        });
    }

    document.getElementById('asset-search').addEventListener('input', renderAssetCards);
    document.getElementById('asset-grid').addEventListener('keydown', event => {
        if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.asset-card')) { event.preventDefault(); event.target.click(); }
    });
    document.getElementById('flow-range-tabs').addEventListener('click', e => {
        const button = e.target.closest('[data-flow-days]');
        if (!button) return; flowDays = Number(button.dataset.flowDays);
        document.querySelectorAll('[data-flow-days]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); });
        loadFlowChart();
    });
    initActNavScrollSpy();
    initStrikeLens();

    document.getElementById('detail-close').addEventListener('click', closeAssetDetail);
    const sidepanelBackdrop = document.getElementById('sidepanel-backdrop');
    if (sidepanelBackdrop) {
        sidepanelBackdrop.addEventListener('click', closeAssetDetail);
    }
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && document.body.classList.contains('sidepanel-open')) {
            closeAssetDetail();
        }
    });

    // Auto-refresh market pulse and recent activity every 60 seconds
    setInterval(() => {
        loadMarketPulse();
        loadRecent();
    }, 60000);

    // Carousel arrows
    function wireCarousel(trackId, leftId, rightId) {
        const t = document.getElementById(trackId);
        const step = 240;

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

// Overview context uses the same recorded volume endpoint as the asset charts.
let flowDays = 365;
let flowRequest = 0;
async function loadFlowChart() {
    const version = ++flowRequest;
    const days = flowDays;
    const loading = document.getElementById('flow-loading');
    const chart = document.getElementById('flow-chart');
    loading.style.display = 'block'; loading.textContent = 'Reading historical flow…';
    chart.style.display = 'none';
    document.getElementById('flow-total').textContent = '—';
    document.getElementById('flow-period').textContent = days === 365 ? '/ past year' : `/ past ${days} days`;
    document.getElementById('flow-sample').textContent = 'Daily buckets · UTC';
    try {
        const response = await fetch(withChain(`/api/global/volume?days=${days}`));
        const data = await response.json();
        if (version !== flowRequest) return;
        if (!response.ok || !data.success) throw new Error('Flow unavailable');
        const rows = data.data || [];
        document.getElementById('flow-total').textContent = compactCurrency(rows.reduce((sum, row) => sum + row.volume, 0), 1);
        if (!rows.length) {
            loading.innerHTML = '<div class="empty-state"><strong>No recorded flow in this window</strong><p>Try a longer time window or another chain to explore available history.</p></div>';
            return;
        }
        const tradeCount = rows.reduce((sum, row) => sum + row.trade_count, 0);
        document.getElementById('flow-sample').textContent = `${formatNumber(tradeCount, 0)} executions · UTC`;
        if (typeof Plotly === 'undefined') {
            loading.textContent = 'Chart library unavailable. The recorded total is shown above; refresh to retry.';
            return;
        }
        const theme = getPlotlyTheme();
        const chains = new Map();
        (data.by_chain || []).forEach(row => {
            const name = chainLabel(row);
            if (!chains.has(name)) chains.set(name, {x: [], y: [], color: Number(row.chain_id) === 1 ? '#9aaaca' : '#67997e'});
            chains.get(name).x.push(row.date); chains.get(name).y.push(row.volume);
        });
        const traces = Array.from(chains, ([name, series]) => ({type: 'bar', name, x: series.x, y: series.y, marker: {color: series.color}, hovertemplate: '%{x|%b %d, %Y}<br>$%{y:,.0f}<extra>%{fullData.name}</extra>'}));
        if (!traces.length) traces.push({type:'bar', name:'Recorded notional', x: rows.map(r => r.date), y: rows.map(r => r.volume), marker:{color:'#67997e'}});
        loading.style.display = 'none'; chart.style.display = 'block';
        await Plotly.react(chart, traces, {
            barmode: 'stack', bargap: .16, showlegend: false,
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: {family:'DM Sans, sans-serif', size:10, color:theme.fontColor},
            margin: {l:47, r:5, t:12, b:28}, height:215,
            xaxis: {type:'date', showgrid:false, tickformat:'%b %y', nticks:5, fixedrange:true},
            yaxis: {gridcolor:theme.gridColor, zeroline:false, tickprefix:'$', tickformat:'~s', nticks:4, fixedrange:true},
            hoverlabel: {bgcolor:theme.annotationBg, bordercolor:theme.gridColor, font:{color:theme.fontColor}},
        }, {responsive:true, displayModeBar:false});
    } catch (_) {
        if (version !== flowRequest) return;
        chart.style.display = 'none'; loading.style.display = 'block';
        loading.innerHTML = '<div class="empty-state"><strong>Historical flow is unavailable</strong><p>Choose a time window to retry, or refresh the page.</p></div>';
    }
}
