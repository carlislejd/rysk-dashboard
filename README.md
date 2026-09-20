# Rysk Options Dashboard

Web dashboard and agent-friendly CLI for managing Rysk option positions.

## Features

- **Open Positions**: Track current positions with strategy tagging (CC/CSP)
- **Historical Performance**: View expired outcomes and deep-dive analytics
- **Protocol Analytics**: Explore notional streams, yield-normalized historical OTM cohorts, volatility regimes, and call/put premium efficiency
- **CLI**: Query account, open positions, strike distributions, and history in table or JSON mode

## Workspace experience

- **Overview** brings recorded flow, a market brief, upcoming expiries, and latest trades together. The latest observed trade date is shown explicitly; the page does not imply historical data is live.
- **Portfolio** accepts up to ten public wallet addresses, preserving combined and per-wallet analysis without a wallet signature.
- **Research** retains the historical premium surface, strategy mix, volatility, and yield analytics.
- Use **Quick find** or **⌘K / Ctrl+K** to jump between workflows and search plain-language metric definitions.
- Search the asset explorer by symbol or chain, open an asset's Strike Lens, or export the latest trade table as CSV.
- Light and dark themes share responsive layouts. Wide tables scroll within their sections; asset cards and sortable columns support keyboard activation.

Shared navigation lives in `templates/partials/`. The workspace design is in `static/css/desk.css`, layered over the existing component styles, and shared interactions are in `static/js/desk.js`.

## Setup

1. Install Poetry (if needed):
```bash
pip3 install poetry
```

2. Install project dependencies:
```bash
poetry install
```

3. (Optional) Configure environment variables:
```bash
# Optional default wallet (UI/CLI can also take addresses at runtime)
export ACCOUNT_ADDRESS="0xYourAddress"

# Optional RPC override (default is Hyperliquid EVM RPC)
export RPC_URL="https://rpc.hyperliquid.xyz/evm"

# Optional Ethereum mainnet settlement lookup overrides
# (defaults shown below)
export ETHEREUM_RPC_URL="https://eth-mainnet.g.alchemy.com/public"
export RYSK_ETHEREUM_EXPIRY_ORACLE="0xc11a4767d83fb2ab643cfc30288a7ee9690009a7"

# Optional Rysk API override (defaults to v12)
export RYSK_API_BASE="https://v12.rysk.finance/api"
```

You do **not** need a `.env` file. The app reads normal environment variables via `os.getenv`, so shell exports are enough.

4. Run the Flask web server:
```bash
poetry run python app.py
```

5. Open the dashboard and enter a wallet address when prompted:
```
http://localhost:5001
```

The protocol research desk is available at `http://localhost:5001/analytics`.

## CLI Usage

Run commands via:

```bash
poetry run rysk --help
```

Core commands:

```bash
# Validate wallet format
poetry run rysk account validate --address 0x...

# Open positions (agent-friendly JSON)
poetry run rysk positions open --address 0x... --json

# Strike distribution with dominant strategy and spot
poetry run rysk positions strikes --address 0x... --symbol UBTC --json

# Notional/premium freeing up on an expiry date
poetry run rysk positions expiring --address 0x... --expiry-date 2026-03-13 --json

# History summary
poetry run rysk history summary --address 0x... --json

# Expired positions filtered by outcome
poetry run rysk history expired --address 0x... --outcome assigned --json

# Deep-dive analytics (top premium / APR slices)
poetry run rysk history deep-dive --address 0x... --symbol WHYPE --json

# Assignment-avoidance rule backtest
poetry run rysk history assignment-backtest --address 0x... --min-premium-retained 80 --json

# Assignment backtest with HYPE realized-volatility veto rules
poetry run rysk history assignment-backtest --address 0x... --include-hype-vol --min-premium-retained 80 --json

# Pre-trade clearance gates for CC/CSP entries
poetry run rysk market clearance --assets HYPE,BTC --target-dte 21 --json

# Single action check for an agent: "is today good for a HYPE covered call?"
poetry run rysk market check --asset HYPE --strategy cc --target-dte 21 --json

# Realized expiry prices grouped by asset + expiry date
poetry run rysk history expiry-prices --address 0x... --json
```

Agent-friendly schema for `history expiry-prices --json`:

- `group_count`: number of `(symbol, expiry_date)` groups
- `positions_considered`: total expired rows after filters
- `groups[]` entries include:
  - `symbol`
  - `expiry` (unix timestamp)
  - `expiry_date`
  - `positions_total`
  - `positions_with_price`
  - `expiry_price`
  - `assigned_count`
  - `returned_count`

CLI reliability options:

- `--retries <n>` retries upstream calls before failing
- `--retry-delay <seconds>` delay between retries
- Exit codes:
  - `0` success
  - `2` validation error
  - `3` runtime error

## Project Structure

- `app.py` - Flask web server
- `analytics_services.py` - Protocol flow, tenor, outcome, and OTM/APR research datasets
- `dashboard_services.py` - Shared service layer for API routes + CLI parity
- `rysk_cli.py` - Agent-oriented CLI entrypoint
- `rpc_client.py` - Hyperliquid RPC client for balances
- `positions_api.py` - Positions/history API client (when endpoints available)
- `templates/dashboard.html` - Frontend HTML
- `static/css/style.css` - Styling
- `static/js/dashboard.js` - Frontend JavaScript
- `tests/` - CLI and API-parity unit tests

## Token Addresses

Token addresses are pre-configured in `rpc_client.py`:
- BTC, ETH, HYPE (whype + khype), SOL, PUMP, PURR

## External Data Sources

- Rysk positions/history APIs (v12)
- Hyperliquid APIs/RPC for spot and oracle-derived analytics
- Hyperliquid daily candles for realized-volatility indices (`/api/global/hype-volatility`, `/api/global/volatility`)
- Strategy clearance gates (`/api/strategy/clearance`) for CC/CSP pre-trade checks

## Outcome Automation

To keep expiry outcomes fresh without restarts:

- Use the protected admin endpoint:
  - `POST /api/admin/backfill-outcomes`
  - Header: `X-Admin-Token: <ADMIN_BACKFILL_TOKEN>`
- Configure `ADMIN_BACKFILL_TOKEN` in environment.
- Schedule two weekly runs on expiry day (example in `render.yaml`):
  - `30 09 * * 5` (first pass)
  - `00 14 * * 5` (second pass for late oracle finalization)

Safety behavior:

- Backfill only updates unresolved rows (`outcome IS NULL`, or provisional `Unknown` with missing `expiry_price_f`).
- It does **not** overwrite finalized `Assigned`/`Returned` rows.

## Wallet retention cohorts

Research → **Wallet Retention** shows monthly option-seller cohorts as return
percentages, without participant counts. Month 1 is the first
**observed attributed** sale, not a proven first-ever trade. Cohorts use all
stored history, independent of the Research window; the chain filter applies.
The same wallet address is counted once across chains in the All view; chain
views measure first observed activity on that chain. Wallets are not people.
The API is `GET /api/analytics/retention?chain_id=999` (omit the filter for all).

Public Global transaction tables and responses omit seller addresses. Owner
proofs remain in the local database for internal analysis and auditing. The
retention response includes a sanitized per-chain trade audit against that
same Global trades table, without participant totals or owner addresses.

### Anonymous trader analytics

Research also includes notional and premium leaderboards, fixed APR bands,
repeat-activity segments, and concentration shares. The endpoint is
`GET /api/analytics/participants?days=365&chain_id=999`; `days=0` means all
history, and omitting `chain_id` combines chains. These views follow the
Research window, unlike retention. All percentage shares use verified
attributed activity in the selected window, with attribution coverage shown.

Leaderboards show only the top ten stable aliases, amounts, financial share,
and weighted entry APR. APR uses annualizable premium divided by total
strike-notional-days, annualized over 365 days; it is not realized profit.
Trader APR bands are under 10%, 10–25%, 25–50%, 50–100%, and 100%+, with an
Unclassified category for traders without an annualizable result. Activity
segments distinguish one trade, repeat trades in one UTC calendar month, and
trades in multiple UTC months within the selected window.

Set `PARTICIPANT_ALIAS_SECRET` to a persistent random secret on the web service.
`render.yaml` generates it for Blueprint-managed provisioning. Existing
services must add it to their Render environment before deploying this feature.
Keep it stable across deploys: rotating it changes every alias. Missing secret
configuration disables rankings while leaving aggregate analytics available.
Aliases are keyed hashes of normalized wallet addresses, consistent across
chains and periods. There is no public address-to-alias lookup. On-chain
transactions remain independently traceable; these are presentation aliases,
not a guarantee of anonymity.

Internally, 20 distinct traders are required for rankings and participant-based
percentages. Each segment and retention cohort must meet this minimum; pooled
retention summaries use their pooled eligible denominator. Suppressed values
show **Limited history**, without redistributing their shares. Concentration
requires 100 traders and uses rounded-up group sizes for the top 1%, 5%, and
10%, ranking notional and premium independently. Exact participant counts stay
internal and are omitted from public JSON, labels, and tooltips. Trade counts
and financial amounts remain available. All analytics reuse the daily Render
refresh and persisted owner proofs; no additional backfill or scheduler runs.

Run the incremental daily pipeline:

```bash
poetry run python scripts/refresh_cohorts.py
```

This syncs new transactions on **both HyperEVM and Ethereum**, then recovers new
owners. A database-specific lock prevents overlapping refresh jobs. Successful
attributions and receipts persist in `trade_wallets`; source hash observations
persist in `trade_source_observations`. Only new trades and unavailable receipts
from the last seven days are attempted during normal incremental runs. Older
gaps are preserved and reported rather than repeatedly fetching months of data.
`render.yaml` defines a daily Render cron at 16:00 UTC (9am PDT / 8am PST).
It calls the protected `/api/admin/cohort-refresh` endpoint, which launches the
job on the web service that owns `/data/rysk_trades.db`. Cron cannot mount that
service's disk directly. The cron polls authenticated job status and fails if
the refresh fails or does not complete. The shared admin token and service URL
are referenced from the web service, not copied into source control. There is
no local Codex schedule. Apply the Blueprint to activate the Render cron;
local SQLite data is not automatically uploaded by a code deployment.

To seed Render from a completed local recovery, export a consistent snapshot,
transfer it to the service's disk, and merge it using the deployed import tool:

```bash
python scripts/cohort_cache.py export data/cohort-seed.sqlite.gz
# After transferring the snapshot to Render, run in its shell:
RYSK_DB_PATH=/data/rysk_trades.db python scripts/cohort_cache.py import /data/cohort-seed.sqlite.gz
# Or upload directly using the existing admin token and service URL in your environment:
python scripts/cohort_cache.py upload data/cohort-seed.sqlite.gz
```

Imports preserve existing deployment trades and settlement results, validate
wallet proofs against the destination trades, and can be safely repeated.
The authenticated upload endpoint accepts compressed snapshots up to 64 MiB
and caps the expanded snapshot at 256 MiB. It does not require new SSH access.
Snapshots are local data artifacts, excluded from version control. Successful
receipt caches retain block identity and raw mint/deposit logs needed to
reproduce attribution; unrelated transfer logs and bloom filters are omitted.

Manual recovery and reconciliation:

```bash
# HyperEVM (RPC_URL override supported)
poetry run python scripts/backfill_wallets.py --chain 999
# Ethereum (ETHEREUM_RPC_URL override supported)
poetry run python scripts/backfill_wallets.py --chain 1
# Explicit historical retry of cached gaps/rejections
poetry run python scripts/backfill_wallets.py --chain 999 --retry
# Full source audit: fetch history and reconcile every returned transaction hash
poetry run python scripts/sync.py --from-date 2025-07-01
```

The public HyperEVM RPC accepts up to 20 requests per batch. dRPC free endpoints
accept at most 3; use `--batch-size 3` with those endpoints. Worker concurrency
and aggregate request rate are bounded, with shared backoff on RPC failures.
A sync failure stops the cursor at the last successful window, and cursor writes
are monotonic. Replayed hashed and hashless rows do not inflate the stored count.
Dense API windows are split, and persisted hashes are checked before advancing.
An older row absent from the current upstream response is reported. After owner
recovery, an exact, unique match across all source fields can be reconciled with
a verified current transaction. The original row is preserved in
`reconciled_trade_records`, settlement results are carried forward, and only the
canonical transaction remains in Global totals. Ambiguous matches, conflicting
settlement results, and independently verified transactions are never merged.
No wallet signature, private key, or on-chain transaction is required.

Attribution uses the indexed `AccountOwner` in Gamma's
[`ShortOtokenMinted` event](https://github.com/opynfinance/GammaProtocol/blob/master/contracts/core/Controller.sol),
requires a successful matching receipt, an allowlisted chain-specific
router/controller, one mint with matching option quantity, and a matching
collateral deposit for the same owner and vault. Transaction senders and asset
addresses are never used as trader identities. Unsupported deployments,
ambiguous receipts, and collateral mismatches remain unattributed; receipt
proof is cached for review. This measures seller-wallet activity, not maker
retention. Deployment allowlists are in `wallet_attribution.py`.

Coverage is visible by chain and month. Missing hashes, unavailable receipts,
and rejected attributions can shift cohort membership or undercount returns;
results with gaps are provisional. Unprocessed months show a pending marker,
future months stay blank, and the final observed month is conservatively marked
partial (there is no verified ingestion-completeness watermark). Weighted
summaries pool original eligible cohort sizes and exclude partial/pending cells.
Thin cohorts display Limited history instead of percentages or denominators.
The earliest history can include established wallets whose previous activity
predates this dataset.
