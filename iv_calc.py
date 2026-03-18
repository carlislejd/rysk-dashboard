"""
Implied Volatility calculator using Black-Scholes.
Newton-Raphson with bisection fallback for robustness.
"""

import math

def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(S, K, T, r, sigma, is_put):
    """Black-Scholes option price."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_put:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    else:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_vega(S, K, T, r, sigma):
    """Vega: derivative of BS price w.r.t. sigma."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * _norm_pdf(d1) * math.sqrt(T)


def implied_volatility(market_price, S, K, T, r, is_put, max_iter=100, tol=1e-6):
    """Compute IV using Newton-Raphson with bisection fallback.

    Args:
        market_price: observed option premium (per unit of underlying)
        S: spot price of underlying
        K: strike price
        T: time to expiry in years
        r: risk-free rate (e.g. 0.045 for 4.5%)
        is_put: True for put, False for call

    Returns:
        IV as a decimal (e.g. 0.85 = 85%), or None if it doesn't converge.
    """
    if market_price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None

    # Intrinsic value check — premium must exceed intrinsic for IV to exist
    intrinsic = max(0, (K * math.exp(-r * T) - S) if is_put else (S - K * math.exp(-r * T)))
    if market_price < intrinsic:
        return None

    # Try Newton-Raphson first with Brenner-Subrahmanyam initial guess
    sigma = math.sqrt(2.0 * math.pi / T) * (market_price / S)
    sigma = max(0.01, min(sigma, 5.0))

    for _ in range(50):
        price = bs_price(S, K, T, r, sigma, is_put)
        vega = bs_vega(S, K, T, r, sigma)

        if vega < 1e-12:
            break

        diff = price - market_price
        if abs(diff) < tol:
            return sigma

        sigma -= diff / vega
        sigma = max(0.001, min(sigma, 10.0))

    # Check if Newton converged
    if abs(bs_price(S, K, T, r, sigma, is_put) - market_price) < tol * 10:
        return sigma

    # Bisection fallback — slower but always converges if a root exists
    lo, hi = 0.001, 10.0

    # Verify the root is bracketed
    if bs_price(S, K, T, r, lo, is_put) > market_price:
        return None
    if bs_price(S, K, T, r, hi, is_put) < market_price:
        return None

    for _ in range(100):
        mid = (lo + hi) / 2.0
        price = bs_price(S, K, T, r, mid, is_put)
        if abs(price - market_price) < tol:
            return mid
        if price < market_price:
            lo = mid
        else:
            hi = mid

    return (lo + hi) / 2.0
