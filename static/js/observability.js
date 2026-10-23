/* Optional Cloudflare Web Analytics. No wallet pages, custom events or IDs. */
(() => {
    'use strict';
    try {
        const configNode = document.getElementById('rysk-web-analytics');
        if (!configNode) return;
        const config = JSON.parse(configNode.textContent);
        const location = window.location;
        const allowedPaths = new Set(['/', '/analytics']);
        const sensitiveIdentifier = /0x[a-f\d]{40}|[a-f\d]{64}/i;
        const decoded = value => decodeURIComponent(value);
        const url = new URL(config.origin);
        if (url.protocol !== 'https:' || url.origin !== config.origin
            || location.origin !== config.origin || !allowedPaths.has(location.pathname)
            || location.search || !/^(?:#[a-z][a-z\d-]{0,48})?$/i.test(location.hash)
            || sensitiveIdentifier.test(decoded(location.href))
            || !/^[a-f\d]{32}$/i.test(config.token)) return;
        // An external site or a previous release may have supplied a full
        // referrer. Do not initialize if it might identify a wallet or trader.
        if (document.referrer) {
            const referrer = new URL(document.referrer);
            if (referrer.search || sensitiveIdentifier.test(decoded(referrer.href))
                || /\/(?:account|trader|docs)(?:\/|$)/i.test(referrer.pathname)) return;
        }
        if (navigator.doNotTrack === '1' || navigator.globalPrivacyControl === true) return;
        const source = 'https://static.cloudflareinsights.com/beacon.min.js';
        if (document.querySelector(`script#rysk-cloudflare-beacon,script[data-cf-beacon],script[src^="${source}"]`)) return;
        const script = document.createElement('script');
        script.id = 'rysk-cloudflare-beacon';
        script.type = 'module';
        script.defer = true;
        script.src = source;
        // This is a multi-page Flask app. Filters and tab/hash transitions are
        // not pageviews, and must not be inspected by automatic SPA tracking.
        script.setAttribute('data-cf-beacon', JSON.stringify({ token: config.token, spa: false }));
        document.head.appendChild(script);
    } catch (_) {
        // Invalid config, browser restrictions and analytics failures must
        // never affect the dashboard itself.
    }
})();
