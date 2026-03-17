"""
RPC Client for Hyperliquid EVM
Fetches token balances from the blockchain
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

# Token decimals
TOKEN_DECIMALS = {
    "BTC": 8,
    "ETH": 18,
    "HYPE": 18,
    "SOL": 18,
    "PUMP": 18,
    "PURR": 18,
    "USDT0": 6,
    "ZEC": 18,
    "XRP": 18,
}

def get_rpc_connection():
    """Get Web3 connection to Hyperliquid RPC"""
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    w3.eth.default_chain_id = CHAIN_ID
    return w3

def get_balance(w3: Web3, account_address: str, token_address: str, decimals: int = 18) -> float:
    """
    Get ERC20 token balance for an account
    
    Args:
        w3: Web3 instance
        account_address: Account address to check
        token_address: Token contract address
        decimals: Token decimals (default 18)
    
    Returns:
        Balance as float
    """
    if not token_address:
        return 0.0
    
    try:
        # ERC20 balanceOf(address) function
        token_contract = w3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=[{
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }]
        )
        
        balance = token_contract.functions.balanceOf(Web3.to_checksum_address(account_address)).call()
        return balance / (10 ** decimals)
    except Exception as e:
        print(f"Error fetching balance for {token_address}: {e}")
        return 0.0

def get_all_balances(account_address: str) -> dict:
    """
    Get balances for all configured tokens
    
    Args:
        account_address: Account address to check
    
    Returns:
        Dictionary of token -> balance
    """
    w3 = get_rpc_connection()
    
    if not w3.is_connected():
        print("❌ Failed to connect to RPC")
        return {}
    
    balances = {}
    for token_name, token_address in TOKEN_ADDRESSES.items():
        if token_name == "HYPE":
            # Sum balances from both whype and khype
            decimals = TOKEN_DECIMALS.get(token_name, 18)
            total_balance = 0.0
            for hype_address in HYPE_ADDRESSES:
                balance = get_balance(w3, account_address, hype_address, decimals)
                total_balance += balance
            balances[token_name] = total_balance
        elif token_address:
            decimals = TOKEN_DECIMALS.get(token_name, 18)
            balance = get_balance(w3, account_address, token_address, decimals)
            balances[token_name] = balance
        else:
            balances[token_name] = 0.0
    
    return balances

