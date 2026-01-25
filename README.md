# Rysk Covered Calls Dashboard

Web dashboard for managing Rysk covered call positions.

## Features

- **Token Balances**: View balances for BTC, ETH, HYPE, SOL, PUMP, PURR
- **Available Inventory**: See current options available from Rysk API
- **Open Positions**: Track current positions (API endpoint needed)
- **Historical Performance**: View past performance (API endpoint needed)

## Setup

1. Install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. (Optional) Configure environment variables:
```bash
# Provide a default wallet address (UI can also accept one at runtime)
export ACCOUNT_ADDRESS="0xYourAddress"

# API endpoints (when available)
export POSITIONS_API_URL="https://..."
export HISTORY_API_URL="https://..."
```

3. Run the Flask web server:
```bash
python app.py
```

4. Open the dashboard and enter a wallet address when prompted:
```
http://localhost:5001
```

## Project Structure

- `app.py` - Flask web server
- `rpc_client.py` - Hyperliquid RPC client for balances
- `inventory_api.py` - Rysk inventory API client
- `positions_api.py` - Positions/history API client (when endpoints available)
- `templates/dashboard.html` - Frontend HTML
- `static/css/style.css` - Styling
- `static/js/dashboard.js` - Frontend JavaScript

## Token Addresses

Token addresses are pre-configured in `rpc_client.py`:
- BTC, ETH, HYPE (whype + khype), SOL, PUMP, PURR

## API Endpoints Needed

- Positions API: For current open positions
- History API: For historical performance data

Contact Rysk team for these endpoints.
