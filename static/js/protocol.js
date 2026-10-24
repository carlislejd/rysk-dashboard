// Activity reads the same stored executions as Research; TVL uses DeFiLlama.
let protocolDays = 30;
let protocolRequest = 0;
let protocolTvlRequest = 0;

// TVL is a current DeFiLlama collateral snapshot, independent of trade turnover.
function renderProtocolTvl(data) {
    const tvl = data.tvl;
    if (!tvl || typeof tvl.usd !== 'number' || !Number.isFinite(tvl.usd) || tvl.usd < 0 ||
        typeof tvl.as_of !== 'number' || !Number.isFinite(tvl.as_of) || tvl.as_of <= 0) {
        throw new Error('Invalid TVL snapshot');
    }
    const sourceDate = new Date(tvl.as_of * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
    const stale = tvl.is_stale !== false;
    document.getElementById('protocol-tvl').textContent = compactCurrency(tvl.usd, 1);
    document.getElementById('protocol-tvl-as-of').textContent = `Source snapshot: ${sourceDate}`;
    const status = document.getElementById('protocol-tvl-status');
    status.className = stale ? 'is-stale' : '';
    status.textContent = stale ? 'Stale snapshot · check DeFiLlama for updates.' : 'Latest available DeFiLlama snapshot.';
    document.getElementById('protocol-tvl-retry').hidden = !stale;
}

async function loadProtocolTvl() {
    const version = ++protocolTvlRequest;
    const panel = document.getElementById('protocol-tvl-panel');
    if (!panel) return;
    panel.setAttribute('aria-busy', 'true');
    const chainId = chainValueToId(selectedChain);
    document.getElementById('protocol-tvl-scope').textContent = `Rysk V12 · ${chainId === null ? 'all networks' : chainLabel({ chain_id: chainId })} · USD`;
    document.getElementById('protocol-tvl').textContent = '—';
    document.getElementById('protocol-tvl-as-of').textContent = 'Source snapshot pending';
    const status = document.getElementById('protocol-tvl-status');
    status.className = '';
    status.textContent = 'Reading current TVL…';
    document.getElementById('protocol-tvl-retry').hidden = true;
    try {
        const response = await fetch(withChain('/api/global/tvl'));
        const data = await response.json();
        if (version !== protocolTvlRequest) return;
        if (!response.ok || !data.success) throw new Error('TVL unavailable');
        renderProtocolTvl(data);
    } catch (_) {
        if (version !== protocolTvlRequest) return;
        document.getElementById('protocol-tvl').textContent = '—';
        document.getElementById('protocol-tvl-as-of').textContent = 'Source snapshot unavailable';
        status.className = 'is-stale';
        status.textContent = 'TVL temporarily unavailable. Check DeFiLlama or retry.';
        document.getElementById('protocol-tvl-retry').hidden = false;
    } finally {
        if (version === protocolTvlRequest) panel.setAttribute('aria-busy', 'false');
    }
}

function protocolComparison(metric, days, stale) {
    if (stale) return 'Recorded activity · collection may be incomplete';
    if (metric.change_pct == null) return `No comparable prior ${days}d activity`;
    const change = Number(metric.change_pct);
    return `${change > 0 ? '+' : ''}${change.toFixed(1)}% vs previous ${days}d`;
}

function protocolPercent(value) {
    return value == null ? '—' : `${Number(value).toFixed(1)}%`;
}

function protocolBar(label, amount, percent, variant = '') {
    const width = Math.max(0, Math.min(100, Number(percent) || 0));
    return `<div class="usage-row"><div><span>${escapeAttr(label)}</span><strong>${escapeAttr(amount)}</strong></div><div class="usage-track" aria-hidden="true"><span class="${variant}" style="width:${width}%"></span></div><small>${protocolPercent(percent)} of notional</small></div>`;
}

function renderProtocolOverview(data) {
    const metrics = data.metrics;
    const observation = data.observation;
    const status = document.getElementById('protocol-status');
    const stale = observation.is_stale;
    const observedDate = observation.last_trade_at ? new Date(observation.last_trade_at * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : null;
    status.className = `protocol-status${stale ? ' is-stale' : ''}`;
    status.replaceChildren();
    const text = document.createElement('span');
    text.textContent = observedDate
        ? `${stale ? 'Collection needs attention. ' : ''}Latest recorded trade: ${observedDate}. ${stale ? 'Recent totals may be incomplete; zero recorded trades does not prove zero protocol activity.' : 'Rolling windows use UTC. The current day is partial.'}`
        : 'No recorded activity for this network. Try another network or return after the next collection.';
    status.appendChild(text);
    const retry = document.createElement('button');
    retry.type = 'button'; retry.className = 'text-action'; retry.textContent = 'Reload view';
    retry.addEventListener('click', () => loadGlobalDashboard());
    status.appendChild(retry);
    for (const [key, id] of [['notional', 'notional'], ['premium', 'premium'], ['trades', 'trades']]) {
        document.getElementById(`protocol-${id}`).textContent = key === 'trades' ? formatNumber(metrics[key].value, 0) : compactCurrency(metrics[key].value, 1);
        document.getElementById(`protocol-${id}-comparison`).textContent = protocolComparison(metrics[key], protocolDays, stale);
    }
    document.getElementById('protocol-yield').textContent = protocolPercent(metrics.premium_yield_pct.value);
    document.querySelectorAll('[data-protocol-window]').forEach(el => { el.textContent = `${protocolDays}d`; });
    const mix = data.strategy_mix;
    document.getElementById('protocol-strategies').innerHTML = metrics.notional.value > 0
        ? protocolBar('Covered calls', compactCurrency(mix.call_notional), mix.call_share_pct) + protocolBar('Cash-secured puts', compactCurrency(mix.put_notional), mix.put_share_pct, 'put')
        : '<p class="usage-empty">No executions recorded in this window. Try 90d to explore earlier activity.</p>';
    document.getElementById('protocol-assets').innerHTML = data.top_assets.length
        ? data.top_assets.slice(0, 3).map(asset => `<button class="usage-asset" type="button" data-usage-asset="${escapeAttr(asset.symbol)}" data-usage-chain="${Number(asset.chain_id)}"><span><strong>${escapeAttr(shortSymbol(asset.symbol))}</strong><small>${escapeAttr(chainLabel(asset))}</small></span><span><strong>${protocolPercent(asset.share_pct)}</strong><small>${compactCurrency(asset.notional)}</small></span></button>`).join('')
        : '<p class="usage-empty">Asset shares appear once this window contains recorded trades.</p>';
    document.getElementById('protocol-assets').querySelectorAll('[data-usage-asset]').forEach(button => button.addEventListener('click', () => showAssetDetail(button.dataset.usageAsset, { chainId: Number(button.dataset.usageChain) })));
    document.getElementById('protocol-chains').textContent = data.chain_mix.map(chain => `${chainLabel(chain)} ${protocolPercent(chain.share_pct)}`).join(' · ');
    const outcomes = data.outcomes;
    document.getElementById('protocol-outcomes').innerHTML = outcomes.expired_count
        ? `<div class="coverage-heading"><strong>${protocolPercent(outcomes.coverage_pct)}</strong><span>settlement coverage</span></div><div class="outcome-totals"><div><strong>${formatNumber(outcomes.returned_count, 0)}</strong><span>Returned</span></div><div><strong>${formatNumber(outcomes.assigned_count, 0)}</strong><span>Assigned</span></div><div><strong>${formatNumber(outcomes.pending_count, 0)}</strong><span>Unresolved</span></div></div><p class="metric-note">${formatNumber(outcomes.settled_count, 0)} of ${formatNumber(outcomes.expired_count, 0)} expired executions have a recorded outcome.</p>`
        : '<p class="usage-empty">No expired executions in this entry window. Settlement coverage appears after expiry.</p>';
}

async function loadProtocolOverview() {
    const version = ++protocolRequest;
    const cards = document.getElementById('protocol-kpis');
    if (!cards) return;
    cards.setAttribute('aria-busy', 'true');
    document.querySelectorAll('[data-protocol-window]').forEach(el => { el.textContent = `${protocolDays}d`; });
    const status = document.getElementById('protocol-status');
    status.textContent = 'Reading selected protocol activity…';
    ['notional', 'premium', 'trades', 'yield'].forEach(id => { document.getElementById(`protocol-${id}`).textContent = '—'; });
    ['notional', 'premium', 'trades'].forEach(id => { document.getElementById(`protocol-${id}-comparison`).textContent = 'Loading selected window…'; });
    ['strategies', 'assets', 'outcomes'].forEach(id => { document.getElementById(`protocol-${id}`).textContent = 'Reading selected window…'; });
    document.getElementById('protocol-chains').textContent = '';
    try {
        const response = await fetch(withChain(`/api/global/protocol-overview?days=${protocolDays}`));
        const data = await response.json();
        if (version !== protocolRequest) return;
        if (!response.ok || !data.success) throw new Error('Protocol overview unavailable');
        renderProtocolOverview(data);
    } catch (_) {
        if (version !== protocolRequest) return;
        status.className = 'protocol-status is-stale';
        status.innerHTML = '<span>Protocol activity is temporarily unavailable.</span><button type="button" class="text-action">Try again</button>';
        status.querySelector('button').addEventListener('click', loadProtocolOverview);
        ['notional', 'premium', 'trades'].forEach(id => { document.getElementById(`protocol-${id}-comparison`).textContent = 'Unavailable · retry above'; });
        ['strategies', 'assets', 'outcomes'].forEach(id => { document.getElementById(`protocol-${id}`).textContent = 'Activity unavailable. Retry above.'; });
    } finally {
        if (version === protocolRequest) cards.setAttribute('aria-busy', 'false');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('protocol-tvl-retry')?.addEventListener('click', loadProtocolTvl);
    document.getElementById('protocol-range-tabs')?.addEventListener('click', event => {
        const button = event.target.closest('[data-protocol-days]');
        if (!button) return;
        protocolDays = Number(button.dataset.protocolDays);
        document.querySelectorAll('[data-protocol-days]').forEach(item => {
            item.classList.toggle('active', item === button);
            item.setAttribute('aria-pressed', String(item === button));
        });
        loadProtocolOverview();
    });
});
