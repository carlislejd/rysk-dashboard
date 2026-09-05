// Shared utility functions for Rysk dashboards

// ── Theme Toggle (Day/Night) ──

function initTheme() {
    let saved = 'light';
    try { saved = localStorage.getItem('rysk-theme') || 'light'; } catch (_) {}
    document.documentElement.setAttribute('data-theme', saved);
    updateToggleIcons(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('rysk-theme', next); } catch (_) {}
    updateToggleIcons(next);
    // Re-render any visible Plotly charts with new theme colors
    replotAllCharts();
}

function updateToggleIcons(theme) {
    // ☾ for dark (click to go light), ☀ for light (click to go dark)
    const icon = theme === 'dark' ? '\u263E' : '\u2600';
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.textContent = icon;
        btn.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`);
    });
}

function replotAllCharts() {
    if (typeof Plotly === 'undefined') return;
    document.querySelectorAll('.js-plotly-plot').forEach(el => {
        const theme = getPlotlyTheme();
        Plotly.relayout(el, {
            'font.color': theme.fontColor,
            'xaxis.gridcolor': theme.gridColor,
            'yaxis.gridcolor': theme.gridColor,
        });
    });
}

function getPlotlyTheme() {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    return {
        fontColor: isLight ? '#68776b' : '#a9bbb3',
        gridColor: isLight ? '#e5e7de' : '#2b3a39',
        annotationBg: isLight ? '#fdfdf9' : '#192525',
        annotationColor: isLight ? '#53635a' : '#b8c6c1',
        zoneCallBg: isLight ? 'rgba(0,132,184,0.06)' : 'rgba(0,212,255,0.05)',
        zonePutBg: isLight ? 'rgba(227,39,93,0.06)' : 'rgba(255,77,109,0.05)',
        priceLineColor: isLight ? 'rgba(0, 132, 91, 0.58)' : 'rgba(242, 255, 247, 0.4)',
        priceLineMutedColor: isLight ? 'rgba(0, 132, 91, 0.38)' : 'rgba(244, 244, 245, 0.2)',
        // Marker colors stay consistent across themes (the accent/semantic colors handle contrast)
    };
}

// Apply theme on load
initTheme();

// Wire up all toggle buttons after DOM ready
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.addEventListener('click', toggleTheme);
    });
});

function smartDecimals(value) {
    if (value === null || value === undefined || value === 0) return 2;
    const abs = Math.abs(value);
    if (abs >= 1000) return 0;    // BTC strikes, SOL, ETH, ZEC
    if (abs >= 1) return 2;       // HYPE, XRP (shows 32.50)
    if (abs >= 0.01) return 3;    // PURR (shows 0.072)
    return 4;                     // PUMP (shows 0.0018)
}

function formatStrike(value) {
    if (value === null || value === undefined) return '—';
    const decimals = smartDecimals(value);
    return '$' + formatNumber(value, decimals);
}

function getStrikeBarWidth(strikeValues, gapRatio = 0.8) {
    const values = (strikeValues || [])
        .map(Number)
        .filter(Number.isFinite)
        .sort((a, b) => a - b);

    const requestedRatio = Number(gapRatio);
    const safeGapRatio = Number.isFinite(requestedRatio) && requestedRatio > 0
        ? Math.min(requestedRatio, 1)
        : 0.8;

    const fallbackWidth = (strike) => {
        const absStrike = Math.abs(Number(strike) || 0);
        if (absStrike === 0) return 0.1;

        const magnitude = 10 ** Math.floor(Math.log10(absStrike));
        return magnitude * 0.04;
    };

    if (values.length <= 1) {
        return fallbackWidth(values[0]);
    }

    let minGap = Infinity;
    for (let i = 1; i < values.length; i++) {
        const gap = values[i] - values[i - 1];
        if (gap > 0 && gap < minGap) minGap = gap;
    }

    if (!Number.isFinite(minGap)) {
        return fallbackWidth(values[0]);
    }

    return minGap * safeGapRatio;
}

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

function compactCurrency(num, decimals = null) {
    if (num === null || num === undefined) return '$0';
    const value = Number(num) || 0;
    const abs = Math.abs(value);
    const sign = value < 0 ? '-' : '';
    if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(decimals ?? 1)}B`;
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(decimals ?? 1)}M`;
    if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(decimals ?? 0)}K`;
    return formatCurrency(num, 0);
}

function formatTileCurrency(num, compactDecimals = null) {
    const value = Number(num) || 0;
    return Math.abs(value) >= 10000 ? compactCurrency(value, compactDecimals) : formatCurrency(value);
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

function getPositionStrategy(position) {
    const explicitStrategy = String(position?.strategy || '').trim().toLowerCase();
    if (explicitStrategy === 'cash_secured_put') {
        return {
            key: 'cash-secured-put',
            label: 'Cash-Secured Put',
            shortLabel: 'CSP'
        };
    }
    if (explicitStrategy === 'covered_call') {
        return {
            key: 'covered-call',
            label: 'Covered Call',
            shortLabel: 'CC'
        };
    }

    const side = String(position?.side || '').trim().toLowerCase();
    const type = String(position?.type || '').trim().toLowerCase();
    const sellLike = side === 'sell' || side === 'short' || side === 'write';
    const buyLike = side === 'buy' || side === 'long';

    if (type === 'put' && (sellLike || !buyLike)) {
        return {
            key: 'cash-secured-put',
            label: 'Cash-Secured Put',
            shortLabel: 'CSP'
        };
    }

    if (type === 'call' && (sellLike || !buyLike)) {
        return {
            key: 'covered-call',
            label: 'Covered Call',
            shortLabel: 'CC'
        };
    }

    return {
        key: 'other',
        label: 'Other',
        shortLabel: 'Other'
    };
}

function strategyBadge(position) {
    const strategy = getPositionStrategy(position);
    return `<span class="strategy-badge strategy-${strategy.key}" title="${strategy.label}">${strategy.label}</span>`;
}

function formatPositionOutcome(position) {
    const rawOutcome = position?.outcome || '—';
    if (rawOutcome === '—') return rawOutcome;

    const strategy = getPositionStrategy(position);
    if (strategy.key === 'cash-secured-put') {
        if (rawOutcome === 'Assigned') return 'Assigned (Bought at strike)';
        if (rawOutcome === 'Returned') return 'Returned (Kept premium)';
    }

    if (strategy.key === 'covered-call') {
        if (rawOutcome === 'Assigned') return 'Assigned (Sold at strike)';
        if (rawOutcome === 'Returned') return 'Returned (Kept asset)';
    }

    return rawOutcome;
}

function parseSortValue(raw, key) {
    const text = String(raw || '').trim();
    if (!text || text === '—' || text.toLowerCase() === 'unknown') {
        return null;
    }

    if (key === 'created' || key === 'expiry') {
        const numeric = Number(text);
        if (Number.isFinite(numeric)) return numeric;
        const ts = Date.parse(text);
        return Number.isNaN(ts) ? null : ts;
    }

    if (['quantity', 'strike', 'premium', 'apr', 'volume', 'notional', 'orders', 'distance'].includes(key)) {
        const normalized = text.replace(/[$,%\s,]/g, '');
        const num = Number(normalized);
        return Number.isFinite(num) ? num : null;
    }

    return text.toLowerCase();
}

function setupSortableTable(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const tbody = table.querySelector('tbody');
    if (!tbody) return;

    const headers = table.querySelectorAll('th[data-sort-key]');
    let currentSort = { key: null, direction: 'asc' };

    const compareValues = (a, b) => {
        if (a === null && b === null) return 0;
        if (a === null) return 1;
        if (b === null) return -1;
        if (typeof a === 'number' && typeof b === 'number') return a - b;
        return String(a).localeCompare(String(b));
    };

    headers.forEach(header => {
        header.classList.add('sortable-header');
        header.addEventListener('click', () => {
            const key = header.getAttribute('data-sort-key');
            if (!key) return;

            const direction = currentSort.key === key && currentSort.direction === 'asc' ? 'desc' : 'asc';
            currentSort = { key, direction };

            const rows = Array.from(tbody.querySelectorAll('tr'));
            rows.sort((rowA, rowB) => {
                const cellA = rowA.querySelector(`td[data-sort-key="${key}"]`);
                const cellB = rowB.querySelector(`td[data-sort-key="${key}"]`);
                const valA = parseSortValue(cellA?.getAttribute('data-sort-value') || cellA?.textContent || '', key);
                const valB = parseSortValue(cellB?.getAttribute('data-sort-value') || cellB?.textContent || '', key);
                const cmp = compareValues(valA, valB);
                return direction === 'asc' ? cmp : -cmp;
            });

            rows.forEach(row => tbody.appendChild(row));

            headers.forEach(h => {
                h.classList.remove('sorted-asc', 'sorted-desc');
            });
            header.classList.add(direction === 'asc' ? 'sorted-asc' : 'sorted-desc');
        });
    });
}
