"""Prix courants via l'API publique Kraken — appel direct, aucun connecteur tiers (#432).

Contrairement à une page publiée en artifact, un serveur Railway n'a aucune restriction d'appel
réseau : on interroge directement https://api.kraken.com/0/public/Ticker (public, sans auth)."""
import json
import urllib.error
import urllib.request

import settings
from cache import cache

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"


class KrakenUnavailable(Exception):
    pass


def _fetch_tickers(pairs: tuple) -> dict:
    """Un seul appel groupé pour tous les coins en position ouverte (#432 : limiter les
    sollicitations de l'API publique). Retourne {coin: last_price or None}."""
    if not pairs:
        return {}
    pair_param = ",".join(f"{coin}USDC" for coin in pairs)
    url = f"{KRAKEN_TICKER_URL}?pair={pair_param}"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:  # nosec B310 -- URL fixe (api.kraken.com), jamais dérivée d'une entrée utilisateur
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise KrakenUnavailable(str(e)) from e

    if payload.get("error"):
        raise KrakenUnavailable(", ".join(payload["error"]))

    result = payload.get("result", {})
    prices: dict = {}
    for coin in pairs:
        wanted = f"{coin}USDC"
        entry = result.get(wanted)
        if entry is None:
            # Kraken peut renommer certaines paires legacy dans sa réponse (ex. préfixe X/Z) —
            # repli par correspondance partielle plutôt que de perdre le prix.
            entry = next((v for k, v in result.items() if coin in k), None)
        prices[coin] = float(entry["c"][0]) if entry else None
    return prices


def get_prices(coins: list) -> dict:
    key = f"kraken:{','.join(sorted(coins))}"
    return cache.get_or_set(key, settings.KRAKEN_CACHE_TTL_S, lambda: _fetch_tickers(tuple(coins)))
