# Rysk Options Dashboard

Web dashboard and agent-friendly CLI for managing Rysk option positions.

## Features

- **Token Balances**: View balances for BTC, ETH, HYPE, SOL, PUMP, PURR
- **Open Positions**: Track current positions with strategy tagging (CC/CSP)
- **Historical Performance**: View expired outcomes and deep-dive analytics
- **CLI**: Query account, open positions, strike distributions, and history in table or JSON mode

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

# Realized expiry prices grouped by asset + expiry date
poetry run rysk history expiry-prices --address 0x... --json
```

Agent-friendly schema for `history expiry-prices --json`:

- `group_count`: number of `(symbol, expiry_date)` groups
- `positions_considered`: total expired rows after filters
- `groups[]` entries include:
  - `symbol`
  - `expiry_date`
  - `positions_total`
  - `positions_with_price`
  - `avg_expiry_price`
  - `min_expiry_price`
  - `max_expiry_price`
  - `assigned_count`
  - `returned_count`
  - `unknown_count`

CLI reliability options:

- `--retries <n>` retries upstream calls before failing
- `--retry-delay <seconds>` delay between retries
- Exit codes:
  - `0` success
  - `2` validation error
  - `3` runtime error

## Project Structure

- `app.py` - Flask web server
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
