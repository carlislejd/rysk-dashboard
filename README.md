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
# Provide a default wallet address (UI can also accept one at runtime)
export ACCOUNT_ADDRESS="0xYourAddress"

# API endpoints (when available)
export POSITIONS_API_URL="https://..."
export HISTORY_API_URL="https://..."
```

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

# History summary
poetry run rysk history summary --address 0x... --json

# Expired positions filtered by outcome
poetry run rysk history expired --address 0x... --outcome assigned --json

# Deep-dive analytics (top premium / APR slices)
poetry run rysk history deep-dive --address 0x... --symbol WHYPE --json
```

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
