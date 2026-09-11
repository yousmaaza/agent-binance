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

La config par défaut du helper désactive la sortie maker (`maker_exit_enabled: False`) : tous les
tests écrits avant #390 décrivent le chemin SELL MARKET, qui reste le repli d'urgence. Les tests
du chemin maker passent explicitement `config={"maker_exit_enabled": True}`.

Helpers partagés : voir tests/fixtures/test_harness.py.
"""
import contextlib
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "binance-bot"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "tests"))

from fixtures import test_harness as harness  # noqa: E402 -- import après sys.path.insert, ordre volontaire

PHASE3_SIGNAL_SELL_PATH = os.path.join(PROJECT_DIR, "binance-bot", "core", "phases", "phase3_signal_sell.py")

# Capturé avant tout patch (#476 review) : permet à un test de simuler une panne subprocess ciblée
# (ex. TimeoutExpired) sur un seul appel binance() tout en délégant les autres au vrai subprocess.run
# routé vers le stub fake_kraken.py.
_REAL_SUBPROCESS_RUN = subprocess.run


def _run_phase3_signal_sell(sell_candidates, history_data, config=None, kraken_scenario=None, extra_patchers=None):
    """Exécute phase3_signal_sell.py. Retourne (output, mock_tg, mock_save, saved_history,
    mock_repose_tg)."""
    # Chemin historique par défaut (SELL MARKET) : la délégation au watcher de sortie maker se
    # teste explicitement, cf. TestSignalSellMakerExitHandoff (#390).
    cfg = config if config is not None else {"maker_exit_enabled": False}
    cycle_id = harness.new_cycle_id()
    in_path = f"/tmp/cycle_{cycle_id}_phase3_signal_sell_input.json"
    out_path = f"/tmp/cycle_{cycle_id}_phase3_signal_sell_output.json"
    scenario_path = harness.write_kraken_scenario(kraken_scenario)
    text = json.dumps(history_data)

    input_data = {"sell_candidates": sell_candidates, "config": cfg}
    with open(in_path, "w") as f:
        json.dump(input_data, f)

    old_env = harness.set_fake_kraken_env(scenario_path)
    try:
        with contextlib.ExitStack() as stack:
            mock_tg = stack.enter_context(patch("core.trade_helpers.tg"))
            mock_save = stack.enter_context(patch("core.trade_helpers._save_trade_history_atomic"))
            stack.enter_context(patch("core.trade_helpers._load_config", return_value=cfg))
            stack.enter_context(patch("core.trade_helpers._EXCHANGE_CLI", harness.FAKE_KRAKEN_PATH))
            stack.enter_context(patch("builtins.open", side_effect=harness.fake_open_factory(text)))
            mock_repose_tg = stack.enter_context(patch("core.maker_exit_watcher.send_telegram"))
            stack.enter_context(patch("time.sleep"))
            for patcher in (extra_patchers or []):
                stack.enter_context(patcher)

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
    comme le ferait un vrai solde nul. Un alias manquant signale un défaut de code (table
    incomplète) -- il doit être visible via une alerte Telegram explicite, distincte de la
    notification de vente (#476 review)."""

    def test_missing_asset_key_sells_using_trade_qty_and_alerts(self):
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
        alert_calls = [c.args[0] for c in mock_tg.call_args_list if "alias manquant" in c.args[0]]
        self.assertEqual(len(alert_calls), 1)
        self.assertIn("WIF", alert_calls[0])


class TestSignalSellKrakenApiFailureFallsBackSilently(unittest.TestCase):
    """Panne réelle de l'appel `kraken balance` (réseau, CLI) -> même repli sur trade_qty que pour
    un alias manquant, mais sans alerte : c'est un aléa réseau, pas un défaut de code (#476
    review) -- distinct du cas ci-dessus où l'alerte "alias manquant" doit être envoyée."""

    def test_balance_call_failure_sells_using_trade_qty_without_alert(self):
        history_data = [
            {"trade_id": "T13", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance_fail": True,
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_market": {"txid": ["SELLTX14"]},
            "query-orders_SELLTX14": {"SELLTX14": {"status": "closed", "cost": "900.0", "vol_exec": "1.0", "fee": "0.6"}},
        }
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 2}], history_data, kraken_scenario=kraken_scenario,
        )

        self.assertEqual(output["closed"], 1)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "closed")
        alert_calls = [c.args[0] for c in mock_tg.call_args_list if "alias manquant" in c.args[0]]
        self.assertEqual(len(alert_calls), 0)


class TestSignalSellUnlistedExceptionDuringMarketSellReprotects(unittest.TestCase):
    """#476 review : une exception non explicitement listée (subprocess.TimeoutExpired) levée par
    l'appel SELL MARKET (Step 3, après annulation du stop) doit déclencher la reprotection comme
    tout autre échec de vente -- pas faire planter le script en laissant la position sans stop.
    Garde-fou contre un typage d'exception trop étroit sur ce chemin (constaté sur un commit bot
    concurrent ayant remplacé `except Exception` par des types précis qui n'incluaient pas
    TimeoutExpired ni OSError, #476 review)."""

    def test_market_sell_timeout_reprotects_instead_of_crashing(self):
        history_data = [
            {"trade_id": "T14", "coin": "ETH", "status": "open", "entry_price": 1000.0,
             "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0,
             "sl_order_txid": "SLTX0"},
        ]
        kraken_scenario = {
            "balance": {"XETH": "1.0"},
            "pairs": {"ETHUSDC": {"lot_decimals": 8}},
            "order_sell_ETHUSDC_stop-loss": {"txid": ["NEWSLTX15"]},
        }

        def _fake_run(cmd, *args, **kwargs):
            if "sell" in cmd and "market" in cmd:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)
            return _REAL_SUBPROCESS_RUN(cmd, *args, **kwargs)

        extra_patchers = [patch("core.trade_helpers.subprocess.run", side_effect=_fake_run)]
        output, mock_tg, mock_save, saved_history, mock_repose_tg = _run_phase3_signal_sell(
            [{"coin": "ETH", "score": 1}], history_data, kraken_scenario=kraken_scenario,
            extra_patchers=extra_patchers,
        )

        self.assertEqual(output["closed"], 0)
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX15")
        self.assertFalse(pos["protection_failed"])
        mock_tg.assert_called()
        mock_repose_tg.assert_called()


def _maker_exit_patchers(already_pending=None):
    """Patche l'état persistant des sorties maker (state/maker_exit_pending_orders.json) : les
    tests ne doivent jamais lire ni écrire le vrai fichier. Retourne (patchers, mock_save)."""
    mock_save = MagicMock()
    patchers = [
        patch("core.maker_exit_watcher.load_maker_exit_pending_orders",
              return_value=list(already_pending or [])),
        patch("core.maker_exit_watcher.save_maker_exit_pending_orders", mock_save),
    ]
    return patchers, mock_save


_MAKER_HISTORY = [
    {"trade_id": "T20", "coin": "ETH", "status": "open", "entry_price": 1000.0,
     "quantity": 1.0, "entry_fee_usdc": 0.5, "stop_price": 950.0, "sl_order_txid": "SLTX0"},
]
_MAKER_SCENARIO = {
    "balance": {"XETH": "1.0"},
    "pairs": {"ETHUSDC": {"lot_decimals": 8}},
    "ticker": {"ETHUSDC": {"a": ["1100.5", "0.01"], "c": ["1100.0", "0.01"]}},
    "order_sell_ETHUSDC_limit": {"txid": ["LIMITTX20"]},
}


class TestSignalSellMakerExitHandoff(unittest.TestCase):
    """#390 étendu à la vente sur signal : un score retombé n'est pas une urgence (contrairement à
    un stop touché), la vente part donc en LIMIT post-only suivie par core/maker_exit_watcher.py
    plutôt qu'en SELL MARKET. Le trade n'est pas clôturé par ce script — le watcher s'en charge."""

    def _run(self, history=None, scenario=None, already_pending=None, candidates=None):
        patchers, mock_save_pending = _maker_exit_patchers(already_pending)
        output, mock_tg, mock_save, saved_history, _mock_repose_tg = _run_phase3_signal_sell(
            candidates or [{"coin": "ETH", "score": 2}],
            json.loads(json.dumps(history if history is not None else _MAKER_HISTORY)),
            config={"maker_exit_enabled": True},
            kraken_scenario=scenario or _MAKER_SCENARIO,
            extra_patchers=patchers,
        )
        return output, mock_tg, mock_save, saved_history, mock_save_pending

    def test_sale_is_delegated_to_the_maker_exit_watcher_not_sold_at_market(self):
        output, _tg, _save, saved_history, mock_save_pending = self._run()

        # Pas de clôture ici : la limite est vivante, le watcher la suivra.
        self.assertEqual(output["closed"], 0)
        self.assertEqual(output["maker_pending"], 1)
        self.assertEqual(saved_history[0]["status"], "open")

        mock_save_pending.assert_called_once()
        pending = mock_save_pending.call_args[0][0]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["trade_id"], "T20")
        self.assertEqual(pending[0]["txid"], "LIMITTX20")
        # Le motif de la vente survit à la délégation : c'est lui qui alimente /perf et Mongo.
        self.assertEqual(pending[0]["close_reason"], "signal_sell_score2")
        self.assertEqual(pending[0]["stop_price"], 950.0)
        self.assertIsNotNone(pending[0]["cycle_id"])
        # Vente posée au meilleur vendeur (ask), pas au dernier prix.
        self.assertAlmostEqual(pending[0]["initial_limit_price"], 1100.5)

    def test_cancelled_stop_txid_is_purged_so_the_watcher_never_cancels_it_twice(self):
        """Le stop est annulé par ce script (Step 1) ; laisser son txid dans l'historique ferait
        échouer la seconde annulation tentée par attempt_maker_exit() — la position resterait
        alors à la fois nue et non vendue."""
        _output, _tg, mock_save, saved_history, _pending = self._run()

        mock_save.assert_called()
        self.assertIsNone(saved_history[0]["sl_order_txid"])

    def test_telegram_notification_keeps_the_score_that_triggered_the_sale(self):
        _output, mock_tg, _save, _history, _pending = self._run()

        messages = [c.args[0] for c in mock_tg.call_args_list if c.args]
        self.assertTrue(any("score 2/10" in m and "LIMIT SELL post-only" in m for m in messages),
                        f"notification sans le motif de la vente : {messages}")

    def test_order_volume_is_truncated_to_the_pair_step_not_the_raw_position(self):
        """La quantité posée en limite passe par le même plafonnement solde/pas de paire que la
        vente au marché (#472) — une quantité brute de trade_history produit un
        EOrder:Insufficient funds, sur une limite comme sur un ordre au marché."""
        history = [
            {"trade_id": "T21", "coin": "ADA", "status": "open", "entry_price": 1.0,
             "quantity": 10.004, "entry_fee_usdc": 0.0, "stop_price": 0.9, "sl_order_txid": "SLTX0"},
        ]
        scenario = {
            "balance": {"ADA": "10.004"},
            "pairs": {"ADAUSDC": {"lot_decimals": 2}},  # pas de 0.01 -> 10.004 tronqué à 10.00
            "ticker": {"ADAUSDC": {"a": ["1.05", "10"], "c": ["1.04", "10"]}},
            "order_sell_ADAUSDC_limit": {"txid": ["LIMITTX21"]},
        }
        output, _tg, _save, _history, mock_save_pending = self._run(
            history=history, scenario=scenario, candidates=[{"coin": "ADA", "score": 1}],
        )

        self.assertEqual(output["maker_pending"], 1)
        self.assertAlmostEqual(mock_save_pending.call_args[0][0][0]["quantity"], 10.0)

    def test_significant_balance_shortfall_falls_back_to_the_market_path(self):
        """Le watcher clôture le trade entier dès que sa limite est remplie : il n'a aucune notion
        de vente partielle. Quand le solde réel ne couvre qu'une fraction de la position, la vente
        reste donc sur le chemin marché, seul à mesurer le reliquat contre la position et à le
        reprotéger (#472 review)."""
        history = [
            {"trade_id": "T22", "coin": "XRP", "status": "open", "entry_price": 0.50,
             "quantity": 100.0, "entry_fee_usdc": 0.05, "stop_price": 0.45, "sl_order_txid": "SLTX0"},
        ]
        scenario = {
            "balance": {"XXRP": "60.0"},  # 40 XRP manquants : très au-dessus du pas de la paire
            "pairs": {"XRPUSDC": {"lot_decimals": 1, "ordermin": "1"}},
            "ticker": {"XRPUSDC": {"a": ["0.60", "100"], "c": ["0.60", "100"]}},
            "order_sell_XRPUSDC_market": {"txid": ["SELLTX22"]},
            "query-orders_SELLTX22": {"SELLTX22": {"status": "closed", "cost": "36.0", "vol_exec": "60.0", "fee": "0.06"}},
            "order_sell_XRPUSDC_stop-loss": {"txid": ["NEWSLTX22"]},
        }
        output, _tg, _save, saved_history, mock_save_pending = self._run(
            history=history, scenario=scenario, candidates=[{"coin": "XRP", "score": 2}],
        )

        mock_save_pending.assert_not_called()
        self.assertEqual(output["maker_pending"], 0)
        self.assertEqual(output["closed"], 0)
        # Chemin marché : le reliquat de 40 XRP est reprotégé, la position n'est pas clôturée.
        self.assertEqual(saved_history[0]["status"], "open")
        self.assertEqual(saved_history[0]["sl_order_txid"], "NEWSLTX22")

    def test_position_already_chasing_a_maker_exit_is_not_sold_a_second_time(self):
        """Son stop est déjà annulé et son volume déjà engagé dans une limite vivante : une
        seconde vente partirait en Insufficient funds."""
        already = [{"trade_id": "T20", "coin": "ETH", "pair": "ETHUSDC", "txid": "LIMITTX_OLD"}]
        output, _tg, mock_save, _history, mock_save_pending = self._run(already_pending=already)

        self.assertEqual(output["closed"], 0)
        self.assertEqual(output["maker_pending"], 0)
        mock_save_pending.assert_not_called()
        mock_save.assert_not_called()

    def test_limit_placement_failure_reposes_the_stop_instead_of_leaving_the_position_naked(self):
        """Le stop a déjà été annulé quand la pose de la limite échoue : la position doit être
        reprotégée immédiatement, jamais laissée à la fois nue et non vendue."""
        scenario = dict(_MAKER_SCENARIO)
        scenario["order_sell_ETHUSDC_limit"] = {}  # pas de txid -> pose refusée
        scenario["order_sell_ETHUSDC_stop-loss"] = {"txid": ["NEWSLTX20"]}
        output, _tg, mock_save, saved_history, mock_save_pending = self._run(scenario=scenario)

        self.assertEqual(output["maker_pending"], 0)
        mock_save_pending.assert_not_called()
        mock_save.assert_called()
        pos = saved_history[0]
        self.assertEqual(pos["status"], "open")
        self.assertEqual(pos["sl_order_txid"], "NEWSLTX20")
        self.assertFalse(pos["protection_failed"])


if __name__ == "__main__":
    unittest.main()
