"""Lecture seule de MongoDB Atlas (#432) — jamais d'écriture, jamais de fichier state/ du bot.

Deux erreurs distinctes exposées à la vue pour des messages dégradés précis (cf. ticket #432) :
- MongoUnavailable : connexion/requête impossible (réseau, IP non whitelistée, credentials).
- DashboardStateMissing : connexion OK mais le document dashboard_state n'existe pas encore
  (premier déploiement avant le premier cycle post-#431)."""
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError

import settings
from cache import cache


class MongoUnavailable(Exception):
    pass


class DashboardStateMissing(Exception):
    pass


_client: Optional[MongoClient] = None


def _get_client() -> MongoClient:
    global _client
    if _client is None:
        if not settings.MONGODB_URI:
            raise MongoUnavailable("MONGODB_URI absent — configure la variable d'environnement sur Railway.")
        _client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
    return _client


def _db():
    try:
        client = _get_client()
        return client[settings.MONGODB_DB]
    except PyMongoError as e:
        raise MongoUnavailable(str(e)) from e


def _fetch_dashboard_state() -> dict:
    db = _db()
    try:
        doc = db.dashboard_state.find_one({"_id": "current"})
    except PyMongoError as e:
        raise MongoUnavailable(str(e)) from e
    if doc is None:
        raise DashboardStateMissing("Aucun document dashboard_state — le bot n'a pas encore terminé de cycle depuis #431.")
    return doc


def get_dashboard_state() -> dict:
    """Cache TTL : évite une lecture Mongo à chaque rafraîchissement de page (#432)."""
    return cache.get_or_set("dashboard_state", settings.DASHBOARD_STATE_CACHE_TTL_S, _fetch_dashboard_state)


def _fetch_recent_cycles(limit: int) -> list:
    db = _db()
    try:
        return list(
            db.cycles.find({}, sort=[("timestamp", -1)]).limit(limit),
        )
    except PyMongoError as e:
        raise MongoUnavailable(str(e)) from e


def get_recent_cycles(limit: int) -> list:
    return cache.get_or_set(f"cycles:{limit}", settings.CYCLES_CACHE_TTL_S, lambda: _fetch_recent_cycles(limit))


# La grille couvre 30 jours, soit ~180 cycles : on n'en lit que l'ossature, sans les décisions
# ni l'explication rédigée, qui pèsent l'essentiel du document (#450).
_GRID_PROJECTION = {
    "cycle_id": 1, "timestamp": 1, "status": 1, "error_type": 1, "trigger": 1,
    "top_score": 1, "execution": 1, "executed": 1, "pending": 1,
    "duration_s": 1, "duration_seconds": 1, "api_cost_usd": 1,
}


def _fetch_cycles_for_grid(limit: int) -> list:
    db = _db()
    try:
        return list(db.cycles.find({}, _GRID_PROJECTION, sort=[("timestamp", -1)]).limit(limit))
    except PyMongoError as e:
        raise MongoUnavailable(str(e)) from e


def get_cycles_for_grid(limit: int) -> list:
    return cache.get_or_set(f"grid:{limit}", settings.CYCLES_CACHE_TTL_S, lambda: _fetch_cycles_for_grid(limit))


def _fetch_latest_weekly_analysis() -> Optional[dict]:
    db = _db()
    try:
        return db.weekly_analysis.find_one(sort=[("generated_at", -1)])
    except PyMongoError as e:
        raise MongoUnavailable(str(e)) from e


def get_latest_weekly_analysis() -> Optional[dict]:
    """Analyse hebdomadaire rédigée la plus récente (#453), ou None si jamais générée."""
    return cache.get_or_set(
        "weekly_analysis:latest", settings.DASHBOARD_STATE_CACHE_TTL_S, _fetch_latest_weekly_analysis,
    )
