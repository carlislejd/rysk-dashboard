"""Recover option sellers from successful Gamma mint receipts, never tx.from.

Event ABI: opynfinance/GammaProtocol contracts/core/Controller.sol,
ShortOtokenMinted(address,address,address,uint256,uint256).
The indexed AccountOwner is the short position owner, not the executor.
"""
from decimal import Decimal

MINT_TOPIC = '0x4d7f96086c92b2f9a254ad21548b1c1f2d99502c7949508866349b96bb1a8d8a'
DEPOSIT_TOPIC = '0xbfab88b861f171b7db714f00e5966131253918d55ddba816c3eb94657d102390'
# Deployments validated against real HyperEVM and Ethereum receipts.
# Fail closed on other deployments; fixtures preserve representative evidence.
CONTROLLERS = {999: {'0x577b846a95711015769452f7f29d8054cf087964'},
               1: {'0xc64453119e2728e956f0815447efb1e1eb30df2d'}}
ROUTERS = {999: {'0x8c8bcb6d2c0e31c5789253ecc8431ca6209b4e35'},
           1: {'0x7a3ddeac7a0ae6dfa9391c764499a3564f3c2aad'}}


def receipt_proof(receipt):
    """Keep the raw events and block identity needed to reproduce attribution.

    Transfer logs and bloom filters are unrelated to owner recovery and make
    the persistent cache several times larger. Keep every mint/deposit event,
    including untrusted emitters, so ambiguity checks remain reproducible.
    """
    if not receipt:
        return None
    proof = {key: receipt[key] for key in
             ('transactionHash', 'blockHash', 'blockNumber', 'status', 'to', 'from') if key in receipt}
    proof['logs'] = [log for log in receipt.get('logs', [])
                     if (log.get('topics') or [None])[0] in (MINT_TOPIC, DEPOSIT_TOPIC)]
    return proof


def recover_wallet(trade, receipt):
    """Require one mint, matching quantity, and matching collateral/vault owner."""
    if not receipt:
        return None, 'receipt_unavailable'
    if str(receipt.get('transactionHash') or '').lower() != str(trade['tx_hash']).lower():
        return None, 'hash_mismatch'
    if receipt.get('status') != '0x1':
        return None, 'unsuccessful_receipt'
    chain = trade['chain_id']
    if str(receipt.get('to') or '').lower() not in ROUTERS.get(chain, set()):
        return None, 'unsupported_router'
    logs = [log for log in receipt.get('logs', []) if not log.get('removed')]
    mints = [log for log in logs if (log.get('topics') or [None])[0] == MINT_TOPIC
             and log.get('address', '').lower() in CONTROLLERS.get(chain, set())]
    if len(mints) != 1:
        return None, 'ambiguous_or_missing_mint'
    mint = mints[0]
    if len(mint['topics']) != 4 or len(mint.get('data', '')) != 130:
        return None, 'malformed_mint'
    try:
        quantity = Decimal(trade['quantity']) / Decimal(10**10)  # 18 -> 8 decimals
        amount = int(mint['data'][66:], 16)
        if quantity != amount or amount <= 0:
            return None, 'quantity_mismatch'
        owner_word = mint['topics'][2].lower()
        if len(owner_word) != 66 or not owner_word.startswith('0x' + '0' * 24):
            return None, 'malformed_owner'
        owner = '0x' + owner_word[-40:]
        if int(owner, 16) == 0:
            return None, 'zero_owner'
        collateral = str(trade['collateral'] or '').lower()
        matches = [log for log in logs if len(log.get('topics', [])) == 4
                   and log['topics'][0] == DEPOSIT_TOPIC
                   and log['address'].lower() == mint['address'].lower()
                   and log['topics'][2].lower() == owner_word
                   and '0x' + log['topics'][1][-40:].lower() == collateral
                   and len(log.get('data', '')) == 130
                   and log['data'][2:66] == mint['data'][2:66]]
        if not matches:
            return None, 'collateral_owner_mismatch'
    except (ValueError, TypeError, ArithmeticError):
        return None, 'malformed_event'
    return owner, 'verified_short_owner'
