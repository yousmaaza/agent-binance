#!/usr/bin/env python3
"""Stub kraken-cli piloté par un scénario JSON — usage exclusif tests/.

Chemin du scénario lu depuis la variable d'env FAKE_KRAKEN_SCENARIO. Format :
{
  "ticker": {"ETHUSDC": {"c": ["1900.0", "0.01"], "b": ["1899.5", "0.01"]}},
  "balance": {"USDC": "500.0", "ETH": "0.0"},
  "pairs": {"ETHUSDC": {"lot_decimals": 8, "ordermin": "0.06"}},
  "order_buy_ETHUSDC": {"txid": ["TXID123"]},
  "order_sell_ETHUSDC": {"txid": ["SL_TXID"]},
  "query-orders_TXID123": {"TXID123": {"status": "closed", "cost": "190.0", "vol_exec": "0.1"}}
}

Sous-commandes supportées : ticker, balance, pairs, ohlc, order buy, order sell, order amend,
order cancel, query-orders.

Pour `order buy`/`order sell`, la clé cherchée est d'abord `order_<sub>_<pair>_<type>` (ex.
order_buy_ETHUSDC_limit) puis, à défaut, `order_<sub>_<pair>` — permet de distinguer dans un même
scénario la pose LIMIT post-only (#388) du repli BUY MARKET sur le même pair.
Pour `order amend --txid <id> ...`, la clé est `order_amend_<id>`.
Pour `order cancel <id> ...`, la clé est `order_cancel_<id>`.
"""
import json
import os
import sys


def _load_scenario():
    path = os.environ.get("FAKE_KRAKEN_SCENARIO")
    if not path:
        print("FAKE_KRAKEN_SCENARIO non défini", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def _positional_args(args):
    return [a for a in args if not a.startswith("-") and a != "json"]


def main():
    argv = sys.argv[1:]
    if not argv:
        print("Usage: fake_kraken.py <command> ...", file=sys.stderr)
        sys.exit(1)

    scenario = _load_scenario()
    cmd = argv[0]

    if cmd == "ticker":
        pairs = _positional_args(argv[1:])
        data = scenario.get("ticker", {})
        result = {p: data[p] for p in pairs if p in data} if pairs else data
        print(json.dumps(result))
    elif cmd == "balance":
        print(json.dumps(scenario.get("balance", {})))
    elif cmd == "pairs":
        data = scenario.get("pairs", {})
        if "--pair" in argv:
            pair = argv[argv.index("--pair") + 1]
            data = {pair: data[pair]} if pair in data else {}
        print(json.dumps(data))
    elif cmd == "ohlc":
        pair = argv[1] if len(argv) > 1 else ""
        data = scenario.get("ohlc", {})
        result = {pair: data[pair]} if pair in data else {}
        print(json.dumps(result))
    elif cmd == "order":
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "amend":
            txid = argv[argv.index("--txid") + 1] if "--txid" in argv else ""
            key = f"order_amend_{txid}"
            print(json.dumps(scenario.get(key, {})))
        elif sub == "cancel":
            txid = argv[2] if len(argv) > 2 else ""
            key = f"order_cancel_{txid}"
            print(json.dumps(scenario.get(key, {})))
        else:
            pair = argv[2] if len(argv) > 2 else ""
            order_type = argv[argv.index("--type") + 1] if "--type" in argv else ""
            typed_key = f"order_{sub}_{pair}_{order_type}"
            plain_key = f"order_{sub}_{pair}"
            result = scenario[typed_key] if typed_key in scenario else scenario.get(plain_key, {})
            print(json.dumps(result))
    elif cmd == "query-orders":
        txid = argv[1] if len(argv) > 1 else ""
        key = f"query-orders_{txid}"
        print(json.dumps(scenario.get(key, {})))
    else:
        print("{}")


if __name__ == "__main__":
    main()
