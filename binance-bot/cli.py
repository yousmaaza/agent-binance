#!/usr/bin/env python3
"""CLI du bot Binance — appelle les commandes sans passer par Telegram."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.env  # noqa: F401  — bootstrap loguru + .env + prompt

from commands.cout import run_cout
from commands.perf import run_perf
from commands.raisonnement import run_raisonnement
from commands.status import run_status
from orchestration.runner import run_trade_workflow


def main():
    parser = argparse.ArgumentParser(description="Binance bot — CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Affiche le portefeuille et les ordres ouverts")
    sub.add_parser("perf", help="Statistiques de performance des trades fermés")
    sub.add_parser("raisonnement", help="Explication du dernier cycle (MongoDB)")
    sub.add_parser("cout", help="Coût API cumulé par cycle")
    trade_p = sub.add_parser("trade", help="Lance un cycle de trading maintenant")
    trade_p.add_argument("--trigger", default="manual", choices=["manual", "auto"])

    args = parser.parse_args()

    if args.cmd == "status":
        print(run_status())
    elif args.cmd == "perf":
        print(run_perf())
    elif args.cmd == "raisonnement":
        print(run_raisonnement())
    elif args.cmd == "cout":
        print(run_cout())
    elif args.cmd == "trade":
        run_trade_workflow(trigger=args.trigger)


if __name__ == "__main__":
    main()
