"""
Agent-friendly CLI for the Rysk dashboard data model.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Iterable, List

from dashboard_services import (
    build_assignment_backtest,
    build_history_expiry_prices,
    build_history_deep_dive,
    build_positions_expiring,
    filter_expired_positions,
    filter_open_positions,
    get_history_payload,
    get_positions_payload,
    validate_account_address,
)
from risk_gate_services import build_clearance_board
from volatility_services import get_hype_volatility


EXIT_OK = 0
EXIT_VALIDATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _print_table(rows: List[Dict[str, Any]], columns: List[str]) -> None:
    if not rows:
        print("No rows.")
        return

    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(str(row.get(col, ""))))

    header = " | ".join(col.ljust(widths[col]) for col in columns)
    sep = "-+-".join("-" * widths[col] for col in columns)
    print(header)
    print(sep)
    for row in rows:
        print(" | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns))


def _call_with_retries(func, retries: int, retry_delay_s: float):
    attempt = 0
    while True:
        try:
            return func()
        except Exception:
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(retry_delay_s)


def cmd_account_validate(args: argparse.Namespace) -> int:
    address = validate_account_address(args.address)
    payload = {"ok": True, "address": address}
    if args.json:
        _print_json(payload)
    else:
        print(f"Address valid: {address}")
    return EXIT_OK


def cmd_positions_open(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_positions_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    open_positions = payload["positions"].get("open_positions") or []
    filtered = filter_open_positions(open_positions, symbol=args.symbol, strategy=args.strategy)

    result = {
        "account": account,
        "count": len(filtered),
        "filters": {"symbol": args.symbol, "strategy": args.strategy},
        "open_positions": filtered,
    }
    if args.json:
        _print_json(result)
    else:
        rows = [
            {
                "symbol": p.get("symbol"),
                "strategy": p.get("strategy"),
                "type": p.get("type"),
                "side": p.get("side"),
                "qty": _fmt(_to_float(p.get("quantity")), 4),
                "strike": _fmt(_to_float(p.get("strike")), 2),
                "premium": _fmt(_to_float(p.get("premium")), 2),
                "apr": _fmt(_to_float(p.get("apr")), 2),
                "expiry": p.get("expiry_date"),
            }
            for p in filtered
        ]
        _print_table(rows, ["symbol", "strategy", "type", "side", "qty", "strike", "premium", "apr", "expiry"])
    return EXIT_OK


def cmd_positions_expiring(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_positions_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    open_positions = payload["positions"].get("open_positions") or []
    result = {
        "account": account,
        **build_positions_expiring(
            open_positions,
            expiry_date=args.expiry_date,
            symbol=args.symbol,
            strategy=args.strategy,
        ),
    }

    if args.json:
        _print_json(result)
    else:
        print(f"Expiry date: {result['expiry_date']}")
        print(f"Positions: {result['count']}")
        print(f"Total notional freeing up: {_fmt(result['totals']['notional'], 2)}")
        print(f"Total premium: {_fmt(result['totals']['premium'], 2)}")
        rows = [
            {
                "symbol": p.get("symbol"),
                "strategy": p.get("strategy"),
                "type": p.get("type"),
                "qty": _fmt(_to_float(p.get("quantity")), 4),
                "strike": _fmt(_to_float(p.get("strike")), 2),
                "notional": _fmt(_to_float(p.get("notional")), 2),
                "premium": _fmt(_to_float(p.get("premium")), 2),
            }
            for p in result["positions"]
        ]
        _print_table(rows, ["symbol", "strategy", "type", "qty", "strike", "notional", "premium"])
    return EXIT_OK


def cmd_positions_strikes(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_positions_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    asset_summary = payload["positions"].get("asset_summary") or []
    symbol = args.symbol.upper() if args.symbol else None
    if symbol:
        asset_summary = [a for a in asset_summary if (a.get("symbol") or "").upper() == symbol]

    result_assets = []
    for asset in asset_summary:
        result_assets.append(
            {
                "symbol": asset.get("symbol"),
                "current_price": asset.get("current_price"),
                "strikes": asset.get("strikes") or [],
            }
        )

    result = {"account": account, "assets": result_assets}
    if args.json:
        _print_json(result)
    else:
        for asset in result_assets:
            print(f"\n{asset['symbol']} (spot={_fmt(asset.get('current_price'), 4)})")
            rows = []
            for strike in asset.get("strikes") or []:
                strategy_notional = strike.get("strategy_notional") or {}
                rows.append(
                    {
                        "strike": _fmt(_to_float(strike.get("strike")), 2),
                        "dominant": strike.get("dominant_strategy"),
                        "notional": _fmt(_to_float(strike.get("notional_total")), 2),
                        "cc_notional": _fmt(_to_float(strategy_notional.get("covered_call")), 2),
                        "csp_notional": _fmt(_to_float(strategy_notional.get("cash_secured_put")), 2),
                    }
                )
            _print_table(rows, ["strike", "dominant", "notional", "cc_notional", "csp_notional"])
    return EXIT_OK


def cmd_history_summary(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_history_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    summary = dict(payload["history"].get("summary") or {})
    summary.pop("unknown_count", None)
    result = {"account": account, "summary": summary}
    if args.json:
        _print_json(result)
    else:
        rows = [
            {"metric": "expired_count", "value": summary.get("expired_count", 0)},
            {"metric": "net_premium", "value": _fmt(_to_float(summary.get("net_premium")), 2)},
            {"metric": "assigned_count", "value": summary.get("assigned_count", 0)},
            {"metric": "returned_count", "value": summary.get("returned_count", 0)},
            {"metric": "total_notional", "value": _fmt(_to_float(summary.get("total_notional")), 2)},
        ]
        _print_table(rows, ["metric", "value"])
    return EXIT_OK


def cmd_history_expired(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_history_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    expired_positions = payload["history"].get("expired_positions") or []
    filtered = filter_expired_positions(expired_positions, symbol=args.symbol, outcome=args.outcome)
    result = {
        "account": account,
        "count": len(filtered),
        "filters": {"symbol": args.symbol, "outcome": args.outcome},
        "expired_positions": filtered,
    }

    if args.json:
        _print_json(result)
    else:
        rows = [
            {
                "created": p.get("created_at"),
                "symbol": p.get("symbol"),
                "strategy": p.get("strategy", "-"),
                "outcome": p.get("outcome"),
                "strike": _fmt(_to_float(p.get("strike")), 2),
                "expiry_price": _fmt(_to_float(p.get("expiry_price")), 2),
                "premium": _fmt(_to_float(p.get("premium")), 2),
                "apr": _fmt(_to_float(p.get("apr")), 2),
            }
            for p in filtered
        ]
        _print_table(rows, ["created", "symbol", "strategy", "outcome", "strike", "expiry_price", "premium", "apr"])
    return EXIT_OK


def cmd_history_deep_dive(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_history_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    deep_dive = build_history_deep_dive(payload["history"], symbol=args.symbol)
    result = {"account": account, "symbol": args.symbol, "deep_dive": deep_dive}

    if args.json:
        _print_json(result)
    else:
        print("Deep Dive")
        print(f"Positions considered: {deep_dive.get('positions_considered', 0)}")
        top_premium = deep_dive.get("top_premium_positions") or []
        rows = [
            {
                "symbol": p.get("symbol"),
                "outcome": p.get("outcome"),
                "premium": _fmt(_to_float(p.get("premium")), 2),
                "apr": _fmt(_to_float(p.get("apr")), 2),
                "expiry": p.get("expiry_date"),
            }
            for p in top_premium[:10]
        ]
        _print_table(rows, ["symbol", "outcome", "premium", "apr", "expiry"])
    return EXIT_OK


def cmd_history_expiry_prices(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_history_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    expired_positions = payload["history"].get("expired_positions") or []
    agg = build_history_expiry_prices(
        expired_positions,
        symbol=args.symbol,
        expiry_date=args.expiry_date,
    )
    rows = agg["groups"]
    result = {
        "account": account,
        **agg,
    }

    if args.json:
        _print_json(result)
    else:
        table_rows = [
            {
                "symbol": r.get("symbol"),
                "expiry": r.get("expiry"),
                "expiry_date": r.get("expiry_date"),
                "total": r.get("positions_total"),
                "priced": r.get("positions_with_price"),
                "expiry_price": _fmt(r.get("expiry_price"), 2),
                "assigned": r.get("assigned_count"),
                "returned": r.get("returned_count"),
            }
            for r in rows
        ]
        _print_table(
            table_rows,
            ["symbol", "expiry", "expiry_date", "total", "priced", "expiry_price", "assigned", "returned"],
        )
    return EXIT_OK


def cmd_history_assignment_backtest(args: argparse.Namespace) -> int:
    account = validate_account_address(args.address)
    payload = _call_with_retries(
        lambda: get_history_payload(account),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )
    volatility_points = None
    if args.include_hype_vol:
        vol = _call_with_retries(
            lambda: get_hype_volatility(days=args.hype_vol_days),
            retries=args.retries,
            retry_delay_s=args.retry_delay,
        )
        volatility_points = vol.get("series") or []
    backtest = build_assignment_backtest(
        payload["history"],
        symbol=args.symbol,
        strategy=args.strategy,
        min_premium_retained_pct=args.min_premium_retained,
        volatility_points=volatility_points,
    )
    result = {
        "account": account,
        "symbol": args.symbol,
        "strategy": args.strategy,
        "assignment_backtest": backtest,
    }

    if args.json:
        _print_json(result)
    else:
        baseline = backtest["baseline"]
        print("Assignment Backtest")
        print(f"Positions considered: {baseline['count']}")
        print(f"Assigned: {baseline['assigned_count']} ({baseline['assignment_rate'] * 100:.1f}%)")
        print(f"Premium: {_fmt(baseline['premium'], 2)}")
        print(f"Notional: {_fmt(baseline['notional'], 2)}")
        rows = []
        for rule in backtest.get("recommended_rules") or []:
            kept = rule["kept"]
            rows.append(
                {
                    "rule": rule["name"],
                    "premium_kept": f"{rule['premium_retained_pct']:.1f}%",
                    "assigned_avoided": f"{rule['assigned_count_avoided_pct']:.1f}%",
                    "assigned_notional_avoided": f"{rule['assigned_notional_avoided_pct']:.1f}%",
                    "kept_apr": _fmt(kept.get("notional_weighted_apr"), 2),
                }
            )
        _print_table(
            rows,
            ["rule", "premium_kept", "assigned_avoided", "assigned_notional_avoided", "kept_apr"],
        )
    return EXIT_OK


def cmd_market_clearance(args: argparse.Namespace) -> int:
    asset_arg = getattr(args, "asset", None)
    assets_value = asset_arg or getattr(args, "assets", None) or "HYPE,BTC"
    assets = [a.strip().upper() for a in assets_value.split(",") if a.strip()]
    strategies = [args.strategy] if args.strategy else None
    board = _call_with_retries(
        lambda: build_clearance_board(
            assets=assets,
            strategies=strategies,
            target_dte=args.target_dte,
            days=args.days,
        ),
        retries=args.retries,
        retry_delay_s=args.retry_delay,
    )

    if args.json:
        _print_json(board)
    else:
        if len(board.get("entries") or []) == 1:
            entry = board["entries"][0]
            metrics = entry.get("metrics") or {}
            print(entry.get("recommendation"))
            print(f"Status: {entry.get('overall')}")
            print(f"As of: {entry.get('as_of_date')}")
            print(f"Close: {_fmt(metrics.get('close'), 2)}")
            print(f"1d move: {_fmt(metrics.get('return_1d_pct'), 2)}%")
            print(f"3d move: {_fmt(metrics.get('return_3d_pct'), 2)}%")
            print(f"7d realized vol: {_fmt(metrics.get('rv_7d'), 2)}%")
            gate_rows = [
                {
                    "gate": g.get("name"),
                    "status": g.get("status"),
                    "value": _fmt(g.get("value"), 2),
                    "threshold": g.get("threshold"),
                }
                for g in entry.get("gates") or []
            ]
            _print_table(gate_rows, ["gate", "status", "value", "threshold"])
            return EXIT_OK

        rows = []
        for entry in board.get("entries") or []:
            blockers = [g["name"] for g in entry.get("gates") or [] if g.get("status") == "block"]
            warnings = [g["name"] for g in entry.get("gates") or [] if g.get("status") == "warn"]
            rows.append(
                {
                    "asset": entry.get("asset"),
                    "strategy": entry.get("strategy_label"),
                    "status": entry.get("overall"),
                    "close": _fmt(entry.get("close"), 2),
                    "date": entry.get("as_of_date"),
                    "blockers": ", ".join(blockers) if blockers else "-",
                    "warnings": ", ".join(warnings) if warnings else "-",
                }
            )
        _print_table(rows, ["asset", "strategy", "status", "close", "date", "blockers", "warnings"])
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rysk", description="Rysk dashboard CLI for agents and operators")
    sub = parser.add_subparsers(dest="group", required=True)

    account = sub.add_parser("account", help="Address validation and account helpers")
    account_sub = account.add_subparsers(dest="account_cmd", required=True)
    account_validate = account_sub.add_parser("validate", help="Validate wallet address format")
    account_validate.add_argument("--address", required=True)
    account_validate.add_argument("--json", action="store_true")
    account_validate.set_defaults(func=cmd_account_validate)

    positions = sub.add_parser("positions", help="Open position and strike views")
    positions_sub = positions.add_subparsers(dest="positions_cmd", required=True)
    pos_open = positions_sub.add_parser("open", help="Open positions")
    pos_open.add_argument("--address", required=True)
    pos_open.add_argument("--symbol")
    pos_open.add_argument("--strategy", choices=["csp", "cc", "cash_secured_put", "covered_call"])
    pos_open.add_argument("--retries", type=int, default=1)
    pos_open.add_argument("--retry-delay", type=float, default=0.5)
    pos_open.add_argument("--json", action="store_true")
    pos_open.set_defaults(func=cmd_positions_open)

    pos_expiring = positions_sub.add_parser("expiring", help="Notional/premium expiring on a target date")
    pos_expiring.add_argument("--address", required=True)
    pos_expiring.add_argument("--expiry-date", required=True, help="YYYY-MM-DD")
    pos_expiring.add_argument("--symbol")
    pos_expiring.add_argument("--strategy", choices=["csp", "cc", "cash_secured_put", "covered_call"])
    pos_expiring.add_argument("--retries", type=int, default=1)
    pos_expiring.add_argument("--retry-delay", type=float, default=0.5)
    pos_expiring.add_argument("--json", action="store_true")
    pos_expiring.set_defaults(func=cmd_positions_expiring)

    pos_strikes = positions_sub.add_parser("strikes", help="Open position strike breakdown")
    pos_strikes.add_argument("--address", required=True)
    pos_strikes.add_argument("--symbol")
    pos_strikes.add_argument("--retries", type=int, default=1)
    pos_strikes.add_argument("--retry-delay", type=float, default=0.5)
    pos_strikes.add_argument("--json", action="store_true")
    pos_strikes.set_defaults(func=cmd_positions_strikes)

    history = sub.add_parser("history", help="Historical performance and deep dive")
    history_sub = history.add_subparsers(dest="history_cmd", required=True)

    hist_summary = history_sub.add_parser("summary", help="History summary")
    hist_summary.add_argument("--address", required=True)
    hist_summary.add_argument("--retries", type=int, default=1)
    hist_summary.add_argument("--retry-delay", type=float, default=0.5)
    hist_summary.add_argument("--json", action="store_true")
    hist_summary.set_defaults(func=cmd_history_summary)

    hist_expired = history_sub.add_parser("expired", help="Expired positions")
    hist_expired.add_argument("--address", required=True)
    hist_expired.add_argument("--symbol")
    hist_expired.add_argument("--outcome", choices=["assigned", "returned", "unknown"])
    hist_expired.add_argument("--retries", type=int, default=1)
    hist_expired.add_argument("--retry-delay", type=float, default=0.5)
    hist_expired.add_argument("--json", action="store_true")
    hist_expired.set_defaults(func=cmd_history_expired)

    hist_deep = history_sub.add_parser("deep-dive", help="Deep dive history analytics")
    hist_deep.add_argument("--address", required=True)
    hist_deep.add_argument("--symbol")
    hist_deep.add_argument("--retries", type=int, default=1)
    hist_deep.add_argument("--retry-delay", type=float, default=0.5)
    hist_deep.add_argument("--json", action="store_true")
    hist_deep.set_defaults(func=cmd_history_deep_dive)

    hist_expiry_prices = history_sub.add_parser(
        "expiry-prices",
        help="Aggregate realized expiry prices by asset and expiry date",
    )
    hist_expiry_prices.add_argument("--address", required=True)
    hist_expiry_prices.add_argument("--symbol")
    hist_expiry_prices.add_argument("--expiry-date", help="Optional filter YYYY-MM-DD")
    hist_expiry_prices.add_argument("--retries", type=int, default=1)
    hist_expiry_prices.add_argument("--retry-delay", type=float, default=0.5)
    hist_expiry_prices.add_argument("--json", action="store_true")
    hist_expiry_prices.set_defaults(func=cmd_history_expiry_prices)

    hist_assignment_backtest = history_sub.add_parser(
        "assignment-backtest",
        help="Backtest assignment-avoidance veto rules against expired wallet history",
    )
    hist_assignment_backtest.add_argument("--address", required=True)
    hist_assignment_backtest.add_argument("--symbol")
    hist_assignment_backtest.add_argument("--strategy", choices=["csp", "cc", "cash_secured_put", "covered_call"])
    hist_assignment_backtest.add_argument(
        "--min-premium-retained",
        type=float,
        default=70.0,
        help="Only recommend rules that keep at least this percent of baseline premium",
    )
    hist_assignment_backtest.add_argument("--retries", type=int, default=1)
    hist_assignment_backtest.add_argument("--retry-delay", type=float, default=0.5)
    hist_assignment_backtest.add_argument(
        "--include-hype-vol",
        action="store_true",
        help="Fetch HYPE daily realized volatility and test volatility veto rules",
    )
    hist_assignment_backtest.add_argument(
        "--hype-vol-days",
        type=int,
        default=730,
        help="Daily HYPE price window used when --include-hype-vol is set",
    )
    hist_assignment_backtest.add_argument("--json", action="store_true")
    hist_assignment_backtest.set_defaults(func=cmd_history_assignment_backtest)

    market = sub.add_parser("market", help="Market risk and pre-trade clearance")
    market_sub = market.add_subparsers(dest="market_cmd", required=True)
    market_clearance = market_sub.add_parser(
        "clearance",
        help="Show CC/CSP pre-trade clearance gates for HYPE/BTC",
    )
    market_clearance.add_argument("--assets", default="HYPE,BTC", help="Comma-separated assets, e.g. HYPE,BTC")
    market_clearance.add_argument("--strategy", choices=["cc", "covered_call", "csp", "cash_secured_put"])
    market_clearance.add_argument("--target-dte", type=float, help="Optional target DTE for the contemplated trade")
    market_clearance.add_argument("--days", type=int, default=180)
    market_clearance.add_argument("--retries", type=int, default=1)
    market_clearance.add_argument("--retry-delay", type=float, default=0.5)
    market_clearance.add_argument("--json", action="store_true")
    market_clearance.set_defaults(func=cmd_market_clearance)

    market_check = market_sub.add_parser(
        "check",
        help="Check whether a specific CC/CSP action is clear today",
    )
    market_check.add_argument("--asset", required=True, help="Asset to check, e.g. HYPE or BTC")
    market_check.add_argument("--strategy", required=True, choices=["cc", "covered_call", "csp", "cash_secured_put"])
    market_check.add_argument("--target-dte", type=float, help="Optional target DTE for the contemplated trade")
    market_check.add_argument("--days", type=int, default=180)
    market_check.add_argument("--retries", type=int, default=1)
    market_check.add_argument("--retry-delay", type=float, default=0.5)
    market_check.add_argument("--json", action="store_true")
    market_check.set_defaults(func=cmd_market_clearance)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except ValueError as exc:
        err = {"ok": False, "error": str(exc), "code": "validation_error"}
        if getattr(args, "json", False):
            _print_json(err)
        else:
            print(f"Validation error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION_ERROR
    except Exception as exc:
        err = {"ok": False, "error": str(exc), "code": "runtime_error"}
        if getattr(args, "json", False):
            _print_json(err)
        else:
            print(f"Runtime error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
