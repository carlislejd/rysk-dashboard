// Shared utility functions for Rysk dashboards

// ── Theme Toggle (Day/Night) ──

function initTheme() {
    const saved = localStorage.getItem('rysk-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
    updateToggleIcons(saved);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('rysk-theme', next);
    updateToggleIcons(next);
    // Re-render any visible Plotly charts with new theme colors
    replotAllCharts();
}

function updateToggleIcons(theme) {
    // ☾ for dark (click to go light), ☀ for light (click to go dark)
    const icon = theme === 'dark' ? '\u263E' : '\u2600';
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.innerHTML = icon;
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
        fontColor: isLight ? '#78716c' : '#71717a',
        gridColor: isLight ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.06)',
        annotationBg: isLight ? 'rgba(250,248,244,0.92)' : 'rgba(9,9,11,0.85)',
        annotationColor: isLight ? '#57534E' : '#71717a',
        zoneCallBg: isLight ? 'rgba(2,132,199,0.06)' : 'rgba(56,189,248,0.04)',
        zonePutBg: isLight ? 'rgba(220,38,38,0.06)' : 'rgba(239,112,112,0.04)',
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

function compactCurrency(num) {
    if (num === null || num === undefined) return '$0';
    const abs = Math.abs(num);
    if (abs >= 1e6) return `$${(num / 1e6).toFixed(1)}M`;
    if (abs >= 1e3) return `$${(num / 1e3).toFixed(0)}K`;
    return formatCurrency(num, 0);
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
        const ts = Date.parse(text);
        return Number.isNaN(ts) ? null : ts;
    }

    if (['quantity', 'strike', 'premium', 'apr', 'volume', 'notional'].includes(key)) {
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
