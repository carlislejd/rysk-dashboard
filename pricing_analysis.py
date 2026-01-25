"""
Option Pricing Analysis
Calculates realized volatility, compares to implied volatility, and determines if options are rich/cheap
"""

import math
from datetime import datetime, timedelta

from hyperliquid_client import get_price_history


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x ** 2)


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

def calculate_realized_volatility(prices, days=30):
    """
    Calculate annualized realized volatility from price history
    
    Args:
        prices: List of closing prices
        days: Number of days to use for calculation
    
    Returns:
        Annualized volatility as a percentage
    """
    if len(prices) < 2:
        return None
    
    # Calculate returns
    returns = []
    for i in range(1, len(prices)):
        if prices[i-1] > 0:
            ret = math.log(prices[i] / prices[i-1])
            returns.append(ret)
    
    if len(returns) < 2:
        return None
    
    # Calculate standard deviation of returns
    mean_return = sum(returns) / len(returns)
    variance = sum((ret - mean_return) ** 2 for ret in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    
    # Annualize based on data frequency
    # We're using hourly candles, so we need to scale by sqrt(24 * 365)
    # But we should use the actual number of data points to determine frequency
    # For hourly data: sqrt(24 * 365) ≈ 93.6
    # For daily data: sqrt(365) ≈ 19.1
    # Since we're fetching hourly candles, use hourly scaling
    if len(prices) > 24 * 7:  # More than a week of hourly data
        periods_per_year = 24 * 365  # hourly data
    else:
        periods_per_year = 365  # daily data (fallback)
    
    annualized_vol = std_dev * math.sqrt(periods_per_year)
    
    return annualized_vol * 100  # Convert to percentage

def calculate_greeks(strike, current_price, time_to_expiry_days, iv, risk_free_rate=0.05):
    """
    Calculate option Greeks using Black-Scholes
    
    Args:
        strike: Strike price
        current_price: Current underlying price
        time_to_expiry_days: Days until expiration
        iv: Implied volatility (as decimal, e.g., 0.75 for 75%)
        risk_free_rate: Risk-free rate (default 5%)
    
    Returns:
        Dictionary with delta, gamma, vega, theta
    """
    if time_to_expiry_days <= 0:
        return {
            "delta": 0,
            "gamma": 0,
            "vega": 0,
            "theta": 0
        }
    
    S = current_price
    K = strike
    T = time_to_expiry_days / 365.0
    r = risk_free_rate
    sigma = iv / 100.0  # Convert from percentage to decimal
    
    if T <= 0 or sigma <= 0:
        return {
            "delta": 0,
            "gamma": 0,
            "vega": 0,
            "theta": 0
        }
    
    # Black-Scholes calculations
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    # Delta (for call option)
    delta = _norm_cdf(d1)
    
    # Gamma
    gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    
    # Vega (per 1% change in vol)
    vega = S * _norm_pdf(d1) * math.sqrt(T) / 100.0
    
    # Theta (per day, negative for time decay)
    theta_part1 = -S * _norm_pdf(d1) * sigma / (2 * math.sqrt(T))
    theta_part2 = -r * K * math.exp(-r * T) * _norm_cdf(d2)
    theta = (theta_part1 + theta_part2) / 365.0
    
    return {
        "delta": delta,
        "gamma": gamma * 100,  # Scale gamma for readability
        "vega": vega,
        "theta": theta
    }

def analyze_option_richness(implied_vol, realized_vol, strike, current_price, days_to_expiry):
    """
    Determine if an option is rich or cheap based on IV vs RV
    
    Args:
        implied_vol: Implied volatility percentage
        realized_vol: Realized volatility percentage
        strike: Strike price
        current_price: Current price
        days_to_expiry: Days until expiration
    
    Returns:
        Dictionary with analysis results
    """
    if realized_vol is None or implied_vol is None:
        return {
            "rich_cheap": "unknown",
            "iv_rv_spread": None,
            "rich_cheap_score": 0
        }
    
    iv_rv_spread = implied_vol - realized_vol
    
    # Determine rich/cheap
    if iv_rv_spread > 20:  # IV is 20%+ higher than RV
        rich_cheap = "rich"
        score = min(100, (iv_rv_spread / 50) * 100)  # Scale to 0-100
    elif iv_rv_spread < -10:  # IV is 10%+ lower than RV
        rich_cheap = "cheap"
        score = max(-100, (iv_rv_spread / 30) * 100)  # Scale to -100-0
    elif abs(iv_rv_spread) <= 10:  # Within 10%
        rich_cheap = "fair"
        score = 0
    else:
        rich_cheap = "slightly_rich" if iv_rv_spread > 0 else "slightly_cheap"
        score = iv_rv_spread * 2  # Scale proportionally
    
    return {
        "rich_cheap": rich_cheap,
        "iv_rv_spread": round(iv_rv_spread, 2),
        "rich_cheap_score": round(score, 1),
        "implied_vol": round(implied_vol, 2),
        "realized_vol": round(realized_vol, 2)
    }

def analyze_option(option_data, asset, current_price):
    """
    Comprehensive option analysis
    
    Args:
        option_data: Dictionary with strike, apy, delta, bidIv, askIv, mid_iv, expiry, days_to_expiry
        asset: Asset name
        current_price: Current price of the asset
    
    Returns:
        Dictionary with full analysis
    """
    try:
        strike = option_data.get("strike", 0)
        days_to_expiry = option_data.get("days_to_expiry", 0)
        mid_iv = option_data.get("mid_iv", 0)
        bid_iv = option_data.get("bid_iv", 0)
        ask_iv = option_data.get("ask_iv", 0)
        
        # Use mid IV, or average of bid/ask if available
        implied_vol = mid_iv
        if implied_vol == 0 and bid_iv > 0 and ask_iv > 0:
            implied_vol = (bid_iv + ask_iv) / 2
        
        # Get price history for realized volatility
        realized_vol = None
        try:
            price_history = get_price_history(asset, days=min(30, days_to_expiry + 7), interval="1h")
            if price_history and len(price_history) > 1:
                closes = [candle["close"] for candle in price_history]
                realized_vol = calculate_realized_volatility(closes, days=30)
        except Exception as e:
            print(f"Error calculating realized vol for {asset}: {e}")
        
        # Calculate Greeks (only if we have valid inputs)
        greeks = {"delta": 0, "gamma": 0, "vega": 0, "theta": 0}
        if strike > 0 and current_price > 0 and days_to_expiry > 0 and implied_vol > 0:
            try:
                greeks = calculate_greeks(strike, current_price, days_to_expiry, implied_vol)
            except Exception as e:
                print(f"Error calculating Greeks: {e}")
        
        # Rich/Cheap analysis
        richness = analyze_option_richness(implied_vol, realized_vol, strike, current_price, days_to_expiry)
        
        # Moneyness
        moneyness = option_data.get("moneyness", ((strike / current_price - 1) * 100) if current_price > 0 else 0)
        
        return {
            **option_data,
            "implied_vol": round(implied_vol, 2) if implied_vol > 0 else None,
            "realized_vol": round(realized_vol, 2) if realized_vol else None,
            "greeks": greeks,
            "richness": richness,
            "moneyness": round(moneyness, 2)
        }
    except Exception as e:
        print(f"Error in analyze_option: {e}")
        # Return original data if analysis fails
        return option_data

