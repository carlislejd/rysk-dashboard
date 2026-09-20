// Anonymous historical trader record. The browser only receives opaque aliases.
const TRADER_PAGE_SIZE = 50;
const MAX_UNIX_TS = 253402300799;
const traderId = decodeURIComponent(
  window.location.pathname.split("/").pop() || "",
);
const traderParams = new URLSearchParams(window.location.search);
let traderDays = Number(traderParams.get("days") ?? 0),
  traderChain = traderParams.get("chain_id") || "all",
  traderPage = Number(traderParams.get("page") ?? 1);
let traderSymbol = traderParams.get("symbol") || "",
  traderFrom = traderParams.get("from_ts") || "",
  traderTo = traderParams.get("to_ts") || "",
  traderRequestId = 0,
  traderVisuals = null,
  traderMetric = "notional";
const escapeTraderHtml = (value) =>
  String(value ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "'": "&#039;",
        '"': "&quot;",
      })[c],
  );
const safeDate = (timestamp) => {
  if (timestamp === "" || timestamp === null || timestamp === undefined) return null;
  const numeric = Number(timestamp);
  if (!Number.isInteger(numeric) || numeric < 0 || numeric > MAX_UNIX_TS)
    return null;
  const date = new Date(numeric * 1000);
  return Number.isFinite(date.getTime()) ? date : null;
};
const traderDate = (timestamp, withTime = false) => {
  const date = safeDate(timestamp);
  return date
    ? date.toLocaleDateString(
        "en-US",
        withTime
          ? {
              month: "short",
              day: "numeric",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              timeZone: "UTC",
            }
          : { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" },
      )
    : "—";
};
const traderWindowLabel = () =>
  traderDays === 0
    ? "all recorded history"
    : traderDays === 365
      ? "trailing year"
      : `trailing ${traderDays} days`;
const dateToTs = (value) => {
  if (!value) return "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const ts = Math.floor(new Date(`${value}T00:00:00Z`).getTime() / 1000);
  return Number.isInteger(ts) && ts >= 0 && ts <= MAX_UNIX_TS ? ts : null;
};
const tsToDate = (value) => {
  const date = safeDate(value);
  try {
    return date ? date.toISOString().slice(0, 10) : "";
  } catch (_) {
    return "";
  }
};
const normaliseTimestamp = (value) => {
  if (!/^\d+$/.test(String(value || ""))) return "";
  const numeric = Number(value);
  return Number.isSafeInteger(numeric) && numeric <= MAX_UNIX_TS
    ? String(numeric)
    : "";
};
function traderApiUrl() {
  const p = new URLSearchParams({
    days: traderDays,
    page: traderPage,
    limit: TRADER_PAGE_SIZE,
  });
  if (traderChain !== "all") p.set("chain_id", traderChain);
  if (traderSymbol) p.set("symbol", traderSymbol);
  if (traderFrom) p.set("from_ts", traderFrom);
  if (traderTo) p.set("to_ts", traderTo);
  return `/api/analytics/traders/${encodeURIComponent(traderId)}?${p}`;
}
function syncTraderUrl() {
  const p = new URLSearchParams({ days: traderDays });
  if (traderChain !== "all") p.set("chain_id", traderChain);
  if (traderSymbol) p.set("symbol", traderSymbol);
  if (traderFrom) p.set("from_ts", traderFrom);
  if (traderTo) p.set("to_ts", traderTo);
  if (traderPage > 1) p.set("page", traderPage);
  window.history.replaceState(
    {},
    "",
    `/trader/${encodeURIComponent(traderId)}?${p}`,
  );
}
function setTraderFilters() {
  document
    .querySelectorAll("#trader-range-tabs [data-days]")
    .forEach((b) =>
      b.classList.toggle("active", Number(b.dataset.days) === traderDays),
    );
  document
    .querySelectorAll("#trader-chain-tabs [data-chain]")
    .forEach((b) =>
      b.classList.toggle("active", b.dataset.chain === traderChain),
    );
  document.getElementById("trader-symbol-filter").value = traderSymbol;
  document.getElementById("trader-from-filter").value = tsToDate(traderFrom);
  document.getElementById("trader-to-filter").value = tsToDate(traderTo);
  const active = Boolean(traderSymbol || traderFrom || traderTo);
  document.getElementById("trader-clear-filters").hidden = !active;
  document.getElementById("trader-selection-chips").innerHTML = active
    ? [
        traderSymbol &&
          `<button class="selection-chip" type="button" data-clear="symbol">${escapeTraderHtml(traderSymbol)} ×</button>`,
        traderFrom &&
          `<button class="selection-chip" type="button" data-clear="from">From ${traderDate(traderFrom)} ×</button>`,
        traderTo &&
          `<button class="selection-chip" type="button" data-clear="to">Before ${traderDate(traderTo)} ×</button>`,
      ]
        .filter(Boolean)
        .join("")
    : "";
}
function renderTraderTotals(data) {
  const t = data.totals || {};
  document.getElementById("trader-title").textContent =
    data.identity?.alias || "Trader history";
  document.getElementById("trader-notional").textContent = formatCurrency(
    t.notional,
    0,
  );
  document.getElementById("trader-premium").textContent = formatCurrency(
    t.premium,
  );
  document.getElementById("trader-apr").textContent = formatPercentage(
    t.weighted_apr,
    1,
  );
  document.getElementById("trader-trades").textContent = formatNumber(
    t.trade_count || 0,
    0,
  );
}
function renderTraderTrades(data) {
  const body = document.getElementById("trader-trades-body"),
    trades = data.trades || [];
  body.innerHTML = !trades.length
    ? '<tr><td colspan="11" class="trader-empty">No recorded executions match these filters.</td></tr>'
    : trades
        .map((t) => {
          const outcome =
            t.outcome === "Assigned"
              ? '<span class="trader-outcome trader-assigned">Assigned</span>'
              : t.outcome === "Returned"
                ? '<span class="trader-outcome trader-returned">Returned</span>'
                : t.outcome
                  ? escapeTraderHtml(t.outcome)
                  : "—";
          const chain =
            t.chain_name ||
            (Number(t.chain_id) === 1
              ? "Ethereum"
              : Number(t.chain_id) === 999
                ? "HyperEVM"
                : "Unknown");
          return `<tr><td>${traderDate(t.created_at, true)}</td><td><span class="chain-badge ${escapeTraderHtml(t.chain_slug || "")}">${escapeTraderHtml(chain)}</span></td><td>${escapeTraderHtml(t.symbol || "—")}</td><td>${escapeTraderHtml(t.type || "—")}</td><td>${formatStrike(t.strike)}</td><td>${formatNumber(t.quantity, 4)}</td><td>${formatCurrency(t.premium)}</td><td>${formatCurrency(t.notional, 0)}</td><td>${formatPercentage(t.apr, 1)}</td><td>${traderDate(t.expiry)}</td><td>${outcome}</td></tr>`;
        })
        .join("");
  const p = data.pagination || {},
    page = Number(p.page) || 1,
    pages = Math.max(1, Number(p.pages) || 1);
  document.getElementById("trader-pagination").innerHTML =
    `<button class="pager-btn" type="button" data-trader-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Prev</button><span class="pager-info">Page ${page} of ${pages}</span><button class="pager-btn" type="button" data-trader-page="${page + 1}" ${page >= pages ? "disabled" : ""}>Next</button>`;
}
function renderTraderVisuals(visuals) {
  traderVisuals = visuals || { timeline: [], assets: [] };
  const api = window.RyskCharts,
    timeline = traderVisuals.timeline || [],
    assets = traderVisuals.assets || [],
    select = document.getElementById("trader-symbol-filter");
  select.innerHTML = `<option value="">All assets</option>${assets.map((a) => `<option value="${escapeTraderHtml(a.symbol)}">${escapeTraderHtml(a.symbol)}</option>`).join("")}`;
  select.value = traderSymbol;
  if (!api) return;
  if (!timeline.length)
    api.empty("trader-timeline-chart", "No executions in this window.");
  else {
    const values = timeline.map((p) => p[traderMetric] || 0),
      selected = timeline.map(
        (p) => String(p.start) === traderFrom && String(p.end) === traderTo,
      );
    api.render(
      "trader-timeline-chart",
      [
        {
          type: "bar",
          x: timeline.map((p) => safeDate(p.start)?.toISOString() || null),
          y: values,
          customdata: timeline.map((p) => [p.start, p.end]),
          marker: {
            color: selected.map((active) =>
              active ? "$highlight" : "$forest",
            ),
          },
          hovertemplate: `%{x|%b %-d, %Y UTC}<br>${traderMetric === "premium" ? "Premium" : "Notional"}: $%{y:,.0f}<extra></extra>`,
        },
      ],
      {
        margin: { l: 54, r: 12, t: 8, b: 44 },
        height: 240,
        xaxis: { type: "date", tickformat: "%b %-d" },
        yaxis: {
          title: `${traderMetric === "premium" ? "Premium" : "Notional"} ($)`,
          tickprefix: "$",
        },
        showlegend: false,
      },
    );
    api.bindClick("trader-timeline-chart", (e) => {
      const range = e?.points?.[0]?.customdata,
        start = range?.[0],
        end = range?.[1];
      if (!start || !end) return;
      [traderFrom, traderTo] =
        traderFrom === String(start) && traderTo === String(end)
          ? ["", ""]
          : [String(start), String(end)];
      traderPage = 1;
      setTraderFilters();
      syncTraderUrl();
      loadTraderHistory();
    });
  }
  if (!assets.length)
    api.empty("trader-assets-chart", "No asset composition in this window.");
  else {
    const reverse = [...assets].reverse(),
      selected = reverse.map((a) => a.symbol === traderSymbol);
    api.render(
      "trader-assets-chart",
      [
        {
          type: "bar",
          orientation: "h",
          name: "Calls",
          y: reverse.map((a) => a.symbol),
          x: reverse.map((a) => a.calls_notional || 0),
          customdata: reverse.map((a) => a.symbol),
          marker: {
            color: selected.map((active) => (active ? "$highlight" : "$call")),
          },
          hovertemplate: "%{y}<br>Calls: $%{x:,.0f}<extra></extra>",
        },
        {
          type: "bar",
          orientation: "h",
          name: "Puts",
          y: reverse.map((a) => a.symbol),
          x: reverse.map((a) => a.puts_notional || 0),
          customdata: reverse.map((a) => a.symbol),
          marker: {
            color: selected.map((active) => (active ? "$highlight" : "$put")),
          },
          hovertemplate: "%{y}<br>Puts: $%{x:,.0f}<extra></extra>",
        },
      ],
      {
        barmode: "stack",
        margin: { l: 58, r: 12, t: 8, b: 36 },
        height: 240,
        xaxis: { title: "Notional ($)", tickprefix: "$" },
        yaxis: { automargin: true },
        legend: { orientation: "h" },
      },
    );
    api.bindClick("trader-assets-chart", (e) => {
      const symbol = e?.points?.[0]?.customdata;
      if (!symbol) return;
      traderSymbol = traderSymbol === symbol ? "" : symbol;
      traderPage = 1;
      setTraderFilters();
      syncTraderUrl();
      loadTraderHistory();
    });
  }
}
function clearTraderDisplay(message) {
  ["trader-notional", "trader-premium", "trader-apr", "trader-trades"].forEach(
    (id) => (document.getElementById(id).textContent = "—"),
  );
  document.getElementById("trader-trades-body").innerHTML =
    `<tr><td colspan="11" class="trader-empty">${escapeTraderHtml(message)}</td></tr>`;
  document.getElementById("trader-pagination").innerHTML = "";
  traderVisuals = null;
  window.RyskCharts?.empty("trader-timeline-chart", message);
  window.RyskCharts?.empty("trader-assets-chart", message);
}
async function loadTraderHistory() {
  const id = ++traderRequestId,
    status = document.getElementById("trader-status"),
    loading = document.getElementById("trader-trades-loading"),
    content = document.getElementById("trader-trades-content");
  status.textContent = "Loading recorded history…";
  loading.hidden = false;
  content.hidden = true;
  try {
    const response = await fetch(traderApiUrl()),
      data = await response.json();
    if (id !== traderRequestId) return;
    if (!response.ok || !data.success)
      throw new Error(data.error || "Request failed");
    renderTraderTotals(data);
    renderTraderTrades(data);
    renderTraderVisuals(data.visuals);
    status.textContent = `${traderWindowLabel()} · ${traderChain === "all" ? "all chains" : traderChain === "ethereum" ? "Ethereum" : "HyperEVM"}`;
    loading.hidden = true;
    content.hidden = false;
  } catch (error) {
    if (id !== traderRequestId) return;
    const message = "This anonymous historical record is unavailable.";
    status.textContent = `Trader history unavailable: ${error.message}`;
    clearTraderDisplay(message);
    loading.textContent = message;
    loading.hidden = false;
    content.hidden = true;
  }
}
function resetTraderLocalFilters() {
  traderSymbol = "";
  traderFrom = "";
  traderTo = "";
  traderPage = 1;
  setTraderFilters();
  syncTraderUrl();
  loadTraderHistory();
}
document.addEventListener("DOMContentLoaded", () => {
  if (![0, 30, 90, 365].includes(traderDays)) traderDays = 0;
  if (traderChain === "1") traderChain = "ethereum";
  if (traderChain === "999") traderChain = "hyperevm";
  if (!["all", "ethereum", "hyperevm"].includes(traderChain))
    traderChain = "all";
  if (!Number.isInteger(traderPage) || traderPage < 1) traderPage = 1;
  traderFrom = normaliseTimestamp(traderFrom);
  traderTo = normaliseTimestamp(traderTo);
  if (traderFrom && traderTo && Number(traderFrom) >= Number(traderTo)) {
    traderFrom = "";
    traderTo = "";
  }
  setTraderFilters();
  syncTraderUrl();
  loadTraderHistory();
  document
    .getElementById("trader-range-tabs")
    .addEventListener("click", (e) => {
      const b = e.target.closest("[data-days]");
      if (!b) return;
      traderDays = Number(b.dataset.days);
      resetTraderLocalFilters();
    });
  document
    .getElementById("trader-chain-tabs")
    .addEventListener("click", (e) => {
      const b = e.target.closest("[data-chain]");
      if (!b) return;
      traderChain = b.dataset.chain;
      resetTraderLocalFilters();
    });
  document
    .getElementById("trader-metric-tabs")
    .addEventListener("click", (e) => {
      const b = e.target.closest("[data-trader-metric]");
      if (!b) return;
      traderMetric = b.dataset.traderMetric;
      document
        .querySelectorAll("#trader-metric-tabs [data-trader-metric]")
        .forEach((item) => item.classList.toggle("active", item === b));
      renderTraderVisuals(traderVisuals);
    });
  document
    .getElementById("trader-symbol-filter")
    .addEventListener("change", (e) => {
      traderSymbol = e.target.value;
      traderPage = 1;
      setTraderFilters();
      syncTraderUrl();
      loadTraderHistory();
    });
  document.getElementById("trader-date-apply").addEventListener("click", () => {
    const fromInput = document.getElementById("trader-from-filter");
    const toInput = document.getElementById("trader-to-filter");
    const from = dateToTs(fromInput.value);
    const to = dateToTs(toInput.value);
    const invalid =
      (fromInput.value && from === null) ||
      (toInput.value && to === null) ||
      (from && to && from >= to);
    fromInput.setAttribute(
      "aria-invalid",
      String(Boolean(invalid && fromInput.value)),
    );
    toInput.setAttribute(
      "aria-invalid",
      String(Boolean(invalid && toInput.value)),
    );
    if (invalid) {
      document.getElementById("trader-status").textContent =
        "Use valid UTC dates with From before To.";
      return;
    }
    traderFrom = String(from || "");
    traderTo = String(to || "");
    traderPage = 1;
    setTraderFilters();
    syncTraderUrl();
    loadTraderHistory();
  });
  document
    .getElementById("trader-clear-filters")
    .addEventListener("click", resetTraderLocalFilters);
  document
    .getElementById("trader-selection-chips")
    .addEventListener("click", (e) => {
      const key = e.target.closest("[data-clear]")?.dataset.clear;
      if (!key) return;
      if (key === "symbol") traderSymbol = "";
      else if (key === "from") traderFrom = "";
      else traderTo = "";
      traderPage = 1;
      setTraderFilters();
      syncTraderUrl();
      loadTraderHistory();
    });
  document
    .getElementById("trader-pagination")
    .addEventListener("click", (e) => {
      const b = e.target.closest("[data-trader-page]");
      if (!b || b.disabled) return;
      traderPage = Number(b.dataset.traderPage);
      syncTraderUrl();
      loadTraderHistory();
    });
});
