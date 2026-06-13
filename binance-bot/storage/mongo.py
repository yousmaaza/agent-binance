"""Accès MongoDB : connexion lazy, lecture/écriture des cycles."""
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
