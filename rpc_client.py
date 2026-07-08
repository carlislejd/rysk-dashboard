"""
RPC clients and token metadata for Rysk-supported EVM chains.
"""

from web3 import Web3
import os

from chain_metadata import ETHEREUM_CHAIN_ID, HYPEREVM_CHAIN_ID, default_chain_id, parse_chain_id


# RPC configuration. RPC_URL remains the backwards-compatible HyperEVM knob.
HYPEREVM_RPC_URL = os.getenv("HYPEREVM_RPC_URL", os.getenv("RPC_URL", "https://rpc.hyperliquid.xyz/evm"))
ETHEREUM_RPC_URL = os.getenv("ETHEREUM_RPC_URL", os.getenv("MAINNET_RPC_URL", ""))
CHAIN_ID = HYPEREVM_CHAIN_ID
RPC_URL = HYPEREVM_RPC_URL

RPC_URLS = {
    HYPEREVM_CHAIN_ID: HYPEREVM_RPC_URL,
    ETHEREUM_CHAIN_ID: ETHEREUM_RPC_URL,
}

# HyperEVM token addresses.
TOKEN_ADDRESSES = {
    "BTC": os.getenv("BTC_ADDRESS", "0x9FDBdA0A5e284c32744D2f17Ee5c74B284993463"),
    "ETH": os.getenv("ETH_ADDRESS", "0xBe6727B535545C67d5cAa73dEa54865B92CF7907"),
    "HYPE": os.getenv("HYPE_ADDRESS", "0x5555555555555555555555555555555555555555"),  # whype
    "SOL": os.getenv("SOL_ADDRESS", "0x068f321Fa8Fb9f0D135f290Ef6a3e2813e1c8A29"),
    "PUMP": os.getenv("PUMP_ADDRESS", "0x27eC642013bcB3D80CA3706599D3cdA04F6f4452"),
    "PURR": os.getenv("PURR_ADDRESS", "0x9b498C3c8A0b8CD8BA1D9851d40D186F1872b44E"),
    "USDT0": os.getenv("USDT0_ADDRESS", "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb"),
    "ZEC": os.getenv("ZEC_ADDRESS", "0xbe068Bb3c7ef5B56360655638f75bf5A6C5f8C10"),
    "XRP": os.getenv("XRP_ADDRESS", "0xd70659a6396285bf7214d7ea9673184e7c72e07e"),
}

# Ethereum mainnet fallback token addresses. Prefer API-provided underlying
# addresses for new markets; these are only symbol fallbacks.
ETHEREUM_TOKEN_ADDRESSES = {
    "BTC": os.getenv("ETHEREUM_BTC_ADDRESS", os.getenv("WBTC_ADDRESS", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")),
    "WBTC": os.getenv("ETHEREUM_BTC_ADDRESS", os.getenv("WBTC_ADDRESS", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")),
    "ETH": os.getenv("ETHEREUM_ETH_ADDRESS", os.getenv("WETH_ADDRESS", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")),
    "WETH": os.getenv("ETHEREUM_ETH_ADDRESS", os.getenv("WETH_ADDRESS", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")),
    "USDC": os.getenv("ETHEREUM_USDC_ADDRESS", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "USDT": os.getenv("ETHEREUM_USDT_ADDRESS", "0xdAC17F958D2ee523a2206206994597C13D831ec7"),
}

# HYPE variants (whype and khype - treated as same asset)
HYPE_ADDRESSES = [
    "0x5555555555555555555555555555555555555555",  # whype
    "0xfD739d4e423301CE9385c1fb8850539D657C296D",  # khype
]


def get_rpc_connection(chain_id=None):
    """Get a Web3 connection for the requested chain."""
    resolved_chain_id = parse_chain_id(chain_id, default=default_chain_id()) or default_chain_id()
    rpc_url = RPC_URLS.get(resolved_chain_id)
    if not rpc_url:
        raise RuntimeError(f"No RPC URL configured for chain {resolved_chain_id}")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.eth.default_chain_id = resolved_chain_id
    return w3
