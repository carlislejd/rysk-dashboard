// Dashboard JavaScript
// Shared utilities (formatNumber, formatCurrency, badges, sorting, etc.) are in utils.js

function setupSortableOpenPositionsTable() {
    setupSortableTable('current-open-positions-table');
}

function setupSortablePositionsDetailTable() {
    setupSortableTable('positions-detail-asset-table');
}

function renderOpenPositionsPage(page) {
    if (page !== undefined) openPositionsPage = page;
    const container = document.getElementById('open-positions-container');
    if (!container) return;

    if (openPositionsData.length === 0) {
        container.innerHTML = '<p class="empty-state">No open option positions right now.</p>';
        return;
    }

    const total = openPositionsData.length;
    const totalPages = Math.ceil(total / OPEN_POSITIONS_PER_PAGE);
    openPositionsPage = Math.max(1, Math.min(openPositionsPage, totalPages));
    const start = (openPositionsPage - 1) * OPEN_POSITIONS_PER_PAGE;
    const pageData = openPositionsData.slice(start, start + OPEN_POSITIONS_PER_PAGE);

    let html = `
        <table id="current-open-positions-table" class="data-table">
            <thead>
                <tr>
                    <th data-sort-key="symbol">Symbol</th>
                    <th data-sort-key="strategy">Strategy</th>
                    <th data-sort-key="side">Side</th>
                    <th data-sort-key="type">Type</th>
                    <th data-sort-key="created">Created</th>
                    <th data-sort-key="expiry">Expiry</th>
                    <th data-sort-key="quantity">Quantity</th>
                    <th data-sort-key="strike">Strike</th>
                    <th data-sort-key="premium">Premium</th>
                    <th data-sort-key="apr">APR</th>
                    <th data-sort-key="status">Status</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const pos of pageData) {
        html += `
            <tr>
                <td data-sort-key="symbol" data-sort-value="${pos.symbol || ''}">${pos.symbol || '—'}</td>
                <td data-sort-key="strategy" data-sort-value="${pos.strategy || ''}">${strategyBadge(pos)}</td>
                <td data-sort-key="side" data-sort-value="${pos.side || ''}">${sideBadge(pos.side)}</td>
                <td data-sort-key="type" data-sort-value="${pos.type || ''}">${pos.type || '—'}</td>
                <td data-sort-key="created" data-sort-value="${pos.created_at || ''}">${formatDateLabel(pos.created_at)}</td>
                <td data-sort-key="expiry" data-sort-value="${pos.expiry_date || ''}">${formatDateLabel(pos.expiry_date)}</td>
                <td data-sort-key="quantity" data-sort-value="${pos.quantity ?? ''}">${formatNumber(pos.quantity, 4)}</td>
                <td data-sort-key="strike" data-sort-value="${pos.strike ?? ''}">${formatStrike(pos.strike)}</td>
                <td data-sort-key="premium" data-sort-value="${pos.premium ?? ''}">${formatCurrency(pos.premium || 0)}</td>
                <td data-sort-key="apr" data-sort-value="${pos.apr ?? ''}">${formatPercentage(pos.apr)}</td>
                <td data-sort-key="status" data-sort-value="${pos.status || ''}">${statusBadge(pos.status)}</td>
            </tr>
        `;
    }

    html += '</tbody></table>';

    if (totalPages > 1) {
        html += `
            <div class="pager">
                <button class="pager-btn" onclick="renderOpenPositionsPage(${openPositionsPage - 1})" ${openPositionsPage <= 1 ? 'disabled' : ''}>Prev</button>
                <span class="pager-info">Page ${openPositionsPage} of ${totalPages} (${total} positions)</span>
                <button class="pager-btn" onclick="renderOpenPositionsPage(${openPositionsPage + 1})" ${openPositionsPage >= totalPages ? 'disabled' : ''}>Next</button>
            </div>
        `;
    }

    container.innerHTML = html;
    setupSortableOpenPositionsTable();
}

let defaultAccount = '';
let currentAccount = '';
let accountInputEl = null;
let accountStatusEl = null;
let accountDisplayEl = null;
let splashScreenEl = null;
let mainContentEl = null;
let splashAccountInputEl = null;
let splashLaunchEl = null;
let splashTypingEl = null;
let splashErrorEl = null;
let splashTypingTimer = null;

function buildUrl(path, params = {}) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            searchParams.set(key, value);
        }
    });
    const query = searchParams.toString();
    return query ? `${path}?${query}` : path;
}

function fetchWithAccount(path, params = {}) {
    const finalParams = { ...params };
    if (currentAccount) {
        finalParams.address = currentAccount;
    }
    return fetch(buildUrl(path, finalParams));
}

function updateAccountUI(address) {
    const display = address ? address : 'Not set';
    if (accountDisplayEl) {
        accountDisplayEl.textContent = display;
    }
    if (accountInputEl && document.activeElement !== accountInputEl) {
        accountInputEl.value = address || '';
    }
}

function setAccountStatus(message = '', isError = false) {
    if (!accountStatusEl) return;
    accountStatusEl.textContent = message || '';
    accountStatusEl.style.color = isError ? '#ef7070' : '#71717a';
}

let positionsAssetSummary = [];
let openPositionsData = [];
let openPositionsPage = 1;
const OPEN_POSITIONS_PER_PAGE = 15;

// Simple positions data cache for health/PnL rendering
const _positions_cache = new Map();
let selectedAssetSymbol = null;
let selectedAssetExpiry = '';
let historyDataCache = null;
let historyDataTimestamp = null;
let historyModalInitialized = false;

function getTokenClass(token) {
    return token.toLowerCase();
}

// Load positions
async function loadPositions() {
    const loading = document.getElementById('positions-loading');
    const content = document.getElementById('positions-content');
    const error = document.getElementById('positions-error');
    const notConfigured = document.getElementById('positions-not-configured');
    const previousAsset = selectedAssetSymbol;

    loading.style.display = 'block';
    if (error) error.style.display = 'none';

    try {
        const response = await fetchWithAccount('/api/positions');
        const data = await response.json();

        loading.style.display = 'none';

        if (!data.success) {
            error.textContent = data.error || 'Failed to load positions';
            error.style.display = 'block';
            return;
        }

        notConfigured.style.display = 'none';
        error.style.display = 'none';
        if (data.account && data.account !== currentAccount) {
            currentAccount = data.account;
            try {
                localStorage.setItem('dashboardAccount', currentAccount || '');
            } catch (_) {
                // ignore storage errors
            }
            updateAccountUI(currentAccount);
        }
        const positions = data.positions || {};
        const openPositions = positions.open_positions || [];
        const assetSummary = positions.asset_summary || [];
        const summary = positions.summary || {};

        let html = '';

        if (Object.keys(summary).length > 0) {
            const weightedApr = summary.open_weighted_apr;
            const hasWeightedApr = weightedApr !== null && weightedApr !== undefined;
            const aprCard = hasWeightedApr ? `
                <div class="summary-card">
                    <span class="summary-label">Portfolio APR</span>
                    <span class="summary-value">${formatPercentage(weightedApr)}</span>
                </div>
            ` : '';

            html += `
                <div class="summary-grid">
                    <div class="summary-card">
                        <span class="summary-label">Open Positions</span>
                        <span class="summary-value">${formatNumber(summary.open_count || 0, 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Open Notional</span>
                        <span class="summary-value">${formatCurrency(summary.open_notional_total || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Net Premium</span>
                        <span class="summary-value">${formatCurrency(summary.open_premium_total || 0)}</span>
                    </div>
                    ${aprCard}
                </div>
            `;
        }

        const openTotalCount = summary.open_count || openPositions.length;
        const openTitleCount = openPositions.length === openTotalCount
            ? openPositions.length
            : `${openPositions.length} of ${openTotalCount}`;

        if (assetSummary.length > 0) {
            html += '<div class="asset-summary-grid">';
            for (const asset of assetSummary) {
                html += `
                    <div class="asset-card" data-asset="${asset.symbol}">
                        <div class="asset-card-header">
                            <span class="asset-symbol">${asset.symbol}</span>
                            <span class="asset-count">${formatNumber(asset.count, 0)} positions</span>
                        </div>
                        <div class="asset-card-metrics">
                            <div class="asset-metric">
                                <span class="asset-metric-label">Quantity</span>
                                <span class="asset-metric-value">${formatNumber(asset.quantity_total, 4)}</span>
                            </div>
                            <div class="asset-metric">
                                <span class="asset-metric-label">Notional</span>
                                <span class="asset-metric-value">${formatCurrency(asset.notional_total || 0)}</span>
                            </div>
                            <div class="asset-metric">
                                <span class="asset-metric-label">Avg APR</span>
                                <span class="asset-metric-value">${asset.avg_apr ? formatPercentage(asset.avg_apr) : '—'}</span>
                            </div>
                        </div>
                    </div>
                `;
            }
            html += '</div>';
        }

        html += `
            <div id="positions-detail" class="positions-detail" style="display:none;">
                <div class="positions-detail-header">
                    <h3 id="positions-detail-title">Asset Detail</h3>
                    <button id="positions-detail-close" class="detail-close">Close</button>
                </div>
                <div id="positions-detail-filters" class="positions-detail-filters"></div>
                <div id="positions-detail-summary" class="positions-detail-summary"></div>
                <div id="positions-heatmap" class="positions-heatmap"></div>
                <div id="positions-detail-table" class="positions-detail-table"></div>
            </div>
        `;

        html += `<h3 class="subsection-title">Current Open Option Positions (${openTitleCount})</h3>`;
        html += '<div id="open-positions-container"></div>';

        content.innerHTML = html;
        content.style.display = 'block';

        positionsAssetSummary = assetSummary;
        openPositionsData = openPositions;
        openPositionsPage = 1;
        renderOpenPositionsPage();
        setupAssetSummaryHandlers();

        // Cache for portfolio health rendering
        _positions_cache.set(currentAccount.toLowerCase(), {
            open_positions: openPositions,
            summary: summary,
            asset_summary: assetSummary,
        });

        if (previousAsset && assetSummary.some(a => a.symbol === previousAsset)) {
            showAssetPositions(previousAsset);
        } else {
            selectedAssetSymbol = null;
            selectedAssetExpiry = '';
            const detail = document.getElementById('positions-detail');
            if (detail) detail.style.display = 'none';
        }
    } catch (err) {
        loading.style.display = 'none';
        error.textContent = 'Error loading positions: ' + err.message;
        error.style.display = 'block';
    }
}

// Load history
async function loadHistory() {
    const loading = document.getElementById('history-loading');
    const content = document.getElementById('history-content');
    const error = document.getElementById('history-error');
    const notConfigured = document.getElementById('history-not-configured');
    const detailButton = document.getElementById('history-detail-button');

    if (detailButton && !historyDataCache) {
        detailButton.disabled = true;
        detailButton.textContent = '🔍 Deep Dive (Loading...)';
    }
    try {
        const response = await fetchWithAccount('/api/history');
        const data = await response.json();

        loading.style.display = 'none';

        if (!data.success) {
            error.textContent = data.error || 'Failed to load history';
            error.style.display = 'block';
            historyDataCache = null;
            return;
        }

        notConfigured.style.display = 'none';
        error.style.display = 'none';

        if (data.account && data.account !== currentAccount) {
            currentAccount = data.account;
            try {
                localStorage.setItem('dashboardAccount', currentAccount || '');
            } catch (_) {
                // ignore storage errors
            }
            updateAccountUI(currentAccount);
        }

        const history = data.history || {};
        const trades = history.trades || [];
        const expiredPositions = history.expired_positions || [];
        const summary = history.summary || {};

        historyDataCache = history;
        historyDataTimestamp = new Date();

        if (detailButton) {
            const totalExpired = summary.expired_count || expiredPositions.length || 0;
            detailButton.disabled = totalExpired === 0;
            if (totalExpired > 0) {
                detailButton.textContent = `🔍 Deep Dive (${formatNumber(totalExpired, 0)} positions)`;
            } else {
                detailButton.textContent = '🔍 Deep Dive (No history yet)';
            }
        }

        let html = '';

        if (Object.keys(summary).length > 0) {
            const assignedSubtext = summary.assigned_notional_total ? `<span class="summary-subtext">${formatCurrency(summary.assigned_notional_total || 0)} Notional Assigned</span>` : '';

            html += `
                <div class="summary-grid">
                    <div class="summary-card">
                        <span class="summary-label">Expired Positions</span>
                        <span class="summary-value">${formatNumber(summary.expired_count || expiredPositions.length || 0, 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Net Premium</span>
                        <span class="summary-value">${formatCurrency(summary.net_premium || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Total Notional</span>
                        <span class="summary-value">${formatCurrency(summary.total_notional || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Assigned Positions</span>
                        <span class="summary-value">${formatNumber(summary.assigned_count || 0, 0)}</span>
                        ${assignedSubtext}
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Returned Positions</span>
                        <span class="summary-value">${formatNumber(summary.returned_count || 0, 0)}</span>
                    </div>
                </div>
            `;
        }

        const assetOutcomes = summary.asset_outcomes || [];
        if (assetOutcomes.length > 0) {
            html += `<h3 class="subsection-title">Expiry Outcomes by Asset (${assetOutcomes.length})</h3>`;
            html += `<div class="history-actions" style="justify-content: flex-start; margin-bottom: 6px;">`;
            html += `<button id="outcomes-show-all" class="terminal-button">Show All Assets</button>`;
            html += `</div>`;
            html += `<div class="asset-summary-grid outcome-grid">`;
            for (const outcome of assetOutcomes) {
                const symbol = outcome.symbol || '—';
                const totalPositions = formatNumber(outcome.total_positions || 0, 0);
                const assignedCount = formatNumber(outcome.assigned_count || 0, 0);
                const assignedNotional = formatCurrency(outcome.assigned_notional || 0);

                html += `
                    <div class="asset-card outcome-card">
                        <span class="asset-summary-symbol token-badge ${getTokenClass(symbol)}">${symbol}</span>
                        <span class="asset-summary-count">${totalPositions} Expired</span>
                        <span class="asset-summary-notional">${assignedCount} Assigned · ${assignedNotional}</span>
                    </div>
                `;
            }
            html += `</div>`;
        }

        html += `
            <div id="history-apr-chart" class="chart-card" style="display:none; margin-top: 0; margin-bottom: 10px; width:100%;">
                <h3 class="subsection-title" id="history-apr-chart-title">APR Scatter</h3>
                <div id="history-apr-chart-plot" style="height:320px; width:100%;"></div>
            </div>
            <div id="expired-section"></div>
        `;

        content.innerHTML = html;
        content.style.display = 'block';
        renderExpiredSection(expiredPositions, summary);
        renderAprChart(expiredPositions, null);
        setupOutcomeFilters(expiredPositions, summary);
    } catch (err) {
        loading.style.display = 'none';
        error.textContent = 'Error loading history: ' + err.message;
        error.style.display = 'block';
        historyDataCache = null;
        historyDataTimestamp = null;
        if (detailButton) {
            detailButton.disabled = true;
            detailButton.textContent = '🔍 Deep Dive (Error)';
        }
    }
}

function buildExpiredSection(expiredPositions, summary, filterSymbol = null, page = 1, pageSize = 50) {
    const totalCount = summary.expired_count || expiredPositions.length;
    const symbolUpper = filterSymbol ? String(filterSymbol).toUpperCase() : null;
    const filtered = symbolUpper
        ? expiredPositions.filter(pos => (pos.symbol || '').toUpperCase() === symbolUpper)
        : expiredPositions;

    const filteredCount = filtered.length;
    const titleCount = filteredCount === totalCount
        ? filteredCount
        : `${filteredCount} of ${totalCount}${symbolUpper ? ` · ${symbolUpper}` : ''}`;

    if (filteredCount === 0) {
        return `<h3 class="subsection-title">Expired Option Positions (${titleCount})</h3><p class="empty-state">No expired positions yet.</p>`;
    }

    const totalPages = Math.max(1, Math.ceil(filteredCount / pageSize));
    const currentPage = Math.min(Math.max(page, 1), totalPages);
    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = Math.min(startIdx + pageSize, filteredCount);
    const pageData = filtered.slice(startIdx, endIdx);

    let html = `<h3 class="subsection-title">Expired Option Positions (${titleCount})</h3>`;

    if (totalPages > 1) {
        html += `
            <div class="pager">
                <button class="pager-btn" data-page="${currentPage - 1}" ${currentPage === 1 ? 'disabled' : ''}>Prev</button>
                <span class="pager-info">Page ${currentPage} / ${totalPages}</span>
                <button class="pager-btn" data-page="${currentPage + 1}" ${currentPage === totalPages ? 'disabled' : ''}>Next</button>
            </div>
        `;
    }

    html += `
        <table class="data-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Symbol</th>
                    <th>Strategy</th>
                    <th>Type</th>
                    <th>Side</th>
                    <th>Quantity</th>
                    <th>Strike</th>
                    <th>Premium</th>
                    <th>Outcome</th>
                    <th>APR</th>
                    <th>Expiry</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const position of pageData) {
        let outcomeHtml = formatPositionOutcome(position);
        if (position.expiry_price !== null && position.expiry_price !== undefined) {
            const expiryDecimals = position.expiry_price >= 1000 ? 0 : position.expiry_price >= 1 ? 2 : 6;
            outcomeHtml += `<div class="table-subtext">Expiry ${formatCurrency(position.expiry_price, expiryDecimals)}</div>`;
        }

        html += `
            <tr>
                <td>${formatDateLabel(position.created_at)}</td>
                <td>${position.symbol || '—'}</td>
                <td>${strategyBadge(position)}</td>
                <td>${position.type || '—'}</td>
                <td>${sideBadge(position.side)}</td>
                <td>${formatNumber(position.quantity, 4)}</td>
                <td>${formatStrike(position.strike)}</td>
                <td>${formatCurrency(position.premium || 0)}</td>
                <td>${outcomeHtml}</td>
                <td>${formatPercentage(position.apr)}</td>
                <td>${formatDateLabel(position.expiry_date)} ${statusBadge(position.status)}</td>
            </tr>
        `;
    }

    html += '</tbody></table>';

    if (totalPages > 1) {
        html += `
            <div class="pager bottom">
                <button class="pager-btn" data-page="${currentPage - 1}" ${currentPage === 1 ? 'disabled' : ''}>Prev</button>
                <span class="pager-info">Page ${currentPage} / ${totalPages}</span>
                <button class="pager-btn" data-page="${currentPage + 1}" ${currentPage === totalPages ? 'disabled' : ''}>Next</button>
            </div>
        `;
    }

    return html;
}

function renderExpiredSection(expiredPositions, summary, filterSymbol = null, page = 1) {
    const container = document.getElementById('expired-section');
    if (!container) return;
    container.innerHTML = buildExpiredSection(expiredPositions, summary, filterSymbol, page);

    // Attach pager handlers
    container.querySelectorAll('.pager-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetPage = Number(btn.getAttribute('data-page'));
            if (!Number.isFinite(targetPage)) return;
            renderExpiredSection(expiredPositions, summary, filterSymbol, targetPage);
        });
    });
}

function setupOutcomeFilters(expiredPositions, summary) {
    const cards = document.querySelectorAll('.outcome-card');
    const allButton = document.getElementById('outcomes-show-all');

    const clearSelection = () => {
        cards.forEach(card => card.classList.remove('selected'));
    };

    if (allButton) {
        allButton.addEventListener('click', () => {
            clearSelection();
            renderExpiredSection(expiredPositions, summary, null, 1);
            renderAprChart(expiredPositions, null);
        });
    }

    cards.forEach(card => {
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => {
            clearSelection();
            card.classList.add('selected');
            const symbol = card.querySelector('.asset-summary-symbol')?.textContent || '';
            renderExpiredSection(expiredPositions, summary, symbol, 1);
            renderAprChart(expiredPositions, symbol);
        });
    });
}

function renderAprChart(expiredPositions, filterSymbol = null) {
    const container = document.getElementById('history-apr-chart');
    const plot = document.getElementById('history-apr-chart-plot');
    const titleEl = document.getElementById('history-apr-chart-title');
    if (!container || !plot || !titleEl || typeof Plotly === 'undefined') return;

    const symbolUpper = filterSymbol ? String(filterSymbol).toUpperCase() : null;
    const filtered = symbolUpper
        ? expiredPositions.filter(pos => (pos.symbol || '').toUpperCase() === symbolUpper)
        : expiredPositions;

    if (!filtered.length) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';
    plot.style.width = '100%';
    titleEl.textContent = `APR Scatter${symbolUpper ? ` — ${symbolUpper}` : ''}`;

    const points = [];
    let maxNotional = 0;
    filtered.forEach(pos => {
        if (pos.apr === null || pos.apr === undefined) return;
        const apr = Number(pos.apr);
        const date = pos.created_at || pos.created_at_iso || '';
        const notional = Number(pos.notional || ((pos.quantity || 0) * (pos.strike || 0)));
        maxNotional = Math.max(maxNotional, notional);
        points.push({
            x: date,
            y: apr,
            notional,
            symbol: pos.symbol || '—',
            strike: pos.strike,
            qty: pos.quantity,
            premium: pos.premium,
            outcome: pos.outcome || '—',
            expiry: pos.expiry_date || '',
        });
    });

    // Keep date axis stable and full-range on first render.
    points.sort((a, b) => {
        const ta = Date.parse(a.x) || 0;
        const tb = Date.parse(b.x) || 0;
        return ta - tb;
    });

    if (!points.length) {
        container.style.display = 'none';
        return;
    }

    const sizes = points.map(p => {
        if (maxNotional <= 0) return 8;
        const ratio = p.notional / maxNotional;
        return Math.max(8, Math.min(28, 6 + ratio * 22));
    });
    const opacities = points.map(p => {
        if (maxNotional <= 0) return 0.6;
        const ratio = p.notional / maxNotional;
        return Math.max(0.5, Math.min(0.9, 0.5 + ratio * 0.4));
    });

    const hover = points.map(p => {
        return [
            `Symbol: ${p.symbol}`,
            `Date: ${p.x}`,
            `APR: ${formatPercentage(p.y)}`,
            `Notional: ${formatCurrency(p.notional || 0)}`,
            `Strike: ${formatStrike(p.strike || 0)}`,
            `Qty: ${formatNumber(p.qty, 4)}`,
            `Premium: ${formatCurrency(p.premium || 0)}`,
            `Outcome: ${p.outcome}`,
            `Expiry: ${p.expiry}`
        ].join('<br>');
    });

    const trace = {
        type: 'scatter',
        mode: 'markers',
        x: points.map(p => p.x),
        y: points.map(p => p.y),
        marker: {
            color: '#34d399',
            size: sizes,
            opacity: opacities
        },
        text: hover,
        hovertemplate: '%{text}<extra></extra>',
        name: 'APR'
    };

    const avgApr = points.reduce((sum, p) => sum + p.y, 0) / points.length;

    const layout = {
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#71717a', family: 'Inter, system-ui, sans-serif' },
        margin: { l: 60, r: 20, t: 30, b: 60 },
        xaxis: {
            title: 'Date',
            color: '#52525b',
            gridcolor: 'rgba(255,255,255,0.06)',
            type: 'date'
        },
        yaxis: {
            title: 'APR (%)',
            color: '#52525b',
            gridcolor: 'rgba(255,255,255,0.06)'
        },
        showlegend: true,
        legend: {
            bgcolor: 'rgba(0,0,0,0)',
            bordercolor: 'rgba(255,255,255,0.06)',
            borderwidth: 1,
            font: { color: '#71717a' }
        }
    };

    Plotly.newPlot(plot, [trace, {
        type: 'scatter',
        mode: 'lines',
        x: [points[0].x, points[points.length - 1].x],
        y: [avgApr, avgApr],
        line: { color: '#f59e0b', dash: 'dash' },
        name: `Avg APR ${formatPercentage(avgApr)}`
    }], layout, { displayModeBar: false, responsive: true }).then(() => {
        Plotly.Plots.resize(plot);
    });
}

function initHistoryModal() {
    if (historyModalInitialized) return;
    const modal = document.getElementById('history-modal');
    const openButton = document.getElementById('history-detail-button');
    const closeButton = document.getElementById('history-modal-close');
    const updatedLabel = document.getElementById('history-modal-updated');

    if (!modal || !openButton || !closeButton) {
        return;
    }

    historyModalInitialized = true;

    const closeModal = () => {
        modal.style.display = 'none';
    };

    openButton.addEventListener('click', () => {
        if (!historyDataCache) return;
        renderHistoryModalContent(historyDataCache);
        if (updatedLabel && historyDataTimestamp) {
            updatedLabel.textContent = `Updated ${historyDataTimestamp.toLocaleString()}`;
        }
        modal.style.display = 'flex';
    });

    closeButton.addEventListener('click', closeModal);

    modal.addEventListener('click', (event) => {
        if (event.target === modal) {
            closeModal();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && modal.style.display === 'flex') {
            closeModal();
        }
    });
}

function renderHistoryModalContent(history) {
    const body = document.getElementById('history-modal-body');
    if (!body) return;

    const summary = history.summary || {};
    const expiredPositions = history.expired_positions || [];
    const assetOutcomes = summary.asset_outcomes || [];
    const totalPositions = summary.expired_count || expiredPositions.length || 0;
    const assignedCount = summary.assigned_count || 0;
    const returnedCount = summary.returned_count || 0;
    const unknownCount = summary.unknown_count != null
        ? Number(summary.unknown_count)
        : Math.max(totalPositions - (assignedCount + returnedCount), 0);
    const assignmentRate = totalPositions ? (assignedCount / totalPositions) * 100 : 0;
    const returnRate = totalPositions ? (returnedCount / totalPositions) * 100 : 0;
    const avgPremiumPerPosition = totalPositions ? (summary.net_premium || 0) / totalPositions : 0;

    const aprValues = expiredPositions
        .map(p => (p.apr !== null && p.apr !== undefined) ? Number(p.apr) : null)
        .filter(v => v !== null && !Number.isNaN(v));
    const avgApr = aprValues.length ? aprValues.reduce((acc, val) => acc + val, 0) / aprValues.length : null;
    const maxApr = aprValues.length ? Math.max(...aprValues) : null;
    const minApr = aprValues.length ? Math.min(...aprValues) : null;

    const premiumValues = expiredPositions.map(p => Number(p.premium || 0));
    const maxPremium = premiumValues.length ? Math.max(...premiumValues) : 0;
    const totalPremium = summary.net_premium != null
        ? Number(summary.net_premium)
        : premiumValues.reduce((acc, val) => acc + val, 0);

    const assignedNotional = summary.assigned_notional_total || 0;
    const avgAssignmentNotional = assignedCount ? assignedNotional / assignedCount : 0;

    const expiryMap = new Map();
    const outcomeCounts = { Assigned: 0, Returned: 0, Unknown: 0 };

    expiredPositions.forEach((position) => {
        const expiryKey = position.expiry_date || 'Unknown';
        const outcome = (position.outcome || 'Unknown');
        const entry = expiryMap.get(expiryKey) || {
            expiry: expiryKey,
            total: 0,
            assigned: 0,
            returned: 0,
            premiumTotal: 0,
            quantityTotal: 0,
            notionalTotal: 0,
            aprSum: 0,
            aprCount: 0,
            strikeSum: 0,
            strikeCount: 0,
            expiryPriceSum: 0,
            expiryPriceCount: 0
        };

        entry.total += 1;
        entry.premiumTotal += Number(position.premium || 0);
        entry.quantityTotal += Number(position.quantity || 0);
        entry.notionalTotal += Number(position.notional || (position.quantity || 0) * (position.strike || 0));

        if (outcome === 'Assigned') {
            entry.assigned += 1;
        } else if (outcome === 'Returned') {
            entry.returned += 1;
        }

        outcomeCounts[outcome] = (outcomeCounts[outcome] || 0) + 1;

        if (position.apr !== null && position.apr !== undefined) {
            entry.aprSum += Number(position.apr);
            entry.aprCount += 1;
        }

        if (position.strike !== null && position.strike !== undefined) {
            entry.strikeSum += Number(position.strike);
            entry.strikeCount += 1;
        }

        if (position.expiry_price !== null && position.expiry_price !== undefined) {
            entry.expiryPriceSum += Number(position.expiry_price);
            entry.expiryPriceCount += 1;
        }

        expiryMap.set(expiryKey, entry);
    });

    const expirySummary = Array.from(expiryMap.values()).sort((a, b) => {
        const aTime = Date.parse(a.expiry) || 0;
        const bTime = Date.parse(b.expiry) || 0;
        return bTime - aTime;
    });

    const topPremiumPositions = [...expiredPositions]
        .sort((a, b) => (Number(b.premium || 0) - Number(a.premium || 0)))
        .slice(0, 15);

    const topAprPositions = [...expiredPositions]
        .filter(p => p.apr !== null && p.apr !== undefined)
        .sort((a, b) => Number(b.apr) - Number(a.apr))
        .slice(0, 15);

    let html = '';

    html += '<div class="modal-section">';
    html += '<h3>Performance Overview</h3>';
    html += '<div class="summary-grid modal-grid">';
    html += `<div class="summary-card"><span class="summary-label">Expired Positions</span><span class="summary-value">${formatNumber(totalPositions, 0)}</span><span class="summary-subtext">Total tracked legs</span></div>`;
    html += `<div class="summary-card"><span class="summary-label">Assignment Rate</span><span class="summary-value">${formatPercentage(assignmentRate, 2)}</span><span class="summary-subtext">${formatNumber(assignedCount, 0)} assigned legs</span></div>`;
    html += `<div class="summary-card"><span class="summary-label">Return Rate</span><span class="summary-value">${formatPercentage(returnRate, 2)}</span><span class="summary-subtext">${formatNumber(returnedCount, 0)} returned legs</span></div>`;
    html += `<div class="summary-card"><span class="summary-label">Premium Collected</span><span class="summary-value">${formatCurrency(totalPremium)}</span><span class="summary-subtext">Avg ${formatCurrency(avgPremiumPerPosition)}</span></div>`;
    html += `<div class="summary-card"><span class="summary-label">Avg APR</span><span class="summary-value">${avgApr !== null ? formatPercentage(avgApr) : '—'}</span><span class="summary-subtext">Low ${minApr !== null ? formatPercentage(minApr) : '—'} · High ${maxApr !== null ? formatPercentage(maxApr) : '—'}</span></div>`;
    html += `<div class="summary-card"><span class="summary-label">Largest Premium</span><span class="summary-value">${formatCurrency(maxPremium)}</span><span class="summary-subtext">Across ${formatNumber(topPremiumPositions.length, 0)} top trades</span></div>`;
    html += `<div class="summary-card"><span class="summary-label">Assigned Notional</span><span class="summary-value">${formatCurrency(assignedNotional)}</span><span class="summary-subtext">Avg ${formatCurrency(avgAssignmentNotional || 0)}</span></div>`;
    html += '</div>';
    html += '</div>';

    if (assetOutcomes.length > 0) {
        html += '<div class="modal-section">';
        html += '<h3>By Asset</h3>';
        html += '<div class="modal-table-wrapper">';
        html += '<table class="data-table">';
        html += '<thead><tr><th>Asset</th><th>Expired</th><th>Assigned</th><th>Returned</th><th>Assignment Rate</th><th>Premium</th><th>Total Notional</th><th>Assigned Notional</th><th>Assigned %</th><th>Avg Assign Strike</th><th>Avg Expiry Px (Assigned)</th><th>Avg Expiry Px (Returned)</th></tr></thead>';
        html += '<tbody>';
        for (const outcome of assetOutcomes) {
            const assetTotal = outcome.total_positions || 0;
            const assetAssigned = outcome.assigned_count || 0;
            const assetReturned = outcome.returned_count || 0;
            const assetAssignmentRate = assetTotal ? (assetAssigned / assetTotal) * 100 : 0;
            const avgAssignStrike = outcome.avg_assignment_price || 0;
            const avgAssignExpiry = outcome.avg_assigned_expiry || null;
            const avgReturnedExpiry = outcome.avg_returned_expiry || null;
            const premiumTotal = outcome.premium_total || 0;
            const totalNotional = outcome.total_notional || 0;
            const assignedNotional = outcome.assigned_notional || 0;
            const assignedPct = totalNotional ? (assignedNotional / totalNotional) * 100 : 0;

            const assignStrikeDecimals = avgAssignStrike > 1000 ? 0 : avgAssignStrike > 1 ? 2 : 6;
            const assignExpiryDecimals = avgAssignExpiry && avgAssignExpiry > 1000 ? 0 : avgAssignExpiry && avgAssignExpiry > 1 ? 2 : 6;
            const returnedExpiryDecimals = avgReturnedExpiry && avgReturnedExpiry > 1000 ? 0 : avgReturnedExpiry && avgReturnedExpiry > 1 ? 2 : 6;

            html += '<tr>';
            html += `<td><span class="token-badge ${getTokenClass(outcome.symbol)}">${outcome.symbol}</span></td>`;
            html += `<td>${formatNumber(assetTotal, 0)}</td>`;
            html += `<td>${formatNumber(assetAssigned, 0)}</td>`;
            html += `<td>${formatNumber(assetReturned, 0)}</td>`;
            html += `<td>${formatPercentage(assetAssignmentRate)}</td>`;
            html += `<td>${formatCurrency(premiumTotal)}</td>`;
            html += `<td>${formatCurrency(totalNotional)}</td>`;
            html += `<td>${formatCurrency(assignedNotional)}</td>`;
            html += `<td>${formatPercentage(assignedPct)}</td>`;
            html += `<td>${avgAssignStrike ? formatCurrency(avgAssignStrike, assignStrikeDecimals) : '—'}</td>`;
            html += `<td>${avgAssignExpiry ? formatCurrency(avgAssignExpiry, assignExpiryDecimals) : '—'}</td>`;
            html += `<td>${avgReturnedExpiry ? formatCurrency(avgReturnedExpiry, returnedExpiryDecimals) : '—'}</td>`;
            html += '</tr>';
        }
        html += '</tbody></table>';
        html += '</div>';
        html += '</div>';
    }

    if (expirySummary.length > 0) {
        html += '<div class="modal-section">';
        html += '<h3>By Expiry</h3>';
        html += '<div class="modal-table-wrapper">';
        html += '<table class="data-table">';
        html += '<thead><tr><th>Expiry</th><th>Positions</th><th>Assigned</th><th>Returned</th><th>Assignment Rate</th><th>Premium</th><th>Avg APR</th><th>Avg Strike</th><th>Avg Settlement</th></tr></thead>';
        html += '<tbody>';
        for (const entry of expirySummary) {
            const assignmentRate = entry.total ? (entry.assigned / entry.total) * 100 : 0;
            const avgAprEntry = entry.aprCount ? entry.aprSum / entry.aprCount : null;
            const avgStrikeEntry = entry.strikeCount ? entry.strikeSum / entry.strikeCount : null;
            const avgSettlementEntry = entry.expiryPriceCount ? entry.expiryPriceSum / entry.expiryPriceCount : null;

            const strikeDecimals = avgStrikeEntry && avgStrikeEntry > 1000 ? 0 : avgStrikeEntry && avgStrikeEntry > 1 ? 2 : 6;
            const settlementDecimals = avgSettlementEntry && avgSettlementEntry > 1000 ? 0 : avgSettlementEntry && avgSettlementEntry > 1 ? 2 : 6;

            html += '<tr>';
            html += `<td>${entry.expiry}</td>`;
            html += `<td>${formatNumber(entry.total, 0)}</td>`;
            html += `<td>${formatNumber(entry.assigned, 0)}</td>`;
            html += `<td>${formatNumber(entry.returned, 0)}</td>`;
            html += `<td>${formatPercentage(assignmentRate)}</td>`;
            html += `<td>${formatCurrency(entry.premiumTotal)}</td>`;
            html += `<td>${avgAprEntry !== null ? formatPercentage(avgAprEntry) : '—'}</td>`;
            html += `<td>${avgStrikeEntry ? formatCurrency(avgStrikeEntry, strikeDecimals) : '—'}</td>`;
            html += `<td>${avgSettlementEntry ? formatCurrency(avgSettlementEntry, settlementDecimals) : '—'}</td>`;
            html += '</tr>';
        }
        html += '</tbody></table>';
        html += '</div>';
        html += '</div>';
    }

    if (topPremiumPositions.length > 0) {
        html += '<div class="modal-section">';
        html += '<h3>Top Premium Harvests</h3>';
        html += '<div class="modal-table-wrapper">';
        html += '<table class="data-table">';
        html += '<thead><tr><th>Date</th><th>Symbol</th><th>Strategy</th><th>Outcome</th><th>Quantity</th><th>Strike</th><th>Premium</th><th>APR</th><th>Expiry</th></tr></thead>';
        html += '<tbody>';
        for (const position of topPremiumPositions) {
            const strikeDecimals = position.strike > 1000 ? 0 : position.strike > 1 ? 2 : 6;
            html += '<tr>';
            html += `<td>${formatDateLabel(position.created_at)}</td>`;
            html += `<td>${position.symbol || '—'}</td>`;
            html += `<td>${strategyBadge(position)}</td>`;
            html += `<td>${formatPositionOutcome(position)}</td>`;
            html += `<td>${formatNumber(position.quantity, 4)}</td>`;
            html += `<td>${formatCurrency(position.strike || 0, strikeDecimals)}</td>`;
            html += `<td>${formatCurrency(position.premium || 0)}</td>`;
            html += `<td>${formatPercentage(position.apr)}</td>`;
            html += `<td>${formatDateLabel(position.expiry_date)}</td>`;
            html += '</tr>';
        }
        html += '</tbody></table>';
        html += '</div>';
        html += '</div>';
    }

    if (topAprPositions.length > 0) {
        html += '<div class="modal-section">';
        html += '<h3>Highest APR Captured</h3>';
        html += '<div class="modal-table-wrapper">';
        html += '<table class="data-table">';
        html += '<thead><tr><th>Date</th><th>Symbol</th><th>Strategy</th><th>Outcome</th><th>Quantity</th><th>Strike</th><th>Premium</th><th>APR</th><th>Expiry</th></tr></thead>';
        html += '<tbody>';
        for (const position of topAprPositions) {
            const strikeDecimals = position.strike > 1000 ? 0 : position.strike > 1 ? 2 : 6;
            html += '<tr>';
            html += `<td>${formatDateLabel(position.created_at)}</td>`;
            html += `<td>${position.symbol || '—'}</td>`;
            html += `<td>${strategyBadge(position)}</td>`;
            html += `<td>${formatPositionOutcome(position)}</td>`;
            html += `<td>${formatNumber(position.quantity, 4)}</td>`;
            html += `<td>${formatCurrency(position.strike || 0, strikeDecimals)}</td>`;
            html += `<td>${formatCurrency(position.premium || 0)}</td>`;
            html += `<td>${formatPercentage(position.apr)}</td>`;
            html += `<td>${formatDateLabel(position.expiry_date)}</td>`;
            html += '</tr>';
        }
        html += '</tbody></table>';
        html += '</div>';
        html += '</div>';
    }

    if (summary.expired_count && expiredPositions.length && summary.expired_count > expiredPositions.length) {
        html += '<div class="modal-section">';
        html += `<p class="modal-subtext">Showing ${formatNumber(expiredPositions.length, 0)} of ${formatNumber(summary.expired_count, 0)} expired legs (API limit). Adjust <code>RYSK_HISTORY_LIMIT</code> for deeper pulls.</p>`;
        html += '</div>';
    }

    body.innerHTML = html;
}

// ── Portfolio Health ──

function renderPortfolioHealth(positionsData, historyData) {
    const healthContent = document.getElementById('health-content');
    const healthGrid = document.getElementById('health-grid');
    const healthExpiring = document.getElementById('health-expiring');
    if (!healthContent || !healthGrid) return;

    const summary = positionsData?.summary || {};
    const openPositions = positionsData?.open_positions || [];

    if (!openPositions.length) {
        healthContent.style.display = 'none';
        return;
    }

    // DTE distribution
    const now = Date.now() / 1000;
    let dteUnder3d = 0, dte3to7d = 0, dte7to14d = 0, dteOver14d = 0;
    const expiringThisWeek = [];

    for (const pos of openPositions) {
        const dte = pos.days_to_expiry || 0;
        if (dte <= 3) { dteUnder3d++; }
        else if (dte <= 7) { dte3to7d++; }
        else if (dte <= 14) { dte7to14d++; }
        else { dteOver14d++; }

        if (dte <= 7 && dte > 0) {
            expiringThisWeek.push(pos);
        }
    }

    const total = openPositions.length;
    const nearTermPct = total > 0 ? Math.round((dteUnder3d + dte3to7d) / total * 100) : 0;
    const nearTermColor = nearTermPct > 60 ? 'var(--color-error)' : nearTermPct > 40 ? 'var(--color-warning)' : 'var(--accent)';

    healthGrid.innerHTML = `
        <div class="summary-card">
            <div class="summary-label">Near-Term Weight</div>
            <div class="summary-value" style="color: ${nearTermColor};">${nearTermPct}%</div>
            <div class="summary-subtext">${dteUnder3d + dte3to7d} of ${total} within 7d</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">&lt; 3 Days</div>
            <div class="summary-value">${dteUnder3d}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">3—7 Days</div>
            <div class="summary-value">${dte3to7d}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">7—14 Days</div>
            <div class="summary-value">${dte7to14d}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">&gt; 14 Days</div>
            <div class="summary-value">${dteOver14d}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Portfolio APR</div>
            <div class="summary-value">${summary.open_weighted_apr != null ? formatPercentage(summary.open_weighted_apr) : '—'}</div>
        </div>
    `;

    // Expiring this week alert
    if (expiringThisWeek.length > 0) {
        // Build price lookup from asset_summary
        const assetSummary = positionsData?.asset_summary || [];
        const priceMap = {};
        for (const a of assetSummary) {
            if (a.symbol && a.current_price != null) {
                priceMap[String(a.symbol).toUpperCase()] = a.current_price;
            }
        }

        const totalExpiringNotional = expiringThisWeek.reduce((s, p) => s + (p.notional || 0), 0);
        const totalExpiringPremium = expiringThisWeek.reduce((s, p) => s + (p.premium || 0), 0);
        const itmCount = expiringThisWeek.filter(p => {
            const cp = priceMap[String(p.symbol || '').toUpperCase()];
            if (cp == null || !p.strike) return false;
            const isPut = (p.type || '').toLowerCase() === 'put';
            return isPut ? cp < p.strike : cp > p.strike;
        }).length;

        healthExpiring.innerHTML = `
            <h3 class="subsection-title">Expiring This Week (${expiringThisWeek.length})</h3>
            <div style="margin-bottom: 12px; font-size: 0.85em; color: var(--text-muted);">
                ${formatCurrency(totalExpiringNotional, 0)} notional · ${formatCurrency(totalExpiringPremium)} premium at stake${itmCount > 0 ? ` · <span style="color: var(--color-error);">${itmCount} ITM</span>` : ''}
            </div>
            <table class="data-table">
                <thead><tr><th>Asset</th><th>Strategy</th><th>Strike</th><th>Days</th><th>Premium</th><th>APR</th><th>Status</th></tr></thead>
                <tbody>${expiringThisWeek.map(p => {
                    const cp = priceMap[String(p.symbol || '').toUpperCase()];
                    const isPut = (p.type || '').toLowerCase() === 'put';
                    const hasPrice = cp != null && p.strike;
                    const itm = hasPrice && (isPut ? cp < p.strike : cp > p.strike);
                    const statusColor = !hasPrice ? 'var(--text-muted)' : itm ? 'var(--color-error)' : 'var(--accent)';
                    const statusLabel = !hasPrice ? '—' : itm ? 'ITM' : 'OTM';

                    return `<tr>
                        <td>${p.symbol || '—'}</td>
                        <td>${strategyBadge(p)}</td>
                        <td>${formatStrike(p.strike)}</td>
                        <td>${formatNumber(p.days_to_expiry, 1)}</td>
                        <td>${formatCurrency(p.premium || 0)}</td>
                        <td>${formatPercentage(p.apr)}</td>
                        <td><span style="color: ${statusColor}; font-weight: 500; font-size: 0.82em;">${statusLabel}</span></td>
                    </tr>`;
                }).join('')}</tbody>
            </table>
        `;
    } else {
        healthExpiring.innerHTML = '<div style="font-size: 0.85em; color: var(--text-muted); margin-top: 8px;">No positions expiring within 7 days.</div>';
    }

    healthContent.style.display = 'block';
}

// ── Premium PnL (Account) ──

function renderAccountPnl(historyData) {
    const pnlContent = document.getElementById('pnl-content');
    const pnlGrid = document.getElementById('pnl-grid');
    if (!pnlContent || !pnlGrid) return;

    const summary = historyData?.summary || {};
    const expired = historyData?.expired_positions || [];

    if (!expired.length) {
        pnlContent.style.display = 'none';
        return;
    }

    const returnedPositions = expired.filter(p => (p.outcome || '').toLowerCase() === 'returned');
    const assignedPositions = expired.filter(p => (p.outcome || '').toLowerCase() === 'assigned');
    const returnedPremium = returnedPositions.reduce((s, p) => s + (p.premium || 0), 0);
    const assignedPremium = assignedPositions.reduce((s, p) => s + (p.premium || 0), 0);
    const totalPremium = summary.net_premium || 0;
    const returnRate = expired.length > 0 ? (returnedPositions.length / expired.length * 100) : 0;

    pnlGrid.innerHTML = `
        <div class="summary-card">
            <div class="summary-label">Returned Position Premium</div>
            <div class="summary-value" style="color: var(--accent);">${formatCurrency(returnedPremium)}</div>
            <div class="summary-subtext">Kept from ${returnedPositions.length} returned positions</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Total Premium Collected</div>
            <div class="summary-value">${formatCurrency(totalPremium)}</div>
            <div class="summary-subtext">${expired.length} expired positions</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Assigned Premium</div>
            <div class="summary-value" style="color: var(--color-error);">${formatCurrency(assignedPremium)}</div>
            <div class="summary-subtext">${assignedPositions.length} assigned</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Return Rate</div>
            <div class="summary-value">${formatPercentage(returnRate)}</div>
            <div class="summary-subtext">${returnedPositions.length} of ${expired.length}</div>
        </div>
        <div class="summary-card">
            <div class="summary-label">Assigned Notional</div>
            <div class="summary-value">${formatCurrency(summary.assigned_notional_total || 0)}</div>
        </div>
    `;

    // Build cumulative premium chart from expired positions (sorted by expiry date)
    const sortedExpired = [...expired].sort((a, b) => {
        const ta = Date.parse(a.expiry_date || '') || 0;
        const tb = Date.parse(b.expiry_date || '') || 0;
        return ta - tb;
    });

    // Group by expiry date
    const byDate = {};
    for (const p of sortedExpired) {
        const date = p.expiry_date || 'Unknown';
        if (!byDate[date]) byDate[date] = { premium: 0, returned_premium: 0, count: 0 };
        byDate[date].premium += p.premium || 0;
        byDate[date].count += 1;
        if ((p.outcome || '').toLowerCase() === 'returned') {
            byDate[date].returned_premium += p.premium || 0;
        }
    }

    const dates = Object.keys(byDate).filter(d => d !== 'Unknown').sort();
    // Show container before rendering so Plotly can measure width
    pnlContent.style.display = 'block';

    if (dates.length > 1 && typeof Plotly !== 'undefined') {
        let cumTotal = 0;
        let cumReturned = 0;
        const cumTotalArr = [];
        const cumReturnedArr = [];
        const dailyPrem = [];

        for (const d of dates) {
            cumTotal += byDate[d].premium;
            cumReturned += byDate[d].returned_premium;
            cumTotalArr.push(cumTotal);
            cumReturnedArr.push(cumReturned);
            dailyPrem.push(byDate[d].premium);
        }

        Plotly.newPlot('pnl-chart-account', [
            { x: dates, y: dailyPrem, type: 'bar', name: 'Expiry Premium', marker: { color: 'rgba(52, 211, 153, 0.3)' }, yaxis: 'y2' },
            { x: dates, y: cumTotalArr, type: 'scatter', mode: 'lines', name: 'Cumulative Total', line: { color: '#34d399', width: 2.5 } },
            { x: dates, y: cumReturnedArr, type: 'scatter', mode: 'lines', name: 'Returned Position Premium', line: { color: '#f59e0b', width: 2, dash: 'dot' } },
        ], {
            paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
            font: { family: 'Inter, system-ui, sans-serif', color: '#71717a', size: 12 },
            margin: { l: 60, r: 60, t: 20, b: 60 },
            xaxis: { showgrid: false, tickfont: { size: 10 }, tickangle: -45 },
            yaxis: { title: 'Cumulative ($)', gridcolor: 'rgba(255,255,255,0.06)', tickfont: { size: 11 }, tickprefix: '$' },
            yaxis2: { title: 'Per Expiry ($)', overlaying: 'y', side: 'right', gridcolor: 'transparent', tickfont: { size: 11 }, tickprefix: '$' },
            legend: { orientation: 'h', y: -0.12, font: { size: 11 } },
            bargap: 0.15,
        }, { responsive: true, displayModeBar: false });
    }
}

async function loadAllData() {
    const tasks = [];

    if (!currentAccount) {
        setAccountStatus('Enter a wallet address');
        await Promise.all(tasks);
        return;
    }

    setAccountStatus('Loading...');
    tasks.push(loadPositions(), loadHistory());

    await Promise.all(tasks);

    // Render new sections after all data is loaded
    const posData = _positions_cache.get(currentAccount.toLowerCase());
    if (posData) renderPortfolioHealth(posData, historyDataCache);
    if (historyDataCache) renderAccountPnl(historyDataCache);

    // Resize any Plotly charts after render (handles cases where container just became visible)
    setTimeout(() => {
        document.querySelectorAll('.js-plotly-plot').forEach(el => {
            Plotly.Plots.resize(el);
        });
    });

    setAccountStatus('');
}

function refreshAllData() {
    loadAllData();
}

function stopSplashTyping(finalText = '') {
    if (splashTypingTimer) {
        clearInterval(splashTypingTimer);
        splashTypingTimer = null;
    }
    if (splashTypingEl && finalText) {
        splashTypingEl.textContent = finalText;
    }
}

function startSplashTyping(messages = []) {
    if (!splashTypingEl) return;
    stopSplashTyping();
    if (!messages.length) {
        splashTypingEl.textContent = '';
        return;
    }
    let msgIdx = 0;
    let charIdx = 0;
    const typeDelay = 55; // ms per character
    const holdDelay = 1200; // pause after full line

    const typeNext = () => {
        const msg = messages[msgIdx];
        if (charIdx <= msg.length) {
            splashTypingEl.textContent = msg.slice(0, charIdx);
            charIdx += 1;
            splashTypingTimer = setTimeout(typeNext, typeDelay);
        } else {
            splashTypingTimer = setTimeout(() => {
                msgIdx = (msgIdx + 1) % messages.length;
                charIdx = 0;
                typeNext();
            }, holdDelay);
        }
    };

    typeNext();
}

function showMainContent() {
    if (splashScreenEl) {
        splashScreenEl.style.display = 'none';
    }
    if (mainContentEl) {
        mainContentEl.style.display = 'block';
    }
}

async function launchDashboard(addressInput, { fromSplash = false } = {}) {
    let normalized = (addressInput || '').trim();
    if (!normalized && defaultAccount) {
        normalized = defaultAccount;
    }
    if (!normalized) {
        if (fromSplash && splashErrorEl) {
            splashErrorEl.textContent = 'Enter a wallet address';
            splashErrorEl.style.display = 'block';
        } else {
            setAccountStatus('Enter a wallet address', true);
        }
        return;
    }
    if (!/^0x[0-9a-fA-F]{40}$/.test(normalized)) {
        if (fromSplash && splashErrorEl) {
            splashErrorEl.textContent = 'Invalid wallet address format';
            splashErrorEl.style.display = 'block';
        } else {
            setAccountStatus('Invalid wallet address format', true);
        }
        return;
    }

    currentAccount = normalized;
    updateAccountUI(currentAccount);
    try {
        localStorage.setItem('dashboardAccount', currentAccount || '');
    } catch (_) {
        // ignore storage errors
    }

    // Reset cached state similar to applyAccountChange
    historyDataCache = null;
    historyDataTimestamp = null;
    const detailButton = document.getElementById('history-detail-button');
    if (detailButton) {
        detailButton.disabled = true;
        detailButton.textContent = '🔍 Deep Dive (Loading...)';
    }
    const historyModal = document.getElementById('history-modal');
    if (historyModal) {
        historyModal.style.display = 'none';
    }
    const positionsDetail = document.getElementById('positions-detail');
    if (positionsDetail) {
        positionsDetail.style.display = 'none';
    }
    positionsAssetSummary = [];
    openPositionsData = [];
    selectedAssetSymbol = null;
    selectedAssetExpiry = '';

    if (fromSplash) {
        if (splashErrorEl) splashErrorEl.style.display = 'none';
        if (splashLaunchEl) {
            splashLaunchEl.disabled = true;
            splashLaunchEl.textContent = 'Loading...';
        }
        startSplashTyping([
            'RYSKing it all...',
            'Pulling balances...',
            'Pulling positions...',
            'Pulling history...',
            'Hang tight — arming dashboard...'
        ]);
    }

    try {
        await loadAllData();
        if (fromSplash) {
            stopSplashTyping('Loaded. Preparing dashboard...');
            showMainContent();
            // Force Plotly charts to recalculate width now that main-content is visible
            // Use setTimeout to ensure layout has fully settled after display change
            setTimeout(() => {
                document.querySelectorAll('.js-plotly-plot').forEach(el => {
                    Plotly.Plots.resize(el);
                });
            }, 100);
        } else {
            setAccountStatus('');
        }
    } catch (err) {
        const message = 'Failed to load data: ' + err.message;
        if (fromSplash) {
            stopSplashTyping();
        }
        if (fromSplash && splashErrorEl) {
            splashErrorEl.textContent = message;
            splashErrorEl.style.display = 'block';
        } else {
            setAccountStatus(message, true);
        }
    } finally {
        if (fromSplash && splashLaunchEl) {
            splashLaunchEl.disabled = false;
            splashLaunchEl.textContent = 'Enter';
        }
    }
}

function applyAccountChange(addressInput) {
    let normalized = (addressInput || '').trim();
    if (!normalized && defaultAccount) {
        normalized = defaultAccount;
    }
    if (normalized && !/^0x[0-9a-fA-F]{40}$/.test(normalized)) {
        setAccountStatus('Invalid wallet address format', true);
        return;
    }
    if (!normalized) {
        setAccountStatus('Enter a wallet address', true);
        return;
    }
    currentAccount = normalized;
    if (accountInputEl) {
        accountInputEl.value = normalized;
    }
    updateAccountUI(currentAccount);
    try {
        localStorage.setItem('dashboardAccount', currentAccount || '');
    } catch (_) {
        // Ignore storage errors
    }
    historyDataCache = null;
    historyDataTimestamp = null;
    const detailButton = document.getElementById('history-detail-button');
    if (detailButton) {
        detailButton.disabled = true;
        detailButton.textContent = '🔍 Deep Dive (Loading...)';
    }
    const historyModal = document.getElementById('history-modal');
    if (historyModal) {
        historyModal.style.display = 'none';
    }
    const positionsDetail = document.getElementById('positions-detail');
    if (positionsDetail) {
        positionsDetail.style.display = 'none';
    }
    positionsAssetSummary = [];
    openPositionsData = [];
    selectedAssetSymbol = null;
    selectedAssetExpiry = '';
    setAccountStatus('Loading...');
    refreshAllData();
}

function setupAssetSummaryHandlers() {
    const detailClose = document.getElementById('positions-detail-close');
    if (detailClose) {
        detailClose.addEventListener('click', () => {
            const detail = document.getElementById('positions-detail');
            if (detail) detail.style.display = 'none';
            selectedAssetSymbol = null;
            selectedAssetExpiry = '';
            document.querySelectorAll('.asset-card').forEach(card => card.classList.remove('selected'));
        });
    }

    document.querySelectorAll('.asset-card').forEach(card => {
        card.addEventListener('click', () => {
            const asset = card.dataset.asset;
            if (!asset) return;
            showAssetPositions(asset);
        });
    });
}

function showAssetPositions(asset) {
    if (!asset) return;
    const previousAsset = selectedAssetSymbol;
    selectedAssetSymbol = asset;
    if (previousAsset !== asset) {
        selectedAssetExpiry = '';
    }
    document.querySelectorAll('.asset-card').forEach(card => {
        card.classList.toggle('selected', card.dataset.asset === asset);
    });
    const detail = document.getElementById('positions-detail');
    if (!detail) return;

    const summary = positionsAssetSummary.find(a => a.symbol === asset);
    const assetPositions = openPositionsData.filter(pos => (pos.symbol || '').toUpperCase() === asset.toUpperCase());
    const expiryOptions = Array.from(new Set(
        assetPositions
            .map(pos => pos.expiry_date)
            .filter(Boolean)
    )).sort((a, b) => {
        const aTs = Date.parse(a);
        const bTs = Date.parse(b);
        if (Number.isNaN(aTs) || Number.isNaN(bTs)) {
            return String(a).localeCompare(String(b));
        }
        return aTs - bTs;
    });
    const effectiveExpiry = selectedAssetExpiry && expiryOptions.includes(selectedAssetExpiry) ? selectedAssetExpiry : '';
    selectedAssetExpiry = effectiveExpiry;
    let positions = effectiveExpiry
        ? assetPositions.filter(pos => pos.expiry_date === effectiveExpiry)
        : assetPositions;
    if (effectiveExpiry && positions.length === 0 && assetPositions.length > 0) {
        selectedAssetExpiry = '';
        positions = assetPositions;
    }

    document.getElementById('positions-detail-title').textContent = `${asset} Open Option Positions`;
    renderAssetDetailFilters(asset, expiryOptions, effectiveExpiry);

    const summaryContainer = document.getElementById('positions-detail-summary');
    if (summaryContainer) {
        if (summary) {
            const filteredNotional = positions.reduce((acc, pos) => acc + (Number(pos.notional) || 0), 0);
            const filteredQuantity = positions.reduce((acc, pos) => acc + (Number(pos.quantity) || 0), 0);
            const filteredPremium = positions.reduce((acc, pos) => acc + (Number(pos.premium) || 0), 0);
            const aprValues = positions
                .map(pos => pos.apr)
                .filter(apr => apr !== null && apr !== undefined)
                .map(apr => Number(apr));
            const avgApr = aprValues.length
                ? aprValues.reduce((acc, apr) => acc + apr, 0) / aprValues.length
                : null;
            summaryContainer.innerHTML = `
                <div class="summary-grid detail-grid">
                    <div class="summary-card">
                        <span class="summary-label">Positions</span>
                        <span class="summary-value">${formatNumber(positions.length || 0, 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Quantity</span>
                        <span class="summary-value">${formatNumber(filteredQuantity, 4)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Notional</span>
                        <span class="summary-value">${formatCurrency(filteredNotional || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Premium</span>
                        <span class="summary-value">${formatCurrency(filteredPremium || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Avg APR</span>
                        <span class="summary-value">${avgApr !== null ? formatPercentage(avgApr) : '—'}</span>
                    </div>
                </div>
            `;
        } else {
            summaryContainer.innerHTML = '<p class="empty-state">No summary available for this asset.</p>';
        }
    }

    renderPositionsHeatmap(buildHeatmapSummary(positions, summary?.current_price));
    renderPositionsDetailTable(positions);

    detail.style.display = 'block';
}

function renderAssetDetailFilters(asset, expiryOptions, selectedExpiry) {
    const filters = document.getElementById('positions-detail-filters');
    if (!filters) return;

    const tabs = [
        { value: '', label: 'All', selected: !selectedExpiry },
        ...expiryOptions.map(expiry => {
            const isActive = Date.parse(expiry) > Date.now();
            return {
                value: expiry,
                label: expiry + (isActive ? ' *' : ''),
                selected: selectedExpiry === expiry
            };
        })
    ];

    const tabsHtml = tabs.map(t => `
        <button class="tab-button${t.selected ? ' active' : ''}" data-expiry="${t.value}">${t.label}</button>
    `).join('');

    filters.innerHTML = `<div class="tabs tab-carousel">${tabsHtml}</div>`;

    filters.querySelectorAll('.tab-button').forEach(button => {
        button.addEventListener('click', () => {
            selectedAssetExpiry = button.dataset.expiry || '';
            showAssetPositions(asset);
        });
    });
}

function buildHeatmapSummary(positions, currentPrice = null) {
    const strikeMap = new Map();
    for (const pos of positions || []) {
        const strike = Number(pos.strike) || 0;
        if (!strike) continue;
        const key = String(strike);
        if (!strikeMap.has(key)) {
            strikeMap.set(key, {
                strike,
                count: 0,
                quantity_total: 0,
                premium_total: 0,
                notional_total: 0,
                apr_sum: 0,
                apr_count: 0,
                put_notional: 0,
                call_notional: 0,
                put_count: 0,
                call_count: 0,
            });
        }
        const entry = strikeMap.get(key);
        const notional = Number(pos.notional) || 0;
        entry.count += 1;
        entry.quantity_total += Number(pos.quantity) || 0;
        entry.premium_total += Number(pos.premium) || 0;
        entry.notional_total += notional;
        if (pos.apr !== null && pos.apr !== undefined) {
            entry.apr_sum += Number(pos.apr);
            entry.apr_count += 1;
        }
        const posType = String(pos.type || '').toLowerCase();
        if (posType === 'put') {
            entry.put_notional += notional;
            entry.put_count += 1;
        } else {
            entry.call_notional += notional;
            entry.call_count += 1;
        }
    }

    const strikes = Array.from(strikeMap.values()).map(entry => ({
        strike: entry.strike,
        count: entry.count,
        quantity_total: entry.quantity_total,
        premium_total: entry.premium_total,
        notional_total: entry.notional_total,
        avg_apr: entry.apr_count ? entry.apr_sum / entry.apr_count : null,
        put_notional: entry.put_notional,
        call_notional: entry.call_notional,
        put_count: entry.put_count,
        call_count: entry.call_count,
    })).sort((a, b) => (a.strike || 0) - (b.strike || 0));

    return { strikes, current_price: currentPrice };
}

function renderPositionsHeatmap(summary) {
    const heatmapDiv = document.getElementById('positions-heatmap');
    if (!heatmapDiv) return;

    const strikes = summary?.strikes || [];
    const currentPrice = summary?.current_price;
    if (!strikes.length) {
        heatmapDiv.innerHTML = '<p class="empty-state">No strike distribution yet.</p>';
        return;
    }

    const sorted = [...strikes].sort((a, b) => (a.strike || 0) - (b.strike || 0));
    const strikeValues = sorted.map(s => s.strike);
    const minStrike = strikeValues[0];
    const maxStrike = strikeValues[strikeValues.length - 1];

    // Compute bar width from minimum gap between consecutive strikes
    let barWidth = (maxStrike - minStrike) / sorted.length;
    for (let i = 1; i < strikeValues.length; i++) {
        const gap = strikeValues[i] - strikeValues[i - 1];
        if (gap > 0 && gap < barWidth) barWidth = gap;
    }
    barWidth *= 0.8;

    const shapes = [];
    const annotations = [];

    // Only show ITM zones for a specific active expiry, not "All Expiries"
    const isActiveExpiry = selectedAssetExpiry && Date.parse(selectedAssetExpiry) > Date.now();
    const cp = Number(currentPrice);
    const hasPrice = currentPrice !== null && currentPrice !== undefined && Number.isFinite(cp);

    if (hasPrice && isActiveExpiry) {
        const xPad = barWidth;
        const xMin = minStrike - xPad;
        const xMax = maxStrike + xPad;

        // Count ITM: calls ITM when strike < price, puts ITM when strike > price
        let callsItm = 0, callsItmNotional = 0, putsItm = 0, putsItmNotional = 0;
        for (const s of sorted) {
            if (s.strike < cp) { callsItm += s.call_notional > 0 ? 1 : 0; callsItmNotional += s.call_notional; }
            if (s.strike > cp) { putsItm += s.put_notional > 0 ? 1 : 0; putsItmNotional += s.put_notional; }
        }

        // ITM Calls zone (left of price)
        shapes.push({
            type: 'rect', x0: xMin, x1: cp, y0: 0, y1: 1, yref: 'paper',
            fillcolor: 'rgba(56, 189, 248, 0.04)', line: { width: 0 }, layer: 'below'
        });
        // ITM Puts zone (right of price)
        shapes.push({
            type: 'rect', x0: cp, x1: xMax, y0: 0, y1: 1, yref: 'paper',
            fillcolor: 'rgba(239, 112, 112, 0.04)', line: { width: 0 }, layer: 'below'
        });

        const callZoneMid = (xMin + cp) / 2;
        const putZoneMid = (cp + xMax) / 2;

        if (callsItm > 0 || callsItmNotional > 0) {
            annotations.push({
                x: callZoneMid, y: 1.0, yref: 'paper', yanchor: 'bottom',
                text: `<b>${callsItm} Call Strike${callsItm !== 1 ? 's' : ''} ITM</b><br>${compactCurrency(callsItmNotional)}`,
                showarrow: false,
                font: { size: 10, color: 'rgba(56, 189, 248, 0.8)', family: 'Inter, system-ui, sans-serif' },
                bgcolor: 'rgba(9,9,11,0.7)', borderpad: 4,
            });
        }
        if (putsItm > 0 || putsItmNotional > 0) {
            annotations.push({
                x: putZoneMid, y: 1.0, yref: 'paper', yanchor: 'bottom',
                text: `<b>${putsItm} Put Strike${putsItm !== 1 ? 's' : ''} ITM</b><br>${compactCurrency(putsItmNotional)}`,
                showarrow: false,
                font: { size: 10, color: 'rgba(239, 112, 112, 0.8)', family: 'Inter, system-ui, sans-serif' },
                bgcolor: 'rgba(9,9,11,0.7)', borderpad: 4,
            });
        }
    }

    // Current price divider line (always show when price available)
    if (hasPrice) {
        shapes.push({
            type: 'line', x0: cp, x1: cp, y0: 0, y1: 1, yref: 'paper',
            line: { color: isActiveExpiry ? 'rgba(244, 244, 245, 0.35)' : 'rgba(244, 244, 245, 0.15)', width: 1.5, dash: 'dot' }
        });
        annotations.push({
            x: cp, y: 0, yref: 'paper', yanchor: 'top', yshift: 6,
            text: `<b>Price ${formatStrike(cp)}</b>`,
            showarrow: false,
            font: { size: 10, color: isActiveExpiry ? '#f4f4f5' : '#71717a', family: 'Inter, system-ui, sans-serif' },
            bgcolor: 'rgba(9,9,11,0.85)', borderpad: 3,
        });
    }

    const data = [
        {
            type: 'bar', name: 'Put', x: strikeValues,
            y: sorted.map(s => s.put_notional),
            marker: { color: 'rgba(239, 112, 112, 0.7)' },
            width: barWidth,
        },
        {
            type: 'bar', name: 'Call', x: strikeValues,
            y: sorted.map(s => s.call_notional),
            marker: { color: 'rgba(56, 189, 248, 0.7)' },
            width: barWidth,
        },
    ];

    const layout = {
        barmode: 'stack',
        plot_bgcolor: 'transparent', paper_bgcolor: 'transparent',
        font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#71717a' },
        margin: { l: 60, r: 20, t: 40, b: 60 },
        xaxis: {
            title: 'Strike', showgrid: false, tickfont: { size: 10 },
            tickprefix: '$', tickangle: -45,
        },
        yaxis: {
            title: 'Notional ($)', gridcolor: 'rgba(255,255,255,0.06)', tickprefix: '$',
        },
        legend: { orientation: 'h', y: -0.12, font: { size: 11 } },
        hoverlabel: {
            bgcolor: '#0c0c0e',
            font: { color: '#fafafa', family: 'Inter, system-ui, sans-serif' },
            bordercolor: 'rgba(255,255,255,0.06)'
        },
        shapes, annotations,
    };

    if (typeof Plotly !== 'undefined') {
        Plotly.newPlot(heatmapDiv, data, layout, { displayModeBar: false, responsive: true }).then(() => {
            Plotly.Plots.resize(heatmapDiv);
        });
    }
}

function renderPositionsDetailTable(positions) {
    const container = document.getElementById('positions-detail-table');
    if (!container) return;

    if (!positions.length) {
        container.innerHTML = '<p class="empty-state">No open positions for this asset.</p>';
        return;
    }

    let html = `
        <table id="positions-detail-asset-table" class="data-table">
            <thead>
                <tr>
                    <th data-sort-key="created">Date</th>
                    <th data-sort-key="strategy">Strategy</th>
                    <th data-sort-key="side">Side</th>
                    <th data-sort-key="type">Type</th>
                    <th data-sort-key="quantity">Quantity</th>
                    <th data-sort-key="strike">Strike</th>
                    <th data-sort-key="premium">Premium</th>
                    <th data-sort-key="apr">APR</th>
                    <th data-sort-key="expiry">Expiry</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const pos of positions) {
        html += `
            <tr>
                <td data-sort-key="created" data-sort-value="${pos.created_at || ''}">${formatDateLabel(pos.created_at)}</td>
                <td data-sort-key="strategy" data-sort-value="${pos.strategy || ''}">${strategyBadge(pos)}</td>
                <td data-sort-key="side" data-sort-value="${pos.side || ''}">${sideBadge(pos.side)}</td>
                <td data-sort-key="type" data-sort-value="${pos.type || ''}">${pos.type || '—'}</td>
                <td data-sort-key="quantity" data-sort-value="${pos.quantity ?? ''}">${formatNumber(pos.quantity, 4)}</td>
                <td data-sort-key="strike" data-sort-value="${pos.strike ?? ''}">${formatStrike(pos.strike)}</td>
                <td data-sort-key="premium" data-sort-value="${pos.premium ?? ''}">${formatCurrency(pos.premium || 0)}</td>
                <td data-sort-key="apr" data-sort-value="${pos.apr ?? ''}">${formatPercentage(pos.apr)}</td>
                <td data-sort-key="expiry" data-sort-value="${pos.expiry_date || ''}">${formatDateLabel(pos.expiry_date)}</td>
            </tr>
        `;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
    setupSortablePositionsDetailTable();
}

// Collapsible sections functionality
function initCollapsibleSections() {
    const headers = document.querySelectorAll('.collapsible-header');

    headers.forEach(header => {
        const section = header.getAttribute('data-section');
        const content = document.querySelector(`.collapsible-content[data-section="${section}"]`);

        if (!content) return;

        // Restore state from localStorage (default to expanded)
        const savedState = localStorage.getItem(`section-${section}-expanded`);
        const isExpanded = savedState === null ? true : savedState === 'true';

        if (isExpanded) {
            header.classList.add('expanded');
            content.classList.remove('collapsed');
        } else {
            header.classList.remove('expanded');
            content.classList.add('collapsed');
        }

        // Click handler
        header.addEventListener('click', () => {
            const wasExpanded = header.classList.contains('expanded');

            if (wasExpanded) {
                // Collapse
                header.classList.remove('expanded');
                content.classList.add('collapsed');
                localStorage.setItem(`section-${section}-expanded`, 'false');
            } else {
                // Expand
                header.classList.add('expanded');
                content.classList.remove('collapsed');
                localStorage.setItem(`section-${section}-expanded`, 'true');
                // Resize any Plotly charts inside the newly expanded section
                setTimeout(() => {
                    content.querySelectorAll('.js-plotly-plot').forEach(el => {
                        Plotly.Plots.resize(el);
                    });
                }, 350); // wait for CSS max-height transition to finish
            }
        });
    });
}

// Initialize dashboard
document.addEventListener('DOMContentLoaded', () => {
    defaultAccount = document.body.dataset.defaultAccount || '';
    accountInputEl = document.getElementById('account-input');
    accountStatusEl = document.getElementById('account-status');
    accountDisplayEl = document.getElementById('current-wallet-display');
    splashScreenEl = document.getElementById('splash-screen');
    mainContentEl = document.getElementById('main-content');
    splashAccountInputEl = document.getElementById('splash-account-input');
    splashLaunchEl = document.getElementById('splash-launch');
    splashTypingEl = document.getElementById('splash-typing');
    splashErrorEl = document.getElementById('splash-error');
    const applyButton = document.getElementById('account-apply');

    let savedAccount = '';
    try {
        savedAccount = (localStorage.getItem('dashboardAccount') || '').trim();
    } catch (_) {
        savedAccount = '';
    }
    const initialAccount = savedAccount || '';
    currentAccount = '';
    // No dashboard input; splash handles entry. Keep display in sync.
    if (splashAccountInputEl) {
        splashAccountInputEl.value = initialAccount;
    }
    updateAccountUI(currentAccount);

    if (applyButton) {
        applyButton.addEventListener('click', () => {
            launchDashboard(accountInputEl ? accountInputEl.value : '', { fromSplash: false });
        });
    }

    if (accountInputEl) {
        accountInputEl.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                launchDashboard(accountInputEl.value, { fromSplash: false });
            }
        });
    }

    if (splashLaunchEl) {
        splashLaunchEl.addEventListener('click', () => {
            launchDashboard(splashAccountInputEl ? splashAccountInputEl.value : '', { fromSplash: true });
        });
    }
    if (splashAccountInputEl) {
        splashAccountInputEl.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                launchDashboard(splashAccountInputEl.value, { fromSplash: true });
            }
        });
    }

    initCollapsibleSections();
    initHistoryModal();

    setAccountStatus('Enter a wallet address');

    // Auto-refresh every 3 minutes
    setInterval(() => {
        if (currentAccount && mainContentEl && mainContentEl.style.display !== 'none') {
            refreshAllData();
        }
    }, 180000);
});




