// Rysk protocol research desk

let analyticsDays = 365;
let analyticsChain = 'all';
let analyticsOverview = null;
let surfaceData = null;
let surfaceOptionType = 'call';
let surfaceRequestId = 0;
let volatilityData = {};
let volatilityWindow = 30;

const ANALYTICS_COLORS = {
    HYPE: '#00ff9d',
    BTC: '#ff9f1c',
    ETH: '#8b9cff',
    SOL: '#c77dff',
    PUMP: '#ff4d8d',
    PURR: '#ffc53d',
    XRP: '#00d4ff',
    ZEC: '#d4ff66',
    OTHER: '#6b7387',
};

function analyticsColor(asset, index = 0) {
    const fallback = ['#00ff9d', '#00d4ff', '#ff9f1c', '#c77dff', '#ff4d6d', '#ffc53d', '#8b9cff'];
    return ANALYTICS_COLORS[asset] || fallback[index % fallback.length];
}

function chainUrl(path) {
    if (analyticsChain === 'all') return path;
    return `${path}${path.includes('?') ? '&' : '?'}chain_id=${encodeURIComponent(analyticsChain)}`;
}

function analyticsPlotLayout(overrides = {}) {
    const theme = getPlotlyTheme();
    return {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { family: 'JetBrains Mono, monospace', color: theme.fontColor, size: 11 },
        margin: { l: 58, r: 24, t: 24, b: 48 },
        hoverlabel: {
            bgcolor: theme.annotationBg,
            bordercolor: 'rgba(128, 255, 190, 0.25)',
            font: { family: 'JetBrains Mono, monospace', color: theme.fontColor, size: 12 },
        },
        xaxis: { showgrid: false, zeroline: false, fixedrange: true },
        yaxis: { gridcolor: theme.gridColor, zerolinecolor: theme.gridColor, fixedrange: true },
        legend: { orientation: 'h', y: -0.16, x: 0, font: { size: 10 } },
        ...overrides,
    };
}

const ANALYTICS_PLOT_CONFIG = { responsive: true, displayModeBar: false, scrollZoom: false };

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function escapeAnalyticsHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function windowLabel() {
    if (analyticsDays === 0) return 'all available history';
    if (analyticsDays === 365) return 'trailing year';
    return `trailing ${analyticsDays} days`;
}

function renderAnalyticsKpis(data) {
    const totals = data.totals || {};
    setText('analytics-notional', compactCurrency(totals.notional));
    setText('analytics-notional-sub', `${formatNumber(totals.trade_count || 0, 0)} executions · ${windowLabel()}`);
    setText('analytics-premium', compactCurrency(totals.premium));
    setText('analytics-premium-sub', `${formatNumber(totals.returned || 0, 0)} returned positions`);
    setText('analytics-yield', formatPercentage(totals.premium_yield_pct, 2));
    setText('analytics-apr', formatPercentage(totals.weighted_apr, 1));
    setText('analytics-apr-sub', `median ${formatPercentage(totals.median_apr, 1)}`);
    setText('analytics-returned', formatPercentage(totals.return_rate_pct, 1));
    setText('analytics-returned-sub', `${formatNumber(totals.settled || 0, 0)} settled positions`);
}

function renderNotionalStream(data) {
    const loading = document.getElementById('notional-stream-loading');
    const points = data.notional_series || [];
    const assets = data.stream_assets || [];
    if (loading) loading.style.display = 'none';

    if (!points.length) {
        setText('notional-stream-loading', 'No executed flow in this window.');
        if (loading) loading.style.display = 'block';
        Plotly.purge('notional-stream-chart');
        return;
    }

    const dates = points.map(point => point.date);
    const traces = assets.map((asset, index) => ({
        x: dates,
        y: points.map(point => point.assets?.[asset] || 0),
        type: 'scatter',
        mode: 'lines',
        name: asset,
        stackgroup: 'notional',
        groupnorm: '',
        line: { color: analyticsColor(asset, index), width: 1.6 },
        fillcolor: `${analyticsColor(asset, index)}55`,
        hovertemplate: `<b>${asset}</b><br>%{x}<br>Notional %{y:$,.0f}<extra></extra>`,
    }));
    traces.push({
        x: dates,
        y: points.map(point => point.premium || 0),
        type: 'scatter',
        mode: 'lines',
        name: 'Premium',
        line: { color: '#ffffff', width: 1.5, dash: 'dot' },
        yaxis: 'y2',
        hovertemplate: '<b>Premium</b><br>%{x}<br>%{y:$,.0f}<extra></extra>',
    });

    Plotly.newPlot('notional-stream-chart', traces, analyticsPlotLayout({
        margin: { l: 64, r: 64, t: 20, b: 56 },
        xaxis: { showgrid: false, fixedrange: true },
        yaxis: { title: 'Executed notional', tickprefix: '$', gridcolor: getPlotlyTheme().gridColor, fixedrange: true },
        yaxis2: { title: 'Premium', tickprefix: '$', overlaying: 'y', side: 'right', showgrid: false, fixedrange: true },
        hovermode: 'x unified',
    }), ANALYTICS_PLOT_CONFIG);

    const leader = (data.by_asset || [])[0];
    setText('stream-leader', leader ? `${leader.asset} leads · ${compactCurrency(leader.notional)}` : '—');
}

function bubbleSizes(rows, min = 16, max = 54) {
    const values = rows.map(row => Math.sqrt(Math.max(Number(row.notional) || 0, 0)));
    const peak = Math.max(...values, 1);
    return values.map(value => min + (value / peak) * (max - min));
}

function renderEfficiency(data) {
    const rows = (data.by_asset || []).filter(row => row.weighted_apr != null && row.premium_yield_pct != null);
    Plotly.newPlot('efficiency-chart', [{
        x: rows.map(row => row.weighted_apr),
        y: rows.map(row => row.premium_yield_pct),
        text: rows.map(row => row.asset),
        customdata: rows.map(row => [row.notional, row.trade_count]),
        mode: 'markers+text',
        type: 'scatter',
        textposition: 'top center',
        textfont: { size: 10 },
        marker: {
            size: bubbleSizes(rows),
            color: rows.map((row, index) => analyticsColor(row.asset, index)),
            opacity: 0.76,
            line: { color: 'rgba(255,255,255,0.38)', width: 1 },
        },
        hovertemplate: '<b>%{text}</b><br>Weighted APR %{x:.1f}%<br>Premium yield %{y:.2f}%<br>Notional %{customdata[0]:$,.0f}<br>%{customdata[1]} trades<extra></extra>',
    }], analyticsPlotLayout({
        margin: { l: 58, r: 24, t: 26, b: 54 },
        xaxis: { title: 'Notional-weighted APR', ticksuffix: '%', showgrid: false, fixedrange: true },
        yaxis: { title: 'Premium / notional', ticksuffix: '%', gridcolor: getPlotlyTheme().gridColor, fixedrange: true },
        showlegend: false,
    }), ANALYTICS_PLOT_CONFIG);
}

function renderTenorSurface(data) {
    const allAssets = (data.by_asset || []).slice(0, 7).map(row => row.asset);
    const tenors = data.tenor_buckets || [];
    const lookup = new Map((data.tenor_surface || []).map(row => [`${row.asset}|${row.tenor}`, row]));
    const z = allAssets.map(asset => tenors.map(tenor => lookup.get(`${asset}|${tenor}`)?.weighted_apr ?? null));
    const text = allAssets.map(asset => tenors.map(tenor => {
        const item = lookup.get(`${asset}|${tenor}`);
        return item ? `${formatPercentage(item.weighted_apr, 1)}<br>${formatNumber(item.trade_count, 0)} trades` : 'No trades';
    }));

    Plotly.newPlot('tenor-chart', [{
        x: tenors,
        y: allAssets,
        z,
        text,
        type: 'heatmap',
        colorscale: [
            [0, '#0d3b32'],
            [0.35, '#007f63'],
            [0.7, '#00d88a'],
            [1, '#d4ff66'],
        ],
        hovertemplate: '<b>%{y} · %{x}</b><br>%{text}<extra></extra>',
        colorbar: { title: 'APR %', thickness: 10, len: 0.78, outlinewidth: 0 },
        hoverongaps: false,
    }], analyticsPlotLayout({
        margin: { l: 60, r: 72, t: 22, b: 48 },
        xaxis: { showgrid: false, side: 'bottom', fixedrange: true },
        yaxis: { showgrid: false, autorange: 'reversed', fixedrange: true },
        showlegend: false,
    }), ANALYTICS_PLOT_CONFIG);
}

function renderOutcomeFrontier(data) {
    const rows = (data.by_asset || []).filter(row => row.assignment_rate_pct != null && row.premium_yield_pct != null);
    Plotly.newPlot('outcome-frontier-chart', [{
        x: rows.map(row => row.assignment_rate_pct),
        y: rows.map(row => row.premium_yield_pct),
        text: rows.map(row => row.asset),
        customdata: rows.map(row => [row.return_rate_pct, row.notional, row.settled, row.weighted_apr]),
        mode: 'markers+text',
        type: 'scatter',
        textposition: 'top center',
        marker: {
            size: bubbleSizes(rows, 18, 62),
            color: rows.map((row, index) => analyticsColor(row.asset, index)),
            opacity: 0.78,
            line: { color: 'rgba(255,255,255,0.4)', width: 1 },
        },
        hovertemplate: '<b>%{text}</b><br>Assignment %{x:.1f}%<br>Premium yield %{y:.2f}%<br>Returned %{customdata[0]:.1f}%<br>Notional %{customdata[1]:$,.0f}<br>%{customdata[2]} settled<extra></extra>',
    }], analyticsPlotLayout({
        margin: { l: 62, r: 28, t: 24, b: 56 },
        xaxis: { title: 'Assignment rate', ticksuffix: '%', showgrid: false, rangemode: 'tozero', fixedrange: true },
        yaxis: { title: 'Premium / notional', ticksuffix: '%', gridcolor: getPlotlyTheme().gridColor, rangemode: 'tozero', fixedrange: true },
        showlegend: false,
        shapes: [{
            type: 'rect', xref: 'paper', yref: 'paper', x0: 0, x1: 0.4, y0: 0.6, y1: 1,
            fillcolor: 'rgba(0,255,157,0.035)', line: { width: 0 }, layer: 'below',
        }],
        annotations: [{
            xref: 'paper', yref: 'paper', x: 0.02, y: 0.98, text: 'EFFICIENCY ZONE', showarrow: false,
            font: { size: 9, color: '#00ff9d' }, xanchor: 'left', yanchor: 'top',
        }],
    }), ANALYTICS_PLOT_CONFIG);
}

function renderScorecard(data) {
    const rows = (data.by_asset || []).slice(0, 8);
    const maxNotional = Math.max(...rows.map(row => row.notional || 0), 1);
    const element = document.getElementById('asset-scorecard');
    element.innerHTML = rows.map((row, index) => `
        <div class="scorecard-row">
            <div class="scorecard-rank">${String(index + 1).padStart(2, '0')}</div>
            <div class="scorecard-asset">
                <strong><span style="background:${analyticsColor(row.asset, index)}"></span>${escapeAnalyticsHtml(row.asset)}</strong>
                <div class="scorecard-bar"><i style="width:${Math.max(4, row.notional / maxNotional * 100)}%;background:${analyticsColor(row.asset, index)}"></i></div>
            </div>
            <div class="scorecard-values">
                <strong>${compactCurrency(row.notional)}</strong>
                <span>${formatPercentage(row.weighted_apr, 1)} APR · ${formatPercentage(row.return_rate_pct, 0)} returned</span>
            </div>
        </div>
    `).join('') || '<div class="analytics-empty">No asset observations in this window.</div>';
}

function populateSurfaceAssets(data) {
    const select = document.getElementById('surface-asset');
    const current = select.value || 'HYPE';
    const assets = (data.assets || []).filter(asset => asset !== 'UNKNOWN');
    select.innerHTML = assets.map(asset => `<option value="${escapeAnalyticsHtml(asset)}">${escapeAnalyticsHtml(asset)}</option>`).join('');
    select.value = assets.includes(current) ? current : (assets.includes('HYPE') ? 'HYPE' : assets[0]);
}

async function loadAnalyticsOverview() {
    const status = document.getElementById('analytics-data-status');
    status.textContent = 'Loading research set…';
    const response = await fetch(chainUrl(`/api/analytics/overview?days=${analyticsDays}`));
    const data = await response.json();
    if (!data.success) throw new Error(data.error || 'Analytics overview failed');
    analyticsOverview = data;
    renderAnalyticsKpis(data);
    renderNotionalStream(data);
    renderEfficiency(data);
    renderTenorSurface(data);
    renderOutcomeFrontier(data);
    renderScorecard(data);
    populateSurfaceAssets(data);
    status.textContent = `${formatNumber(data.totals?.trade_count || 0, 0)} executions · ${windowLabel()}`;
    return data;
}

function getDteParams() {
    const value = document.getElementById('surface-dte').value;
    if (!value || value === 'all') return '';
    const [minimum, maximum] = value.split(',');
    let params = '';
    if (minimum !== '') params += `&dte_min=${encodeURIComponent(minimum)}`;
    if (maximum !== '') params += `&dte_max=${encodeURIComponent(maximum)}`;
    return params;
}

function renderSurfaceChart(data) {
    const buckets = data.buckets || [];
    const samples = data.samples || [];
    const loading = document.getElementById('surface-loading');
    loading.style.display = 'none';

    if (!buckets.length) {
        loading.textContent = 'No trades have both an APR and prior-close reference for these filters.';
        loading.style.display = 'block';
        Plotly.purge('otm-apr-chart');
        return;
    }

    const callColor = surfaceOptionType === 'call' ? '#00d4ff' : '#ff4d8d';
    const sortedApr = samples.map(sample => Number(sample.apr) || 0).sort((a, b) => a - b);
    const p95Apr = sortedApr.length ? sortedApr[Math.floor((sortedApr.length - 1) * 0.95)] : 100;
    const cohortPeak = Math.max(...buckets.flatMap(bucket => [bucket.weighted_apr || 0, bucket.median_apr || 0]), 75);
    const focusedAprMax = Math.min(250, Math.max(100, p95Apr * 1.08, cohortPeak * 1.25));
    const traces = [{
        x: samples.map(sample => sample.otm_pct),
        y: samples.map(sample => sample.apr),
        text: samples.map(sample => sample.symbol),
        customdata: samples.map(sample => [sample.strike, sample.spot_reference, sample.dte, sample.notional, sample.outcome || 'Open']),
        type: 'scattergl',
        mode: 'markers',
        name: 'Executions',
        marker: { size: 6, color: callColor, opacity: 0.18 },
        hovertemplate: '<b>%{text}</b><br>%{x:.2f}% OTM<br>APR %{y:.1f}%<br>Strike %{customdata[0]:$,.2f}<br>Prior close %{customdata[1]:$,.2f}<br>%{customdata[2]:.1f} DTE<br>Notional %{customdata[3]:$,.0f}<br>%{customdata[4]}<extra></extra>',
    }, {
        x: buckets.map(bucket => bucket.midpoint),
        y: buckets.map(bucket => bucket.weighted_apr),
        text: buckets.map(bucket => bucket.label),
        customdata: buckets.map(bucket => [bucket.trade_count, bucket.median_apr, bucket.premium_yield_pct, bucket.return_rate_pct]),
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Weighted APR',
        line: { color: '#00ff9d', width: 3, shape: 'spline' },
        marker: { size: 10, color: '#00ff9d', line: { color: '#06110d', width: 2 } },
        hovertemplate: '<b>%{text}</b><br>Weighted APR %{y:.1f}%<br>Median APR %{customdata[1]:.1f}%<br>Premium yield %{customdata[2]:.2f}%<br>Returned %{customdata[3]:.1f}%<br>%{customdata[0]} trades<extra></extra>',
    }, {
        x: buckets.map(bucket => bucket.midpoint),
        y: buckets.map(bucket => bucket.median_apr),
        type: 'scatter',
        mode: 'lines',
        name: 'Median APR',
        line: { color: '#ffc53d', width: 1.7, dash: 'dot', shape: 'spline' },
        hovertemplate: 'Median APR %{y:.1f}%<extra></extra>',
    }];

    Plotly.newPlot('otm-apr-chart', traces, analyticsPlotLayout({
        margin: { l: 62, r: 30, t: 30, b: 58 },
        xaxis: { title: 'Strike distance at entry (OTM)', ticksuffix: '%', zeroline: true, zerolinecolor: 'rgba(255,255,255,0.2)', showgrid: false, range: [-12, 32], fixedrange: true },
        yaxis: { title: 'Executed APR', ticksuffix: '%', gridcolor: getPlotlyTheme().gridColor, range: [0, focusedAprMax], fixedrange: true },
        legend: { orientation: 'h', y: -0.18, x: 0 },
        hovermode: 'closest',
        shapes: [{ type: 'line', x0: 5, x1: 5, y0: 0, y1: 1, yref: 'paper', line: { color: '#ffffff', width: 1, dash: 'dash' } }],
    }), ANALYTICS_PLOT_CONFIG);
}

function targetOtm() {
    const spot = Number(document.getElementById('surface-spot').value);
    const strike = Number(document.getElementById('surface-strike').value);
    if (!(spot > 0) || !(strike > 0)) return null;
    return (surfaceOptionType === 'put' ? (1 - strike / spot) : (strike / spot - 1)) * 100;
}

function findSurfaceBucket(otm) {
    if (!surfaceData || otm == null) return null;
    return (surfaceData.buckets || []).find(bucket => otm >= bucket.lower && otm < bucket.upper) || null;
}

function updateSurfaceTarget() {
    const spot = Number(document.getElementById('surface-spot').value);
    const strike = Number(document.getElementById('surface-strike').value);
    const otm = targetOtm();
    const bucket = findSurfaceBucket(otm);

    if (otm == null) {
        setText('surface-formula', 'Enter a spot and strike to map your target.');
        setText('result-otm', '—');
        return;
    }

    const direction = surfaceOptionType === 'call' ? 'strike / spot − 1' : '1 − strike / spot';
    setText('surface-formula', `${direction} = ${formatPercentage(otm, 2)} OTM`);
    setText('result-otm', `${otm >= 0 ? '+' : ''}${formatPercentage(otm, 2)} OTM`);
    setText('result-bucket', bucket ? `${bucket.label} historical cohort` : 'No observed cohort at this distance');
    setText('result-apr', bucket ? formatPercentage(bucket.weighted_apr, 1) : '—');
    setText('result-median', bucket ? formatPercentage(bucket.median_apr, 1) : '—');
    setText('result-yield', bucket ? formatPercentage(bucket.premium_yield_pct, 2) : '—');
    setText('result-returned', bucket ? formatPercentage(bucket.return_rate_pct, 1) : '—');
    setText('result-confidence', bucket ? `${formatNumber(bucket.trade_count, 0)} observed executions · ${compactCurrency(bucket.notional)}` : 'No directly comparable executions');

    const result = document.getElementById('surface-result');
    result.classList.toggle('has-result', Boolean(bucket));
    if (document.getElementById('otm-apr-chart')?.data) {
        Plotly.relayout('otm-apr-chart', {
            'shapes[0].x0': otm,
            'shapes[0].x1': otm,
            'shapes[0].line.color': bucket ? '#ffffff' : '#ff4d6d',
        });
    }

    // Keep the entered values stable and explicit in the accessible formula.
    document.getElementById('surface-formula').title = `Spot ${spot}; strike ${strike}`;
}

async function loadSurface({ resetInputs = false } = {}) {
    const requestId = ++surfaceRequestId;
    const asset = document.getElementById('surface-asset').value || 'HYPE';
    const loading = document.getElementById('surface-loading');
    loading.textContent = 'Reconstructing historical moneyness…';
    loading.style.display = 'block';
    const url = chainUrl(`/api/analytics/otm-apr?asset=${encodeURIComponent(asset)}&days=${analyticsDays}&option_type=${surfaceOptionType}${getDteParams()}`);

    try {
        const response = await fetch(url);
        const data = await response.json();
        if (!data.success) throw new Error(data.error || 'Premium surface failed');
        if (requestId !== surfaceRequestId) return;
        surfaceData = data;
        renderSurfaceChart(data);
        setText('surface-coverage', `${formatNumber(data.observed_trades || 0, 0)} trades · ${formatPercentage(data.price_coverage_pct, 0)} price coverage`);

        const spotInput = document.getElementById('surface-spot');
        const strikeInput = document.getElementById('surface-strike');
        if (resetInputs || !Number(spotInput.value)) {
            const reference = Number(data.current_reference_price);
            if (reference > 0) {
                spotInput.value = reference.toFixed(reference >= 1000 ? 0 : 2);
                const target = reference * (surfaceOptionType === 'call' ? 1.05 : 0.95);
                strikeInput.value = target.toFixed(target >= 1000 ? 0 : 2);
            }
        }
        updateSurfaceTarget();
    } catch (error) {
        if (requestId !== surfaceRequestId) return;
        loading.textContent = `Historical surface unavailable: ${error.message}`;
        surfaceData = null;
        setText('surface-coverage', 'Price reference unavailable');
    }
}

function renderVolatility() {
    const assets = ['HYPE', 'BTC', 'ETH'];
    const key = `rv_${volatilityWindow}d`;
    const traces = assets.filter(asset => volatilityData[asset]).map((asset, index) => {
        const series = volatilityData[asset].series || [];
        return {
            x: series.map(point => point.date),
            y: series.map(point => point[key]),
            type: 'scatter',
            mode: 'lines',
            name: asset,
            line: { color: analyticsColor(asset, index), width: asset === 'HYPE' ? 2.8 : 2 },
            hovertemplate: `<b>${asset}</b><br>%{x}<br>${volatilityWindow}d RV %{y:.1f}%<extra></extra>`,
        };
    });
    Plotly.newPlot('volatility-chart', traces, analyticsPlotLayout({
        margin: { l: 62, r: 28, t: 26, b: 56 },
        xaxis: { showgrid: false, fixedrange: true },
        yaxis: { title: `${volatilityWindow}d annualized realized vol`, ticksuffix: '%', gridcolor: getPlotlyTheme().gridColor, rangemode: 'tozero', fixedrange: true },
        hovermode: 'x unified',
    }), ANALYTICS_PLOT_CONFIG);

    document.getElementById('volatility-snapshot').innerHTML = assets.map((asset, index) => {
        const latest = volatilityData[asset]?.latest || {};
        return `<div class="vol-snapshot-card" style="--asset-color:${analyticsColor(asset, index)}">
            <span>${asset}</span>
            <strong>${latest[key] != null ? formatPercentage(latest[key], 1) : '—'}</strong>
            <small>${latest.return_1d_pct != null ? `${latest.return_1d_pct >= 0 ? '+' : ''}${formatPercentage(latest.return_1d_pct, 2)} 1d` : 'No current reading'}</small>
        </div>`;
    }).join('');
}

async function loadVolatility() {
    const loading = document.getElementById('volatility-loading');
    loading.style.display = 'block';
    const results = await Promise.allSettled(['HYPE', 'BTC', 'ETH'].map(async asset => {
        const days = analyticsDays > 0 ? analyticsDays : 730;
        const response = await fetch(`/api/global/volatility?asset=${asset}&days=${days}`);
        const data = await response.json();
        if (!data.success) throw new Error(data.error || `${asset} volatility failed`);
        return [asset, data];
    }));
    results.forEach(result => {
        if (result.status === 'fulfilled') volatilityData[result.value[0]] = result.value[1];
    });
    loading.style.display = 'none';
    renderVolatility();
}

function initAnalyticsScrollSpy() {
    const links = Array.from(document.querySelectorAll('#analytics-act-nav a[data-act]'));
    const targets = links.map(link => document.getElementById(link.dataset.act)).filter(Boolean);
    if (!targets.length) return;
    const observer = new IntersectionObserver(entries => {
        const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (!visible.length) return;
        links.forEach(link => link.classList.toggle('active', link.dataset.act === visible[0].target.id));
    }, { rootMargin: '-90px 0px -65% 0px', threshold: 0 });
    targets.forEach(target => observer.observe(target));
}

function setAnalyticsError(error) {
    const status = document.getElementById('analytics-data-status');
    status.textContent = `Data unavailable · ${error.message}`;
    status.classList.add('error-text');
}

async function refreshAnalytics({ refreshVolatility = false, resetSurface = false } = {}) {
    try {
        await loadAnalyticsOverview();
        await Promise.allSettled([
            loadSurface({ resetInputs: resetSurface }),
            refreshVolatility ? loadVolatility() : Promise.resolve(),
        ]);
    } catch (error) {
        setAnalyticsError(error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    refreshAnalytics({ refreshVolatility: true, resetSurface: true });
    initAnalyticsScrollSpy();

    document.getElementById('analytics-range-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-days]');
        if (!button) return;
        analyticsDays = Number(button.dataset.days);
        document.querySelectorAll('#analytics-range-tabs .tab-button').forEach(item => item.classList.toggle('active', item === button));
        refreshAnalytics({ refreshVolatility: true });
    });

    document.getElementById('analytics-chain-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-chain]');
        if (!button) return;
        analyticsChain = button.dataset.chain || 'all';
        document.querySelectorAll('#analytics-chain-tabs .tab-button').forEach(item => item.classList.toggle('active', item === button));
        refreshAnalytics({ resetSurface: true });
    });

    document.getElementById('surface-type-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-option-type]');
        if (!button) return;
        surfaceOptionType = button.dataset.optionType;
        document.querySelectorAll('#surface-type-tabs .tab-button').forEach(item => item.classList.toggle('active', item === button));
        loadSurface({ resetInputs: true });
    });
    document.getElementById('surface-asset').addEventListener('change', () => loadSurface({ resetInputs: true }));
    document.getElementById('surface-dte').addEventListener('change', () => loadSurface());
    document.getElementById('surface-spot').addEventListener('input', updateSurfaceTarget);
    document.getElementById('surface-strike').addEventListener('input', updateSurfaceTarget);

    document.getElementById('vol-window-tabs').addEventListener('click', event => {
        const button = event.target.closest('[data-vol-window]');
        if (!button) return;
        volatilityWindow = Number(button.dataset.volWindow);
        document.querySelectorAll('#vol-window-tabs .tab-button').forEach(item => item.classList.toggle('active', item === button));
        renderVolatility();
    });
});
