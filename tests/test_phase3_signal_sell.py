"""Tests d'intégration pour phase3_signal_sell.py — vente sur signal (sell_candidates, score <=
3), mise sous contrat de #472 : ce chemin n'était écrit nulle part et produisait plus de sorties
que le TP watcher, sans le moindre test.

Même approche que test_phase0_profit.py / test_phase4_sizing.py : trade_history.json intercepté
via patch de builtins.open ciblé, _save_trade_history_atomic/_load_config mockés, tg() mockée,
binance() redirigée vers le stub fake_kraken.py (core.trade_helpers._EXCHANGE_CLI).

La réintégration en cas d'échec (fill introuvable, SELL raté, remplissage partiel) passe par
core.maker_exit_watcher._repose_stop_and_alert() — le réutiliser plutôt que d'inventer une
politique nouvelle est précisément l'objet du ticket #472, donc il n'est pas mocké ici : ses
appels Kraken transitent par le même stub fake_kraken.py que le reste du script, et sa notification
(core.maker_exit_watcher.send_telegram) est mockée séparément de tg() (core.trade_helpers.tg).

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import json
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import (
    test_harness as harness,
)

PHASE3_SIGNAL_SELL_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase3_signal_sell.py")


def _run_phase3_signal_sell(sell_candidates, history_data, config=None, kraken_scenario=None):
    """Exécute phase3_signal_sell.py. Retourne (output, mock_tg, mock_save, saved_history,
    mock_repose_tg)."""
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase3_signal_sell_input.json"
    out_path = f"/tmp/cycle_{cycle_id}_phase3_signal_sell_output.json"
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    text = json.dumps(history_data)

    input_data = {"sell_candidates": sell_candidates, "config": config or {}}
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=config or {}))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))
            mock_repose_tg = stack.enter_context(patch("core.maker_exit_watcher.send_telegram"))
            stack.enter_context(patch("time.sleep"))

            harness.exec_phase_script(PHASE3_SIGNAL_SELL_PATH, cycle_id)

        output = harness.load_and_remove_json(out_path)
        saved_history = mock_save.call_args[0][0] if mock_save.call_args else None
        return output, mock_tg, mock_save, saved_history, mock_repose_tg
    finally:
        harness.restore_fake_kraken_env(old_env)
        harness.remove_if_exists(in_path, out_path, scenario_path)


class TestSignalSellNominalWithActiveStop(unittest.TestCase):
    """Cas nominal : candidat avec stop actif -> annulation, vente, trade clôturé avec le bon
    close_reason, le bon PnL net et le cycle_id (#472)."""

    def test_active_stop_is_cancelled_and_trade_closed_with_net_pnl(self):
        history_data = [
            {"trade_id": "T1", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        # Clé de solde réelle Kraken (préfixée, #476) — pas la clé brute "ETH".
        kraken_scenario = {
            "balance": {"XETH": "1.0"},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_market": {"txid": ["SELLTX1"]},
            "query-orders_SELLTX1": {"SELLTX1": {"status": "closed", "cost": "900.0", "vol_exec": "1.0", "fee": "0.6"}},
        }
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 2}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        mock_save.assert_called()
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "signal_sell_score2")
        self.assertAlmostEqual(pos["exit_price"], 900.0)
        # pnl_gross = (900-1000)*1 = -100 ; fees = 0.5+0.6 = 1.1 ; pnl net = -101.1
        self.assertAlmostEqual(pos["pnl_gross_usdc"], -100.0)
        self.assertAlmostEqual(pos["fees_usdc"], 1.1)
        self.assertAlmostEqual(pos["pnl_usdc"], -101.1)
        self.assertIsNotNone(pos["cycle_id"])
        mock_tg.assert_called()


class TestSignalSellWithoutActiveStop(unittest.TestCase):
    """Candidat sans stop actif (sl_order_txid=None) : pas d'annulation tentée, vente normale —
    c'est 11 des 25 ventes réelles (#472)."""

    def test_no_cancel_attempted_sale_proceeds_normally(self):
        history_data = [
            {"trade_id": "T2", "coin": "XRP", "status": "open", "entry_price": 0.5,
             "quantity": 100.0, "entry_fee_usdc": 0.1, "stop_price": 0.45,
             "sl_order_txid": None},
        ]
        kraken_scenario = {
            "balance": {"XXRP": "100.0"},
            "pairs": {"XRPUSDC": {"lot_decimals": 1}},
            "order_sell_XRPUSDC_market": {"txid": ["SELLTX2"]},
            "query-orders_SELLTX2": {"SELLTX2": {"status": "closed", "cost": "48.0", "vol_exec": "100.0"}},
        }
        output, _mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "XRP", "score": 1}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        self.assertEqual(pos["close_reason"], "signal_sell_score1")
        self.assertIsNone(pos["sl_order_txid"])
        mock_save.assert_called()


class TestSignalSellNoOpenTradeForCoin(unittest.TestCase):
    """Aucun trade "open" pour le coin -> passer sans rien casser."""

    def test_missing_open_trade_is_skipped_silently(self):
        history_data = [
            {"trade_id": "T3", "coin": "SOL", "status": "closed", "entry_price": 100.0, "quantity": 1.0},
        ]
        output, mock_tg, mock_save, _saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "DOGE", "score": 2}], history_data, kraken_scenario={},
        )

        self.assertEqual(output["closed"], 0)
        mock_save.assert_not_called()
        mock_tg.assert_not_called()


class TestSignalSellFillNotFoundNeverFabricatesPrice(unittest.TestCase):
    """Fill introuvable après 3 tentatives -> jamais de prix fabriqué (#469) : le trade n'est pas
    clôturé silencieusement, exit_price ne vaut jamais entry_price, la position est reprotégée."""

    def test_unconfirmed_fill_reprotects_position_without_closing(self):
        history_data = [
            {"trade_id": "T4", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"XETH": "1.0"},
            "pairs": {"ETHUSDC": {"lot_decimals": 8, "tick_size": "0.01"}},
            "order_sell_ETHUSDC_market": {"txid": ["SELLTX3"]},
            # Pas de clé query-orders_SELLTX3 -> vol_exec toujours 0 sur les 3 tentatives
            "order_sell_ETHUSDC_stop-loss": {"txid": ["NEWSLTX4"]},
        }
        output, mock_tg, mock_save, saved_history, mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 1}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertNotEqual(pos.get("exit_price"), 1000.0)
        self.assertIsNone(pos.get("exit_price"))
        # Reprotection réussie via _repose_stop_and_alert (core/maker_exit_watcher.py)
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX4")
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called()
        mock_repose_tg.assert_called()


class TestSignalSellMarketOrderFailureReprotectsPosition(unittest.TestCase):
    """SELL en échec après annulation du stop -> la position est reprotégée, jamais laissée nue
    (#472, réutilisation de core.maker_exit_watcher._repose_stop_and_alert)."""

    def test_failed_sell_after_cancel_reprotects_instead_of_leaving_naked(self):
        history_data = [
            {"trade_id": "T5", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"XETH": "1.0"},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            # Pas de clé order_sell_ETHUSDC_market (ni de fallback order_sell_ETHUSDC) -> pas de txid
            "order_sell_ETHUSDC_stop-loss": {"txid": ["NEWSLTX5"]},
        }
        output, mock_tg, mock_save, saved_history, mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 2}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX5")
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called()
        mock_repose_tg.assert_called()


class TestSignalSellPartialFillKeepsRemainderTracked(unittest.TestCase):
    """Remplissage partiel -> le reliquat reste une position suivie et protégée, pas de trade
    clôturé sur une quantité qui n'a pas été réellement vendue (#472)."""

    def test_partial_fill_reprotects_remainder_without_closing(self):
        history_data = [
            {"trade_id": "T6", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"XETH": "1.0"},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_market": {"txid": ["SELLTX6"]},
            "query-orders_SELLTX6": {"SELLTX6": {"status": "open", "cost": "600.0", "vol_exec": "0.6"}},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["NEWSLTX6"]},
        }
        output, mock_tg, mock_save, saved_history, mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 2}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["quantity"], 1.0)
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX6")
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called()
        mock_repose_tg.assert_called()


class TestSignalSellBalanceShortfallIsMeasuredAgainstPosition(unittest.TestCase):
    """Review PR #475 : le solde réel plafonne la taille de l'ORDRE (sell_qty), pas la taille de
    la POSITION (trade_qty) — un ordre intégralement rempli à sell_qty peut donc ne représenter
    qu'une fraction de la position réellement détenue. Le reliquat doit être mesuré contre
    trade_qty, sinon la partie non vendue de la position disparaît silencieusement et le PnL est
    calculé sur une quantité jamais vendue.

    Position de 100 XRP entrée à 0.50, solde réel 60, ordre de 60 intégralement rempli à 0.60 :
    avec le mauvais dénominateur (sell_qty), remaining_qty vaut 0 -> le trade se clôturait pour
    100 XRP avec un PnL gonflé de 67% pendant que 40 XRP restaient sans stop. Avec le bon
    dénominateur (trade_qty), remaining_qty vaut 40 -> reconnu comme un remplissage partiel
    significatif, la position n'est pas clôturée et le reliquat de 40 XRP est reprotégé."""

    def test_full_order_fill_below_real_balance_is_treated_as_significant_partial(self):
        history_data = [
            {"trade_id": "T7", "coin": "XRP", "status": "open", "entry_price": 0.50,
             "quantity": 100.0, "entry_fee_usdc": 0.05, "stop_price": 0.45,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"XXRP": "60.0"},
            "pairs": {"XRPUSDC": {"lot_decimals": 1, "ordermin": "1"}},
            "order_sell_XRPUSDC_market": {"txid": ["SELLTX8"]},
            # Ordre de 60 (plafonné par le solde réel) intégralement rempli.
            "query-orders_SELLTX8": {"SELLTX8": {"status": "closed", "cost": "36.0", "vol_exec": "60.0", "fee": "0.06"}},
            "order_sell_XRPUSDC_stop-loss": {"txid": ["NEWSLTX8"]},
        }
        output, mock_tg, mock_save, saved_history, mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "XRP", "score": 2}], history_data, kraken_scenario=kraken_scenario,
        )

        # Ne se clôture pas : 40 XRP de la position n'ont jamais été vendus.
        self.assertEqual(output["closed"], 0)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertIsNone(pos.get("pnl_usdc"))
        self.assertIsNone(pos.get("exit_price"))
        # Le reliquat (100 - 60 = 40 XRP) est reprotégé, pas laissé nu ni oublié.
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX8")
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called()
        mock_repose_tg.assert_called()


class TestSignalSellPnlUsesActuallySoldQuantity(unittest.TestCase):
    """Review PR #475 : quand la position se clôture réellement, le PnL et la quantité enregistrée
    portent sur vol_exec (ce qui a été réellement vendu), jamais sur trade_qty — la troncature au
    pas de la paire (Step 2) rend systématiquement sell_qty (et donc vol_exec) un peu inférieur à
    trade_qty ; ce reliquat est en-dessous du pas de la paire (non vendable, non protégeable), donc
    absorbé silencieusement, mais le PnL enregistré ne doit jamais gonfler la quantité vendue."""

    def test_closed_trade_records_pnl_and_quantity_on_vol_exec_not_trade_qty(self):
        history_data = [
            {"trade_id": "T8", "coin": "ADA", "status": "open", "entry_price": 1.0,
             "quantity": 10.004, "entry_fee_usdc": 0.0, "stop_price": 0.9,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"ADA": "10.004"},
            # lot_decimals=2 -> pas de 0.01 : sell_qty tronqué à 10.00 (perd le résidu 0.004,
            # inférieur au pas -> non significatif).
            "pairs": {"ADAUSDC": {"lot_decimals": 2}},
            "order_sell_ADAUSDC_market": {"txid": ["SELLTX9"]},
            "query-orders_SELLTX9": {"SELLTX9": {"status": "closed", "cost": "10.5", "vol_exec": "10.0", "fee": "0.0"}},
        }
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ADA", "score": 3}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        # quantity enregistrée = vol_exec réellement vendu (10.0), pas trade_qty (10.004).
        self.assertEqual(pos["quantity"], 10.0)
        # pnl_gross = (1.05 - 1.0) * 10.0 = 0.5 (et non (1.05-1.0)*10.004 = 0.5002).
        self.assertAlmostEqual(pos["pnl_gross_usdc"], 0.5)
        mock_tg.assert_called()


class TestSignalSellRealProductionBalanceDict(unittest.TestCase):
    """#476 : le solde `kraken balance` réel mêle actifs préfixés (XETH, XXBT, XXRP, XXDG) et non
    préfixés (SOL, ADA, LINK, BNB, TRUMP) dans le même dict — utiliser ce dict tel quel, pas une
    version simplifiée qui masque le bug. Solde issu du cycle 20260907_040506 (issue #476)."""

    _REAL_BALANCE = {
        "ADA": "0.06652239", "BNB": "0.00001642", "LINK": "0.0000000000",
        "SOL": "0.0009199479", "TRUMP": "0.000010", "USDC": "101.18877489",
        "XETH": "0.0754454797", "XXBT": "0.0001572488",
        "XXDG": "591.21753490", "XXRP": "72.61162160",
    }

    def test_prefixed_asset_xrp_is_sold(self):
        history_data = [
            {"trade_id": "T9", "coin": "XRP", "status": "open", "entry_price": 3.0,
             "quantity": 72.6, "entry_fee_usdc": 0.1, "stop_price": 2.7,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": self._REAL_BALANCE,
            "pairs": {"XRPUSDC": {"lot_decimals": 1}},
            "order_sell_XRPUSDC_market": {"txid": ["SELLTX10"]},
            "query-orders_SELLTX10": {"SELLTX10": {"status": "closed", "cost": "217.8", "vol_exec": "72.6", "fee": "0.1"}},
        }
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "XRP", "score": 1}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        mock_tg.assert_called()

    def test_non_prefixed_asset_sol_is_sold(self):
        history_data = [
            {"trade_id": "T10", "coin": "SOL", "status": "open", "entry_price": 150.0,
             "quantity": 0.0009199479, "entry_fee_usdc": 0.01, "stop_price": 140.0,
             "sl_order_txid": "SLTX1"},
        ]
        kraken_scenario = {
            "balance": self._REAL_BALANCE,
            "pairs": {"SOLUSDC": {"lot_decimals": 8}},
            "order_sell_SOLUSDC_market": {"txid": ["SELLTX11"]},
            "query-orders_SELLTX11": {"SELLTX11": {"status": "closed", "cost": "0.138", "vol_exec": "0.0009199479", "fee": "0.0001"}},
        }
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "SOL", "score": 2}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        mock_tg.assert_called()


class TestSignalSellRealZeroBalanceStillReprotects(unittest.TestCase):
    """Solde réellement nul pour un actif préfixé (clé XETH présente, valeur "0.0") -> reste
    distinct d'une clé introuvable : la vente est bloquée et la position reprotégée, comme avant
    #476 (non-régression de la branche « solde disponible nul »)."""

    def test_zero_balance_for_prefixed_asset_reprotects(self):
        history_data = [
            {"trade_id": "T11", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"XETH": "0.0"},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["NEWSLTX12"]},
        }
        output, mock_tg, mock_save, saved_history, mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 1}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 0)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX12")
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called()
        mock_repose_tg.assert_called()


class TestSignalSellUnresolvableAssetFallsBackToTradeQtyNotZero(unittest.TestCase):
    """Actif introuvable dans le solde (ni clé brute, ni alias connu) -> ne doit jamais être
    confondu avec un solde réellement nul (#476) : kraken_coin_balance lève KeyError, et le script
    retombe sur trade_qty comme pour un échec Kraken, au lieu de bloquer la vente et reprotéger
    comme le ferait un vrai solde nul."""

    def test_missing_asset_key_sells_using_trade_qty(self):
        history_data = [
            {"trade_id": "T12", "coin": "WIF", "status": "open", "entry_price": 2.0,
             "quantity": 50.0, "entry_fee_usdc": 0.1, "stop_price": 1.8,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            # WIF absent du solde (ni "WIF" ni alias connu) — #476 exige que ça ne soit pas traité
            # comme un solde nul.
            "balance": {"USDC": "500.0"},
            "pairs": {"WIFUSDC": {"lot_decimals": 1}},
            "order_sell_WIFUSDC_market": {"txid": ["SELLTX13"]},
            "query-orders_SELLTX13": {"SELLTX13": {"status": "closed", "cost": "100.0", "vol_exec": "50.0", "fee": "0.1"}},
        }
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "WIF", "score": 1}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        mock_tg.assert_called()


if __name__ == "__main__":
    unittest.main()
