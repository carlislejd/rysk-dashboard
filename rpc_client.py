"""
RPC Client for Hyperliquid EVM
Provides shared Web3 access and token address metadata.
"""

from web3 import Web3
import os

# Hyperliquid RPC
RPC_URL = os.getenv("RPC_URL", "https://rpc.hyperliquid.xyz/evm")
CHAIN_ID = 999

# Token addresses
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

# HYPE variants (whype and khype - treated as same asset)
HYPE_ADDRESSES = [
    "0x5555555555555555555555555555555555555555",  # whype
    "0xfD739d4e423301CE9385c1fb8850539D657C296D",  # khype
]

def get_rpc_connection():
    """Get Web3 connection to Hyperliquid RPC"""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.eth.default_chain_id = CHAIN_ID
    return w3
