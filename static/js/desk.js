// Shared workspace interactions. No analytics are synthesized by this layer.
(() => {
    const icons = {
        overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        wallet: '<path d="M4 6h15v14H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h13v2M19 10h3v6h-7v-6z"/><path d="M18 13h.01"/>',
        research: '<path d="M3 20V4m0 16h18M6 15l5-5 4 3 6-8"/><path d="M17 5h4v4"/>',
        code: '<path d="m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18"/>',
        search: '<circle cx="10" cy="10" r="6.5"/><path d="m15 15 6 6"/>',
    };
    function paintIcons(root = document) {
        root.querySelectorAll('[data-icon]').forEach(el => {
            el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[el.dataset.icon] || icons.overview}</svg>`;
        });
    }
    const definitions = {
        'Notional': 'Strike price × option quantity. Open notional includes recorded, unexpired positions without a settled outcome. It describes exposure at strike, not the current market value of collateral or protocol TVL.',
        'Premium': 'The amount paid for the option. Premium alone is not net profit: assignment, changes in collateral value, fees, and other costs can affect the outcome.',
        'APR': 'The premium yield expressed as a simple annualized rate. It is not a forecast or a compounded return. Research uses notional-and-duration weighting; tables labeled Avg APR may use a simple trade average.',
        'DTE / tenor': 'Days to expiry (DTE) is time remaining until settlement. Entry tenor is the duration from execution to expiry. Historical entry DTE describes the original trade, not its remaining life today.',
        'IV / realized volatility': 'Implied volatility (IV) is estimated from an option price. Realized volatility measures past price changes. Both are annualized; they describe different things and depend on the observation window.',
        'OTM / moneyness': 'Out of the money describes a call strike above the reference price or a put strike below it. Research uses the prior daily close as a historical reference. It is not an executable quote.',
        'Assigned / returned': 'Assigned calls sell the underlying at strike; assigned puts buy it at strike. Returned positions keep the premium and release collateral. Neither label alone measures total investment profit.',
        'CC / CSP': 'CC means covered call: sell a call against an underlying asset. CSP means cash-secured put: sell a put backed by cash collateral. Compare their exposure as well as their premium.',
    };
    const destinations = [
        ['Overview', '/', 'Protocol flow, market brief, and latest activity', 'overview'],
        ['Portfolio', '/account', 'Wallet positions, exposure, premium PnL, and history', 'wallet'],
        ['Research', '/analytics', 'Executed flow, pricing benchmarks, and volatility', 'research'],
        ['API reference', '/docs', 'Endpoints, CLI, and JSON previews', 'code'],
        ['Asset explorer', '/#act-explore', 'Inspect an underlying, its strikes, and expiries', 'overview'],
        ['Activity & expiries', '/#act-activity', 'Recent executions and upcoming settlement exposure', 'overview'],
        ['Premium surface', '/analytics#act-surface', 'Compare historical annualized yield by moneyness', 'research'],
        ['Volatility', '/analytics#act-volatility', 'Compare realized volatility and assignment outcomes', 'research'],
        ['Yield mix', '/analytics#act-yield', 'Call and put premium efficiency by asset', 'research'],
    ];
    function initCommand() {
        const dialog = document.createElement('dialog');
        dialog.className = 'command-dialog';
        dialog.setAttribute('aria-label', 'Quick find: pages and metric definitions');
        dialog.innerHTML = '<div class="command-head"><span data-icon="search"></span><input type="search" aria-label="Search pages and metrics" placeholder="Find a page, an insight, a metric…" autocomplete="off"><button class="command-close" type="button" aria-label="Close quick find">Esc</button></div><div class="command-results"></div><div class="command-foot">Pages &amp; metric guide <span style="float:right">Tab to explore · Enter to open</span></div>';
        document.body.appendChild(dialog);
        const input = dialog.querySelector('input');
        const results = dialog.querySelector('.command-results');
        let returnFocus;
        function render() {
            const query = input.value.trim().toLowerCase();
            results.replaceChildren();
            const matches = destinations.filter(row => row.slice(0, 3).join(' ').toLowerCase().includes(query));
            if (matches.length) {
                const label = document.createElement('div'); label.className = 'command-category'; label.textContent = 'Go to'; results.appendChild(label);
            }
            matches.forEach(([name, href, description, icon]) => {
                const link = document.createElement('a'); link.className = 'command-result'; link.href = href;
                link.innerHTML = `<span data-icon="${icon}"></span><div><strong>${name}</strong><small>${description}</small></div><span aria-hidden="true">↗</span>`;
                link.addEventListener('click', () => dialog.close());
                results.appendChild(link);
            });
            const terms = Object.entries(definitions).filter(([term, text]) => `${term} ${text}`.toLowerCase().includes(query));
            if (terms.length) {
                const label = document.createElement('div'); label.className = 'command-category'; label.textContent = 'Metric guide'; results.appendChild(label);
                terms.forEach(([name, text]) => {
                    const item = document.createElement('article'); item.className = 'metric-definition';
                    const heading = document.createElement('h3'); heading.textContent = name;
                    const p = document.createElement('p'); p.textContent = text;
                    item.append(heading, p); results.appendChild(item);
                });
            }
            if (!matches.length && !terms.length) {
                const p = document.createElement('p'); p.className = 'empty-state'; p.textContent = 'No matches. Try “premium”, “volatility”, or “portfolio”.'; results.appendChild(p);
            }
            paintIcons(results);
        }
        function open(query = '') {
            if (dialog.open) return;
            returnFocus = document.activeElement; input.value = query; render(); dialog.showModal(); input.focus();
        }
        document.querySelectorAll('.command-trigger').forEach(button => button.addEventListener('click', () => open()));
        document.querySelectorAll('[data-glossary]').forEach(button => button.addEventListener('click', () => open(button.dataset.glossary)));
        input.addEventListener('input', render);
        input.addEventListener('keydown', e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); results.querySelector('a')?.focus(); }
            if (e.key === 'Enter' && results.querySelector('a')) { e.preventDefault(); results.querySelector('a').click(); }
        });
        dialog.querySelector('.command-close').addEventListener('click', () => dialog.close());
        dialog.addEventListener('click', e => { if (e.target === dialog) { const r = dialog.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close(); } });
        dialog.addEventListener('close', () => returnFocus?.focus());
        document.addEventListener('keydown', e => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); dialog.open ? dialog.close() : open(); } });
        render(); paintIcons(dialog);
    }
    // Keep large data tables scrollable within their card, rather than the page.
    function enhanceContent() {
        document.querySelectorAll('.data-table').forEach(table => {
            if (table.closest('.table-scroll, .modal-table-wrapper')) return;
            const wrapper = document.createElement('div'); wrapper.className = 'table-scroll'; wrapper.tabIndex = 0;
            wrapper.setAttribute('role', 'region'); wrapper.setAttribute('aria-label', `${table.closest('section')?.querySelector('h2')?.textContent || 'Data'} table; scroll horizontally for more columns`);
            table.before(wrapper); wrapper.appendChild(table);
        });
        document.querySelectorAll('.tabs .tab-button').forEach(button => button.setAttribute('aria-pressed', String(button.classList.contains('active'))));
        document.querySelectorAll('th[data-sort-key]').forEach(header => {
            header.tabIndex = 0; header.setAttribute('aria-sort', header.classList.contains('sorted-asc') ? 'ascending' : header.classList.contains('sorted-desc') ? 'descending' : 'none');
            if (!header.dataset.keyboardReady) { header.dataset.keyboardReady = 'true'; header.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); header.click(); } }); }
        });
    }
    function initExport() {
        document.querySelectorAll('[data-export-table]').forEach(button => button.addEventListener('click', () => {
            const table = document.getElementById(button.dataset.exportTable);
            if (!table?.tBodies[0]?.rows.length) return;
            const rows = Array.from(table.rows).map(row => Array.from(row.cells).map(cell => {
                let text = cell.innerText.trim().replace(/\s+/g, ' ');
                if (/^[=+@-]/.test(text)) text = `'${text}`;
                return `"${text.replace(/"/g, '""')}"`;
            }).join(','));
            const url = URL.createObjectURL(new Blob(['\ufeff' + rows.join('\r\n')], {type: 'text/csv;charset=utf-8'}));
            const a = document.createElement('a'); a.href = url; a.download = `rysk-${table.id}-${new Date().toISOString().slice(0,10)}.csv`; a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        }));
    }
    // Contain keyboard focus in existing modal panels, including dynamically added ones.
    let modalFocus = null, previousFocus = null;
    function trackModal() {
        const candidates = Array.from(document.querySelectorAll('.account-entry-modal, .sidepanel.is-open, .modal-overlay'));
        const current = candidates.filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden').pop() || null;
        if (current === modalFocus) return;
        if (current) {
            if (!modalFocus) previousFocus = document.activeElement;
            current.setAttribute('role', 'dialog'); current.setAttribute('aria-modal', 'true');
            if (!current.contains(document.activeElement)) current.querySelector('button, input, textarea, select, a[href]')?.focus();
        } else if (modalFocus && previousFocus?.isConnected) previousFocus.focus();
        modalFocus = current;
    }
    document.addEventListener('keydown', e => {
        if (!modalFocus || document.querySelector('.command-dialog[open]') || e.key !== 'Tab') return;
        const items = Array.from(modalFocus.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),textarea,select,[tabindex="0"]')).filter(el => el.getClientRects().length);
        if (!items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && (document.activeElement === first || !modalFocus.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (document.activeElement === last || !modalFocus.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    });
    document.addEventListener('DOMContentLoaded', () => {
        paintIcons(); initCommand(); initExport(); enhanceContent(); trackModal();
        document.querySelectorAll('.carousel-arrow').forEach(button => button.setAttribute('aria-label', button.classList.contains('left') ? 'Scroll to earlier items' : 'Scroll to later items'));
        let scheduled = false;
        new MutationObserver(() => {
            if (scheduled) return; scheduled = true;
            requestAnimationFrame(() => { scheduled = false; enhanceContent(); trackModal(); });
        }).observe(document.querySelector('.app-shell'), {childList: true, subtree: true});
        // Style changes control the legacy wallet entry and sidepanels.
        document.querySelectorAll('.account-entry-modal,.modal-overlay,.sidepanel').forEach(el => new MutationObserver(trackModal).observe(el, {attributes:true,attributeFilter:['style','class']}));
        document.addEventListener('click', () => requestAnimationFrame(enhanceContent));
    });
})();
