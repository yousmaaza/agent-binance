"""Accès MongoDB : connexion lazy, lecture/écriture des cycles."""
from datetime import datetime, timezone
from typing import Dict, List, Optional

from loguru import logger
from pymongo import MongoClient

from core.env import MONGO_DB, MONGO_URI
from models.cycle import CycleDocument


class MongoRepository:
    def __init__(self):
        self._client: Optional[MongoClient] = None

    def _db(self):
        if not MONGO_URI:
            return None
        if self._client is None:
            try:
                self._client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
                self._client.admin.command("ping")
                logger.info("MongoDB connecté")
            except Exception as e:
                logger.error(f"MongoDB connexion échouée : {e}")
                self._client = None
                return None
        return self._client[MONGO_DB]

    def _with_db(self, fn):
        """Helper pour exécuter une fonction avec la DB si disponible."""
        db = self._db()
        return fn(db) if db is not None else None

    def save_cycle(self, doc: CycleDocument) -> bool:
        db = self._db()
        if db is None:
            return False
        try:
            db.cycles.update_one(
                {"cycle_id": doc["cycle_id"]},
                {"$set": doc},
                upsert=True,
            )
            return True
        except Exception as e:
            logger.error(f"MongoDB save_cycle erreur : {e}")
            return False

    def find_last_cycle(self) -> Optional[Dict]:
        db = self._db()
        if db is None:
            return None
        try:
            return db.cycles.find_one(sort=[("started_at", -1)])
        except Exception as e:
            logger.error(f"MongoDB find_last_cycle erreur : {e}")
            return None

    def find_cycles_since(self, since: datetime) -> List[Dict]:
        """Cycles dont le timestamp est >= since — pour le résumé de cycles de l'analyse hebdo (#453)."""
        db = self._db()
        if db is None:
            return []
        try:
            return list(
                db.cycles.find(
                    {"timestamp": {"$gte": since.isoformat()}},
                    {"execution": 1, "executed": 1, "status": 1, "error_type": 1, "timestamp": 1},
                ),
            )
        except Exception as e:
            logger.error(f"MongoDB find_cycles_since erreur : {e}")
            return []

    def find_weekly_analysis(self, week_key: str) -> Optional[Dict]:
        """Document existant pour cette semaine ISO, ou None — clé d'idempotence de #453."""
        db = self._db()
        if db is None:
            return None
        try:
            return db.weekly_analysis.find_one({"_id": week_key})
        except Exception as e:
            logger.error(f"MongoDB find_weekly_analysis erreur : {e}")
            return None

    def save_weekly_analysis(self, doc: Dict) -> bool:
        db = self._db()
        if db is None:
            return False
        try:
            db.weekly_analysis.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
            return True
        except Exception as e:
            logger.error(f"MongoDB save_weekly_analysis erreur : {e}")
            return False

    def save_maker_pending_orders(self, orders: List[Dict]) -> bool:
        """Publication du maker watcher (#498) : `$set` ciblé sur `watchers.maker_pending_orders`
        + `watchers.maker_pending_updated_at`, jamais une reconstruction du document — le reste
        (`open_positions`, `financials`, ...) appartient à la Phase 7.

        Sans `upsert` (retour de review #498) : si `dashboard_state` n'existe pas encore (avant
        le premier passage de la Phase 7), il n'y a rien à enrichir — un document créé avec pour
        seul contenu ces deux champs serait amputé (`open_positions`/`financials`/`config`
        absents) sans que `DashboardStateMissing` ne se déclenche côté dashboard, puisque
        `find_one` ne renverrait plus `None`. La Phase 7 créera le document complet au premier
        cycle ; un `update_one` qui ne matche rien d'ici là est le comportement voulu."""
        db = self._db()
        if db is None:
            return False
        try:
            db.dashboard_state.update_one(
                {"_id": "current"},
                {"$set": {
                    "watchers.maker_pending_orders": orders,
                    "watchers.maker_pending_updated_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=False,
            )
            return True
        except Exception as e:
            logger.error(f"MongoDB save_maker_pending_orders erreur : {e}")
            return False

    def save_trade_history_slices(self, open_positions: List[Dict], closed_trades: List[Dict],
                                   financials: Dict) -> bool:
        """Publication des watchers qui modifient `trade_history` entre deux cycles (#500) :
        `core/maker_watcher.py` (remplissage, repli marché), `core/maker_exit_watcher.py`
        (clôture par sortie maker ou son repli marché), `core/tp_watcher.py` (clôture sur cible
        atteinte). `$set` ciblé sur ces trois clés + `watchers.trade_history_slices_updated_at`,
        jamais une reconstruction du document — le reste (`watchers.maker_pending_orders`,
        `config`, ...) appartient à la Phase 7 ou au maker watcher (#498).

        Sans `upsert`, même raisonnement que #498 : si `dashboard_state` n'existe pas encore
        (avant le premier passage de la Phase 7), un document créé avec pour seul contenu ces
        clés serait amputé (`config` absent, ...) sans que `DashboardStateMissing` ne se
        déclenche côté dashboard. La Phase 7 créera le document complet au premier cycle."""
        db = self._db()
        if db is None:
            return False
        try:
            db.dashboard_state.update_one(
                {"_id": "current"},
                {"$set": {
                    "open_positions": open_positions,
                    "closed_trades": closed_trades,
                    "financials": financials,
                    "watchers.trade_history_slices_updated_at": datetime.now(timezone.utc).isoformat(),
                }},
                upsert=False,
            )
            return True
        except Exception as e:
            logger.error(f"MongoDB save_trade_history_slices erreur : {e}")
            return False

    def get_api_costs(self, limit: int = 5) -> List[Dict]:
        db = self._db()
        if db is None:
            return []
        try:
            return list(
                db.cycles.find(
                    {"api_cost_usd": {"$exists": True, "$gt": 0}},
                    {"cycle_id": 1, "started_at": 1, "api_cost_usd": 1, "trigger": 1},
                    sort=[("api_cost_usd", -1)],
                ).limit(limit)
            )
        except Exception as e:
            logger.error(f"MongoDB get_api_costs erreur : {e}")
            return []


# Instance partagée (importée par les modules qui en ont besoin)
mongo_repo = MongoRepository()
