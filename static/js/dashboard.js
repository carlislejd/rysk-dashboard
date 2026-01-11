// Dashboard JavaScript

// Format numbers
function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined) return '0.00';
    return parseFloat(num).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

function formatCurrency(num, decimals = 2) {
    if (num === null || num === undefined) return '$0.00';
    const sign = num < 0 ? '-' : '';
    const absValue = Math.abs(num);
    return `${sign}$${formatNumber(absValue, decimals)}`;
}

function formatPercentage(value, decimals = 2) {
    if (value === null || value === undefined) return '—';
    return `${formatNumber(value, decimals)}%`;
}

function formatDays(value) {
    if (value === null || value === undefined) return '—';
    if (value <= 0) return 'Expired';
    return `${formatNumber(value, 1)}d`;
}

function formatDateLabel(label) {
    return label || '—';
}

function formatAddress(address) {
    if (!address) return 'Not configured';
    const str = String(address);
    if (str.length <= 10) return str;
    return `${str.slice(0, 10)}...${str.slice(-8)}`;
}

function statusBadge(status) {
    if (!status) return '';
    const normalized = status.toLowerCase();
    let badgeClass = 'status-default';
    if (normalized === 'active') badgeClass = 'status-active';
    if (normalized === 'expired') badgeClass = 'status-expired';
    return `<span class="status-badge ${badgeClass}">${status}</span>`;
}

function sideBadge(side) {
    if (!side) return '';
    const normalized = side.toLowerCase();
    const badgeClass = normalized === 'buy' ? 'side-buy' : 'side-sell';
    return `<span class="side-badge ${badgeClass}">${side}</span>`;
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
    accountStatusEl.style.color = isError ? '#ff5555' : '#888';
}

let positionsAssetSummary = [];
let openPositionsData = [];
let selectedAssetSymbol = null;
let historyDataCache = null;
let historyDataTimestamp = null;
let historyModalInitialized = false;

function getTokenClass(token) {
    return token.toLowerCase();
}

function getAPYClass(apy) {
    if (apy >= 50) return 'apy-high';
    if (apy >= 20) return 'apy-medium';
    return 'apy-low';
}

function getRiskClass(risk) {
    if (risk < 10) return 'risk-low';
    if (risk < 20) return 'risk-medium';
    return 'risk-high';
}

// Load balances
async function loadBalances() {
    const loading = document.getElementById('balances-loading');
    const content = document.getElementById('balances-content');
    const error = document.getElementById('balances-error');
    const table = document.getElementById('balances-table');

    loading.style.display = 'block';
    if (error) error.style.display = 'none';

    try {
        const response = await fetchWithAccount('/api/balances');
        const data = await response.json();

        loading.style.display = 'none';

        if (data.success) {
            const resolvedAccount = data.account || currentAccount || defaultAccount || '';
            if (resolvedAccount && resolvedAccount !== currentAccount) {
                currentAccount = resolvedAccount;
                try {
                    localStorage.setItem('dashboardAccount', currentAccount || '');
                } catch (_) {
                    // Ignore storage errors (e.g. private browsing)
                }
            }
            updateAccountUI(currentAccount);
            setAccountStatus('');

            table.innerHTML = '';

            let totalNotional = 0;
            for (const [token, balance] of Object.entries(data.balances)) {
                const price = data.prices?.[token] || 0;
                const notional = data.notional?.[token] || 0;
                totalNotional += notional;

                // Get token address from API response
                const address = data.addresses?.[token] || 'N/A';
                const row = document.createElement('tr');

                // Format price and notional based on token
                let priceStr = 'N/A';
                if (price > 0) {
                    if (token === 'BTC') {
                        priceStr = formatNumber(price, 0);
                    } else if (price < 1) {
                        priceStr = formatNumber(price, 6);
                    } else if (token === 'PUMP' || token === 'PURR') {
                        priceStr = formatNumber(price, 4);
                    } else {
                        priceStr = formatNumber(price, 2);
                    }
                }
                let notionalStr = notional > 0 ? '$' + formatNumber(notional, 2) : 'N/A';

                // For BTC, use more decimals for price
                if (token === 'BTC' && price > 0) {
                    priceStr = formatNumber(price, 0);
                }

                row.innerHTML = `
                    <td><span class="token-badge ${getTokenClass(token)}">${token}</span></td>
                    <td>${formatNumber(balance, 6)}</td>
                    <td>${priceStr}</td>
                    <td>${notionalStr}</td>
                    <td><code>${address !== 'N/A' ? address : 'N/A'}</code></td>
                `;
                table.appendChild(row);
            }

            const totalRow = document.createElement('tr');
            totalRow.classList.add('total-row');
            totalRow.innerHTML = `
                <td colspan="3">Total Notional</td>
                <td>$${formatNumber(totalNotional, 2)}</td>
                <td></td>
            `;
            table.appendChild(totalRow);

            content.style.display = 'block';
            error.style.display = 'none';
        } else {
            const message = data.error || 'Failed to load balances';
            error.textContent = message;
            error.style.display = 'block';
            if (content) content.style.display = 'none';
            setAccountStatus(message, true);
        }
    } catch (err) {
        loading.style.display = 'none';
        error.textContent = 'Error loading balances: ' + err.message;
        error.style.display = 'block';
        if (content) content.style.display = 'none';
        setAccountStatus('Failed to load balances', true);
    }
}

// Load inventory
async function loadInventory() {
    const loading = document.getElementById('inventory-loading');
    const content = document.getElementById('inventory-content');
    const error = document.getElementById('inventory-error');
    const tables = document.getElementById('inventory-tables');

    try {
        const response = await fetch('/api/inventory');
        const data = await response.json();

        loading.style.display = 'none';

        if (data.success) {
            tables.innerHTML = '';

            for (const [asset, options] of Object.entries(data.inventory)) {
                if (options.length === 0) continue;

                const tableDiv = document.createElement('div');
                tableDiv.className = 'inventory-table';
                tableDiv.id = `inventory-${asset}`;
                if (asset === 'BTC') tableDiv.classList.add('active');

                let html = `
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Strike</th>
                                <th>OTM %</th>
                                <th>APY</th>
                                <th>Risk</th>
                                <th>Expiry</th>
                            </tr>
                        </thead>
                        <tbody>
                `;

                for (const opt of options.slice(0, 10)) {
                    const strike = asset === 'BTC' ? formatNumber(opt.strike, 0) : formatNumber(opt.strike, 2);
                    html += `
                        <tr>
                            <td>$${strike}</td>
                            <td>${opt.moneyness.toFixed(2)}%</td>
                            <td class="${getAPYClass(opt.apy)}">${opt.apy.toFixed(2)}%</td>
                            <td class="${getRiskClass(opt.assignment_risk)}">${opt.assignment_risk.toFixed(1)}%</td>
                            <td>${opt.expiry}</td>
                        </tr>
                    `;
                }

                html += `
                        </tbody>
                    </table>
                `;

                tableDiv.innerHTML = html;
                tables.appendChild(tableDiv);
            }

            content.style.display = 'block';

            // Setup tab switching
            setupTabs();
        } else {
            error.textContent = data.error || 'Failed to load inventory';
            error.style.display = 'block';
        }
    } catch (err) {
        loading.style.display = 'none';
        error.textContent = 'Error loading inventory: ' + err.message;
        error.style.display = 'block';
    }
}

// Setup tab switching
function setupTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            // Remove active class from all buttons and tables
            tabButtons.forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.inventory-table').forEach(table => {
                table.classList.remove('active');
            });

            // Add active class to clicked button
            button.classList.add('active');

            // Show corresponding table
            const asset = button.dataset.asset;
            const table = document.getElementById(`inventory-${asset}`);
            if (table) {
                table.classList.add('active');
            }
        });
    });
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
                <div id="positions-detail-summary" class="positions-detail-summary"></div>
                <div id="positions-heatmap" class="positions-heatmap"></div>
                <div id="positions-detail-table" class="positions-detail-table"></div>
            </div>
        `;

        html += `<h3 class="subsection-title">Current Covered Calls (${openTitleCount})</h3>`;

        if (openPositions.length > 0) {
            html += `
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Symbol</th>

                            <th>Side</th>
                            <th>Type</th>
                            <th>Created</th>
                            <th>Expiry</th>
                            <th>Quantity</th>
                            <th>Strike</th>
                            <th>Premium</th>
                            <th>APR</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            for (const pos of openPositions) {
                html += `
                    <tr>
                        <td>${pos.symbol || '—'}</td>
                        <td>${sideBadge(pos.side)}</td>
                        <td>${pos.type || '—'}</td>
                        <td>${formatDateLabel(pos.created_at)}</td>
                        <td>${formatDateLabel(pos.expiry_date)}</td>
                        <td>${formatNumber(pos.quantity, 4)}</td>
                        <td>${formatCurrency(pos.strike, pos.strike > 1000 ? 0 : 2)}</td>
                        <td>${formatCurrency(pos.premium || 0)}</td>
                        <td>${formatPercentage(pos.apr)}</td>
                        <td>${statusBadge(pos.status)}</td>
                    </tr>
                `;
            }

            html += '</tbody></table>';
        } else {
            html += '<p class="empty-state">No open covered calls right now.</p>';
        }

        content.innerHTML = html;
        content.style.display = 'block';

        positionsAssetSummary = assetSummary;
        openPositionsData = openPositions;
        setupAssetSummaryHandlers();

        if (previousAsset && assetSummary.some(a => a.symbol === previousAsset)) {
            showAssetPositions(previousAsset);
        } else {
            selectedAssetSymbol = null;
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
        return `<h3 class="subsection-title">Expired Covered Calls (${titleCount})</h3><p class="empty-state">No expired positions yet.</p>`;
    }

    const totalPages = Math.max(1, Math.ceil(filteredCount / pageSize));
    const currentPage = Math.min(Math.max(page, 1), totalPages);
    const startIdx = (currentPage - 1) * pageSize;
    const endIdx = Math.min(startIdx + pageSize, filteredCount);
    const pageData = filtered.slice(startIdx, endIdx);

    let html = `<h3 class="subsection-title">Expired Covered Calls (${titleCount})</h3>`;

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
        let outcomeHtml = position.outcome || '—';
        if (position.expiry_price !== null && position.expiry_price !== undefined) {
            const expiryDecimals = position.expiry_price >= 1000 ? 0 : position.expiry_price >= 1 ? 2 : 6;
            outcomeHtml += `<div class="table-subtext">Expiry ${formatCurrency(position.expiry_price, expiryDecimals)}</div>`;
        }

        html += `
            <tr>
                <td>${formatDateLabel(position.created_at)}</td>
                <td>${position.symbol || '—'}</td>
                <td>${position.type || '—'}</td>
                <td>${sideBadge(position.side)}</td>
                <td>${formatNumber(position.quantity, 4)}</td>
                <td>${formatCurrency(position.strike, position.strike > 1000 ? 0 : 2)}</td>
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
    cards.forEach(card => {
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => {
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
            `Strike: ${formatCurrency(p.strike || 0, (p.strike || 0) > 1000 ? 0 : 2)}`,
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
            color: '#00ff00',
            size: sizes,
            opacity: opacities
        },
        text: hover,
        hovertemplate: '%{text}<extra></extra>',
        name: 'APR'
    };

    const avgApr = points.reduce((sum, p) => sum + p.y, 0) / points.length;

    const layout = {
        plot_bgcolor: '#0a0a0a',
        paper_bgcolor: '#0a0a0a',
        font: { color: '#00ff00' },
        margin: { l: 60, r: 20, t: 30, b: 60 },
        xaxis: {
            title: 'Date',
            color: '#888',
            gridcolor: '#333',
            type: 'date'
        },
        yaxis: {
            title: 'APR (%)',
            color: '#888',
            gridcolor: '#333'
        },
        showlegend: true,
        legend: {
            bgcolor: '#0a0a0a',
            bordercolor: '#333',
            borderwidth: 1
        }
    };

    Plotly.newPlot(plot, [trace, {
        type: 'scatter',
        mode: 'lines',
        x: [points[0].x, points[points.length - 1].x],
        y: [avgApr, avgApr],
        line: { color: '#ffaa00', dash: 'dash' },
        name: `Avg APR ${formatPercentage(avgApr)}`
    }], layout, { displayModeBar: false, responsive: true });
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
        html += '<thead><tr><th>Date</th><th>Symbol</th><th>Outcome</th><th>Quantity</th><th>Strike</th><th>Premium</th><th>APR</th><th>Expiry</th></tr></thead>';
        html += '<tbody>';
        for (const position of topPremiumPositions) {
            const strikeDecimals = position.strike > 1000 ? 0 : position.strike > 1 ? 2 : 6;
            html += '<tr>';
            html += `<td>${formatDateLabel(position.created_at)}</td>`;
            html += `<td>${position.symbol || '—'}</td>`;
            html += `<td>${position.outcome || '—'}</td>`;
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
        html += '<thead><tr><th>Date</th><th>Symbol</th><th>Outcome</th><th>Quantity</th><th>Strike</th><th>Premium</th><th>APR</th><th>Expiry</th></tr></thead>';
        html += '<tbody>';
        for (const position of topAprPositions) {
            const strikeDecimals = position.strike > 1000 ? 0 : position.strike > 1 ? 2 : 6;
            html += '<tr>';
            html += `<td>${formatDateLabel(position.created_at)}</td>`;
            html += `<td>${position.symbol || '—'}</td>`;
            html += `<td>${position.outcome || '—'}</td>`;
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

async function loadAllData() {
    const tasks = [];

    if (!currentAccount) {
        setAccountStatus('Enter a wallet address');
        await Promise.all(tasks);
        return;
    }

    setAccountStatus('Loading...');
    tasks.push(
        loadPositions(),
        loadHistory()
    );

    await Promise.all(tasks);
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
    selectedAssetSymbol = asset;
    document.querySelectorAll('.asset-card').forEach(card => {
        card.classList.toggle('selected', card.dataset.asset === asset);
    });
    const detail = document.getElementById('positions-detail');
    if (!detail) return;

    const summary = positionsAssetSummary.find(a => a.symbol === asset);
    const positions = openPositionsData.filter(pos => (pos.symbol || '').toUpperCase() === asset.toUpperCase());

    document.getElementById('positions-detail-title').textContent = `${asset} Covered Calls`;

    const summaryContainer = document.getElementById('positions-detail-summary');
    if (summaryContainer) {
        if (summary) {
            summaryContainer.innerHTML = `
                <div class="summary-grid detail-grid">
                    <div class="summary-card">
                        <span class="summary-label">Positions</span>
                        <span class="summary-value">${formatNumber(summary.count || positions.length || 0, 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Quantity</span>
                        <span class="summary-value">${formatNumber(summary.quantity_total || 0, 4)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Notional</span>
                        <span class="summary-value">${formatCurrency(summary.notional_total || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Premium</span>
                        <span class="summary-value">${formatCurrency(summary.premium_total || 0)}</span>
                    </div>
                    <div class="summary-card">
                        <span class="summary-label">Avg APR</span>
                        <span class="summary-value">${summary.avg_apr ? formatPercentage(summary.avg_apr) : '—'}</span>
                    </div>
                </div>
            `;
        } else {
            summaryContainer.innerHTML = '<p class="empty-state">No summary available for this asset.</p>';
        }
    }

    renderPositionsHeatmap(summary);
    renderPositionsDetailTable(positions);

    detail.style.display = 'block';
}

function renderPositionsHeatmap(summary) {
    const heatmapDiv = document.getElementById('positions-heatmap');
    if (!heatmapDiv) return;

    const strikes = summary?.strikes || [];
    if (!strikes.length) {
        heatmapDiv.innerHTML = '<p class="empty-state">No strike distribution yet.</p>';
        return;
    }

    // Sort strikes and prepare data for bar chart
    const sorted = [...strikes].sort((a, b) => (a.strike || 0) - (b.strike || 0));
    
    const xStrikes = [];
    const yNotionals = [];
    const hoverTexts = [];
    let maxNotional = 0;

    // Only include strikes that have positions
    for (const entry of sorted) {
        const strike = entry.strike || 0;
        const notional = entry.notional_total || 0;
        
        if (notional > 0) {
            const strikeDecimals = strike > 1000 ? 0 : strike > 1 ? 2 : 6;
            const display = `$${formatNumber(strike, strikeDecimals)}`;
            xStrikes.push(display);
            yNotionals.push(notional);
            maxNotional = Math.max(maxNotional, notional);
            
            hoverTexts.push(
                `Strike: ${display}<br>` +
                `Positions: ${formatNumber(entry.count, 0)}<br>` +
                `Notional: ${formatCurrency(notional)}<br>` +
                `Premium: ${formatCurrency(entry.premium_total || 0)}<br>` +
                `Avg APR: ${entry.avg_apr ? formatPercentage(entry.avg_apr) : '—'}`
            );
        }
    }

    if (xStrikes.length === 0) {
        heatmapDiv.innerHTML = '<p class="empty-state">No strike distribution yet.</p>';
        return;
    }

    // Create bar chart data
    const data = [{
        type: 'bar',
        x: xStrikes,
        y: yNotionals,
        hovertext: hoverTexts,
        hovertemplate: '%{hovertext}<extra></extra>',
        marker: {
            color: yNotionals.map(val => {
                // Color gradient from green (low) to yellow (high)
                const ratio = maxNotional > 0 ? val / maxNotional : 0;
                if (ratio < 0.33) return '#00ff00';
                if (ratio < 0.66) return '#88ff00';
                return '#ffff00';
            }),
            line: {
                color: '#00ff00',
                width: 1.5
            },
            opacity: 0.9
        },
        width: Math.max(0.45, Math.min(0.9, 35 / xStrikes.length)), // Adaptive bar width
        textposition: 'none'
    }];

    const layout = {
        plot_bgcolor: '#0a0a0a',
        paper_bgcolor: '#0a0a0a',
        font: { family: 'Courier New, Monaco, Menlo, monospace', size: 11, color: '#00ff00' },
        margin: { l: 80, r: 20, t: 20, b: 60 },
        xaxis: {
            title: {
                text: 'Strike Price',
                font: { color: '#888', size: 12 }
            },
            color: '#888',
            gridcolor: '#333',
            tickangle: xStrikes.length > 5 ? -45 : 0,
            type: 'category' // Treat as categorical to avoid spacing issues
        },
        yaxis: {
            title: {
                text: 'Notional Value',
                font: { color: '#888', size: 12 }
            },
            color: '#888',
            gridcolor: '#333',
            tickformat: '$,.0f'
        },
        hoverlabel: {
            bgcolor: '#0d0d0d',
            font: { color: '#00ff00' },
            bordercolor: '#00ff00'
        },
        bargap: 0.35 // Gap between bars
    };

    const config = {
        displayModeBar: false,
        responsive: true
    };

    if (typeof Plotly !== 'undefined') {
        Plotly.newPlot(heatmapDiv, data, layout, config).then(() => {
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
        <table class="data-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Side</th>
                    <th>Type</th>
                    <th>Quantity</th>
                    <th>Strike</th>
                    <th>Premium</th>
                    <th>APR</th>
                    <th>Expiry</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const pos of positions) {
        html += `
            <tr>
                <td>${formatDateLabel(pos.created_at)}</td>
                <td>${sideBadge(pos.side)}</td>
                <td>${pos.type || '—'}</td>
                <td>${formatNumber(pos.quantity, 4)}</td>
                <td>${formatCurrency(pos.strike, pos.strike > 1000 ? 0 : 2)}</td>
                <td>${formatCurrency(pos.premium || 0)}</td>
                <td>${formatPercentage(pos.apr)}</td>
                <td>${formatDateLabel(pos.expiry_date)}</td>
            </tr>
        `;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
}

// Load suggestions
async function loadSuggestions() {
    const loading = document.getElementById('suggestions-loading');
    const content = document.getElementById('suggestions-content');
    const error = document.getElementById('suggestions-error');

    loading.style.display = 'block';
    if (error) error.style.display = 'none';

    try {
        const response = await fetchWithAccount('/api/suggestions');
        const data = await response.json();

        loading.style.display = 'none';

        if (data.success) {
            if (data.account && data.account !== currentAccount) {
                currentAccount = data.account;
                try {
                    localStorage.setItem('dashboardAccount', currentAccount || '');
                } catch (_) {
                    // Ignore storage issues
                }
                updateAccountUI(currentAccount);
            }
            content.innerHTML = '';

            if (Object.keys(data.suggestions).length === 0) {
                content.innerHTML = '<p>No suggestions available. Make sure you have token balances.</p>';
                content.style.display = 'block';
                return;
            }

            for (const [asset, suggestion] of Object.entries(data.suggestions)) {
                const card = document.createElement('div');
                card.className = 'suggestion-card';

                let html = `
                    <div class="suggestion-header">
                        <div>
                            <span class="suggestion-asset token-badge ${getTokenClass(asset)} clickable-asset" data-asset="${asset}" style="cursor: pointer; text-decoration: underline;">${asset}</span>
                            <span class="suggestion-balance">Balance: ${formatNumber(suggestion.balance, 6)}</span>
                        </div>
                        <div>
                            <span style="color: #666; font-size: 0.9em;">Target: ${suggestion.target_range} APR</span>
                        </div>
                    </div>
                    <div class="suggestion-options">
                `;

                for (const opt of suggestion.options) {
                    const strike = asset === 'BTC' ? formatNumber(opt.strike, 0) : formatNumber(opt.strike, 2);
                    let badgeClass = 'balanced';
                    let badgeText = 'Balanced';

                    if (opt.apy >= 50 && opt.assignment_risk < 15) {
                        badgeClass = 'excellent';
                        badgeText = '⭐ Excellent';
                    } else if (opt.apy >= 25 && opt.assignment_risk < 20) {
                        badgeClass = 'good';
                        badgeText = '✅ Good';
                    }

                    // Rich/Cheap indicator
                    let richCheapBadge = '';
                    if (opt.richness && opt.richness.rich_cheap) {
                        const rc = opt.richness.rich_cheap;
                        if (rc === 'rich') {
                            richCheapBadge = '<span class="rich-cheap-badge rich" title="Option is rich (IV > RV)">🔴 Rich</span>';
                        } else if (rc === 'cheap') {
                            richCheapBadge = '<span class="rich-cheap-badge cheap" title="Option is cheap (IV < RV)">🟢 Cheap</span>';
                        } else if (rc === 'fair') {
                            richCheapBadge = '<span class="rich-cheap-badge fair" title="Option is fairly priced">⚪ Fair</span>';
                        } else if (rc === 'slightly_rich') {
                            richCheapBadge = '<span class="rich-cheap-badge slightly-rich" title="Option is slightly rich">🟡 Slightly Rich</span>';
                        } else if (rc === 'slightly_cheap') {
                            richCheapBadge = '<span class="rich-cheap-badge slightly-cheap" title="Option is slightly cheap">🟢 Slightly Cheap</span>';
                        }
                    }

                    // IV vs RV
                    let ivRvHtml = '';
                    if (opt.implied_vol && opt.realized_vol) {
                        const ivRvSpread = opt.richness?.iv_rv_spread || (opt.implied_vol - opt.realized_vol);
                        ivRvHtml = `
                            <div class="suggestion-metric">
                                <span class="suggestion-metric-label">IV vs RV</span>
                                <span class="suggestion-metric-value">${opt.implied_vol.toFixed(1)}% / ${opt.realized_vol.toFixed(1)}%</span>
                                <span class="suggestion-metric-sub" style="font-size: 0.75em; color: ${ivRvSpread > 0 ? '#ff0000' : '#00ff00'};">
                                    (${ivRvSpread > 0 ? '+' : ''}${ivRvSpread.toFixed(1)}%)
                                </span>
                            </div>
                        `;
                    }

                    // Greeks
                    let greeksHtml = '';
                    if (opt.greeks) {
                        const g = opt.greeks;
                        greeksHtml = `
                            <div class="suggestion-metric">
                                <span class="suggestion-metric-label">Greeks</span>
                                <span class="suggestion-metric-value" style="font-size: 0.8em;">
                                    Δ${g.delta.toFixed(2)} | Γ${g.gamma.toFixed(3)} | ν${g.vega.toFixed(2)} | θ${g.theta.toFixed(4)}
                                </span>
                            </div>
                        `;
                    }

                    html += `
                        <div class="suggestion-option">
                            <div class="suggestion-option-header">
                                <span class="suggestion-strike">$${strike}</span>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    ${richCheapBadge}
                                    <span class="suggestion-badge ${badgeClass}">${badgeText}</span>
                                </div>
                            </div>
                            <div class="suggestion-metrics">
                                <div class="suggestion-metric">
                                    <span class="suggestion-metric-label">APY</span>
                                    <span class="suggestion-metric-value ${getAPYClass(opt.apy)}">${opt.apy.toFixed(2)}%</span>
                                </div>
                                <div class="suggestion-metric">
                                    <span class="suggestion-metric-label">Assignment Risk</span>
                                    <span class="suggestion-metric-value ${getRiskClass(opt.assignment_risk)}">${opt.assignment_risk.toFixed(1)}%</span>
                                </div>
                                ${ivRvHtml}
                                <div class="suggestion-metric">
                                    <span class="suggestion-metric-label">OTM</span>
                                    <span class="suggestion-metric-value">${opt.moneyness.toFixed(2)}%</span>
                                </div>
                                <div class="suggestion-metric">
                                    <span class="suggestion-metric-label">Expiry</span>
                                    <span class="suggestion-metric-value">${opt.expiry}</span>
                                </div>
                                ${greeksHtml}
                            </div>
                        </div>
                    `;
                }

                html += `
                    </div>
                `;

                card.innerHTML = html;
                content.appendChild(card);
            }

            // Set up click handlers for clickable assets (after content is added)
            document.querySelectorAll('.clickable-asset').forEach(el => {
                el.addEventListener('click', (e) => {
                    e.preventDefault();
                    const asset = el.getAttribute('data-asset');
                    if (asset) {
                        loadChart(asset);
                    }
                });
            });

            content.style.display = 'block';
        } else {
            error.textContent = data.error || 'Failed to load suggestions';
            error.style.display = 'block';
        }
    } catch (err) {
        loading.style.display = 'none';
        error.textContent = 'Error loading suggestions: ' + err.message;
        error.style.display = 'block';
    }
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
            }
        });
    });
}

// Chart functionality
async function loadChart(asset) {
    const chartContainer = document.getElementById('chart-container');
    const chartTitle = document.getElementById('chart-title');
    const chartPlot = document.getElementById('chart-plot');
    const chartLoading = document.getElementById('chart-loading');

    // Show container first and ensure it's visible
    chartContainer.style.display = 'block';
    chartPlot.style.display = 'block';
    chartPlot.style.width = '100%';
    chartPlot.style.height = '500px';
    chartPlot.style.minHeight = '500px';

    chartTitle.textContent = `${asset} Price Chart (7 Days)`;
    chartLoading.style.display = 'block';
    chartPlot.innerHTML = '';

    // Force a reflow to ensure dimensions are calculated
    chartContainer.offsetHeight;

    try {
        const response = await fetchWithAccount('/api/chart', { asset, days: 7 });
        const data = await response.json();

        chartLoading.style.display = 'none';

        if (data.success) {
            const chartData = data.data;
            const times = chartData.times.map(t => new Date(t));

            // Create candlestick trace
            const candlestick = {
                x: times,
                open: chartData.opens,
                high: chartData.highs,
                low: chartData.lows,
                close: chartData.closes,
                type: 'candlestick',
                name: asset,
                increasing: { line: { color: '#00ff00' } },
                decreasing: { line: { color: '#ff0000' } },
                xaxis: 'x',
                yaxis: 'y'
            };

            const traces = [candlestick];

            // Add strike price lines
            if (chartData.strikes && chartData.strikes.length > 0) {
                chartData.strikes.forEach((strikeData, idx) => {
                    const strike = strikeData.strike;
                    const color = idx === 0 ? '#ffff00' : idx === 1 ? '#00ffff' : '#ff00ff';

                    traces.push({
                        x: [times[0], times[times.length - 1]],
                        y: [strike, strike],
                        type: 'scatter',
                        mode: 'lines',
                        name: `Strike $${strike.toFixed(asset === 'BTC' ? 0 : 2)} (${strikeData.apy.toFixed(1)}% APY)`,
                        line: {
                            color: color,
                            width: 2,
                            dash: 'dash'
                        },
                        xaxis: 'x',
                        yaxis: 'y'
                    });
                });
            }

            // Terminal-style layout
            const layout = {
                plot_bgcolor: '#0a0a0a',
                paper_bgcolor: '#0a0a0a',
                font: {
                    family: 'Courier New, Monaco, Menlo, monospace',
                    size: 11,
                    color: '#00ff00'
                },
                xaxis: {
                    gridcolor: '#333',
                    gridwidth: 1,
                    showgrid: true,
                    color: '#888',
                    title: {
                        text: 'Time',
                        font: { color: '#888' }
                    }
                },
                yaxis: {
                    gridcolor: '#333',
                    gridwidth: 1,
                    showgrid: true,
                    color: '#888',
                    title: {
                        text: 'Price',
                        font: { color: '#888' }
                    }
                },
                margin: { l: 60, r: 20, t: 20, b: 50 },
                showlegend: true,
                legend: {
                    bgcolor: '#0a0a0a',
                    bordercolor: '#333',
                    borderwidth: 1,
                    font: { color: '#00ff00', size: 10 }
                },
                hovermode: 'x unified'
            };

            const config = {
                displayModeBar: false,
                responsive: true,
                autosize: true
            };

            // Ensure container has dimensions before plotting
            const plotDiv = document.getElementById('chart-plot');

            // Small delay to ensure DOM is ready
            setTimeout(() => {
                Plotly.newPlot('chart-plot', traces, layout, config).then(() => {
                    // Resize after initial render to ensure proper sizing
                    Plotly.Plots.resize('chart-plot');
                });
            }, 50);
        } else {
            chartPlot.innerHTML = `<p style="color: #ff0000;">Error: ${data.error}</p>`;
        }
    } catch (err) {
        chartLoading.style.display = 'none';
        chartPlot.innerHTML = `<p style="color: #ff0000;">Error loading chart: ${err.message}</p>`;
    }
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

    const chartClose = document.getElementById('chart-close');
    if (chartClose) {
        chartClose.addEventListener('click', () => {
            document.getElementById('chart-container').style.display = 'none';
        });
    }

    window.addEventListener('resize', () => {
        const chartPlot = document.getElementById('chart-plot');
        if (chartPlot && chartPlot.style.display !== 'none' && typeof Plotly !== 'undefined') {
            Plotly.Plots.resize('chart-plot');
        }
    });

    setAccountStatus('Enter a wallet address');

    // Auto-refresh every 3 minutes
    setInterval(() => {
        if (currentAccount && mainContentEl && mainContentEl.style.display !== 'none') {
            refreshAllData();
        }
    }, 180000);
});




