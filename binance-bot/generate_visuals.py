#!/usr/bin/env python3
"""
Génère des visuels Napkin AI depuis la documentation du projet agent-binance.

Usage :
  python scripts/generate_visuals.py --list
  python scripts/generate_visuals.py --section architecture
  python scripts/generate_visuals.py --all
  python scripts/generate_visuals.py --all --format png

Prérequis : NAPKIN_API_TOKEN dans .env
"""
import os
import sys
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
VISUALS_DIR = PROJECT_DIR / "docs" / "visuals"
NAPKIN_API_BASE = "https://api.napkin.ai/v1"

# ---------------------------------------------------------------------------
# Textes envoyés à Napkin — chaque entrée produit UN visuel
# La clé devient le nom du fichier de sortie (ex: architecture.svg)
# ---------------------------------------------------------------------------
VISUALS: dict[str, dict] = {
    "architecture": {
        "title": "Architecture système — agent-binance",
        "text": """
Agent-binance est un bot de trading Binance piloté par Telegram.
Il tourne comme un unique processus Python en polling-only (aucun port entrant).

Composants principaux :
- webhook_server.py : process principal. Poll Telegram toutes les 30s.
- Auto-scheduler : déclenche automatiquement un cycle de trading toutes les 4h
  aux slots alignés sur TradingView (00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC)
- Claude CLI : sous-processus lancé à chaque cycle, orchestre l'analyse en 7 phases
- Binance CLI : exécute les ordres spot (OTOCO : entrée limite + TP + SL)
- TradingView MCP : données marché en temps réel (gainers, breakouts, analyse multi-timeframe)
- MongoDB Atlas : persistance des cycles de trading (collection `cycles`)
- Telegram Bot API : interface utilisateur — commandes entrantes + notifications sortantes

Flux principal :
Utilisateur → Telegram → webhook_server.py → Claude CLI → Binance CLI
Claude CLI → TradingView MCP (données marché) → analyse → ordres OTOCO
Claude CLI → MongoDB Atlas (sauvegarde) → Telegram (notification résumé)

État persistant dans state/ (JSON) : trade_history, agent_lock, telegram_offset
Logs dans logs/ : bot_YYYY-MM-DD.log, stdout et stderr par cycle
""",
    },

    "trade-phases": {
        "title": "7 phases du cycle de trading",
        "text": """
Un cycle de trading complet se déroule en 7 phases séquentielles,
orchestrées par le sous-processus Claude CLI.

Phase 0 — Vérifications préalables
Lecture du portefeuille Binance, vérification de la limite de perte journalière (5%),
réconciliation des trades ouverts vs ordres actifs, mise à jour des statuts fermés (TP/SL touchés).

Phase 1 — Scan marché
4 screeners parallèles : top gainers, breakouts de volume, sentiment global du marché,
filtre par note technique. Constitution d'un univers de 20 coins maximum.

Phase 2 — Analyse multi-timeframe
Pour chaque coin retenu : analyse technique 4h + 1d via TradingView MCP.
Indicateurs : RSI, MACD, ADX, signal directionnel, tendance de fond.

Phase 3 — Scoring et sélection
Score de 0 à 10 par coin (RSI, MACD, ADX, alignement des timeframes, sentiment).
Filtres : score minimum 6, corrélation maximale entre positions (max 2 L1-alts),
budget disponible, nombre maximum de positions ouvertes (5).
Décision finale : BUY / HOLD / SELL / SKIP avec motif.

Phase 4 — Sizing et préparation des ordres
Risque fixe de 1% du portefeuille par trade.
Calcul du stop-loss via ATR × 2.0, calcul du TP à ratio 3:1.
Validation des contraintes Binance : montant minimum 11 USDC, pas de dérive de prix > 2%.

Phase 5 — Exécution des ordres
Placement d'ordres OTOCO atomiques sur Binance Spot :
ordre d'entrée LIMIT + ordre TP (take profit) + ordre SL (stop-loss) simultanément.
Notification Telegram pour chaque ordre exécuté ou rejeté.

Phase 6 — Rapport
Génération d'un rapport Markdown complet dans reports/.
Résumé du contexte marché, tableau des décisions, ordres exécutés, prochaine analyse.

Phase 7 — Persistance et synthèse
Sauvegarde du cycle complet dans MongoDB Atlas (collection cycles).
Envoi d'une notification Telegram de synthèse en français vulgarisé.
Libération du verrou de cycle (agent_lock.json).
""",
    },

    "data-flow": {
        "title": "Flux de données",
        "text": """
Comment les données circulent dans le bot de trading agent-binance.

Sources de données entrant dans le système :
L'utilisateur envoie des commandes via Telegram (lancer un trade, voir le portefeuille, consulter les performances, lire l'analyse, réinitialiser).
TradingView fournit les données de marché en temps réel : coins en hausse, breakouts de volume, sentiment global, analyse technique multi-timeframe.
Binance fournit les soldes du portefeuille, les ordres en cours et confirme les exécutions.

Traitement par le serveur principal :
Le serveur webhook reçoit les commandes Telegram en continu. Pour les demandes de statut portefeuille, il interroge Binance directement. Pour les analyses de performance, il consulte l'historique local des trades. Pour expliquer le dernier cycle de trading, il interroge la base de données MongoDB. Pour lancer un cycle de trading, il démarre un sous-processus d'intelligence artificielle.

Traitement par le sous-processus IA :
Le moteur IA lit la configuration et l'historique des trades, puis interroge TradingView pour analyser le marché. Il calcule les meilleures opportunités, prépare les ordres et les envoie à Binance pour exécution. Enfin, il sauvegarde le rapport complet du cycle dans MongoDB et envoie une synthèse à l'utilisateur via Telegram.

Données produites :
Notifications Telegram à l'utilisateur à chaque étape importante.
Rapport de cycle sauvegardé localement en format texte lisible.
Historique complet du cycle stocké dans MongoDB (décisions, ordres, explication).
Journaux techniques pour le débogage.
""",
    },

    "telegram-commands": {
        "title": "Commandes Telegram disponibles",
        "text": """
Interface utilisateur du bot de trading via Telegram.
Le bot répond à 5 commandes principales.

Commande TRADE
Lance immédiatement un cycle complet d'analyse et de trading.
Durée : entre 5 et 15 minutes.
Le bot envoie des notifications à chaque grande étape du cycle.
Si un cycle est déjà en cours, le bot le signale et refuse de démarrer un second.

Commande STATUS
Affiche une vue instantanée du portefeuille sur Binance :
solde disponible, montant verrouillé dans des ordres, positions ouvertes,
ordres en attente, et heure du prochain cycle automatique.

Commande PERF
Statistiques de performance calculées sur tous les trades fermés :
taux de réussite, espérance de gain par trade, profit factor,
ratio de Sharpe annualisé, perte maximale, test de significativité statistique.

Commande RAISONNEMENT
Explication en français simple du dernier cycle de trading.
Décrit ce que le bot a analysé, pourquoi il a acheté ou non,
et son évaluation du contexte de marché actuel.
L'explication est lue depuis la base de données MongoDB.

Commande RESET
Déverouille le bot si un cycle précédent s'est arrêté de façon anormale.
À utiliser quand le bot ne répond plus après un plantage.

Cycle automatique toutes les 4 heures
Sans aucune commande utilisateur, le bot se déclenche automatiquement
aux horaires alignés sur les clôtures des graphiques TradingView.
""",
    },

    "state-files": {
        "title": "Couches de persistance des données",
        "text": """
Le bot de trading agent-binance utilise plusieurs couches de persistance pour stocker son état.

Historique des trades (fichier JSON local)
Source de vérité pour tous les trades passés et actifs.
Chaque entrée contient : la crypto-monnaie tradée, le sens (achat), les prix d'entrée, de stop-loss et de take-profit, la quantité, le risque en USDC, les identifiants des ordres Binance, le statut (ouvert, fermé, annulé), le gain ou la perte réalisé, et les dates.
Ce fichier est lu et mis à jour à chaque cycle de trading.

Verrou de cycle (fichier JSON local)
Mécanisme de protection qui empêche deux cycles de tourner simultanément.
Contient un indicateur actif/inactif et l'heure de démarrage.
Se déverouille automatiquement après 2 heures ou via la commande de réinitialisation.

Position de lecture Telegram (fichier JSON local)
Mémorise le dernier message Telegram traité pour éviter les doublons après un redémarrage.
Mis à jour en continu pendant que le bot fonctionne.

Base de données MongoDB Atlas (cloud)
Stocke le document complet de chaque cycle de trading :
contexte de marché analysé, décisions prises pour chaque crypto avec motifs,
ordres placés, budget utilisé, et explication vulgarisée en français.
Consultée par la commande de raisonnement.

Journaux techniques (fichiers locaux)
Journal quotidien du processus principal avec rotation automatique.
Journaux de sortie et d'erreurs par cycle de trading pour le débogage.
Rapports lisibles par cycle au format Markdown.
""",
    },
}


# ---------------------------------------------------------------------------
# Chargement .env (même pattern que webhook_server.py)
# ---------------------------------------------------------------------------
def _load_env() -> None:
    env_path = PROJECT_DIR / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


# ---------------------------------------------------------------------------
# Client Napkin API — curl subprocess (contourne le bot-detection Cloudflare)
# ---------------------------------------------------------------------------
def _curl(method: str, url: str, token: str, body: dict | None = None) -> dict:
    cmd = [
        "curl", "-s", "-f", "-X", method,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json",
    ]
    if body:
        cmd += ["-d", json.dumps(body)]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"curl {method} {url} → exit {result.returncode}\n"
            f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Réponse Napkin non-JSON : {result.stdout[:500]}") from e


def create_visual(token: str, text: str, fmt: str = "svg") -> str:
    url = f"{NAPKIN_API_BASE}/visual"
    result = _curl("POST", url, token, {"content": text, "format": fmt})
    request_id = result.get("id") or result.get("request_id")
    if not request_id:
        raise RuntimeError(f"Pas de request_id dans la réponse Napkin : {result}")
    return request_id


def poll_visual(token: str, request_id: str, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    interval = 4
    while time.time() < deadline:
        result = _curl("GET", f"{NAPKIN_API_BASE}/visual/{request_id}/status", token)
        status = result.get("status", "")
        if status == "completed":
            return result
        if status == "failed":
            raise RuntimeError(f"Napkin a retourné status=failed : {result}")
        print(f"  … statut={status or '(en attente)'}, retry dans {interval}s", flush=True)
        time.sleep(interval)
        interval = min(interval + 2, 12)
    raise TimeoutError(f"Napkin n'a pas complété dans {timeout}s (request_id={request_id})")


def download_file(url: str, dest: Path, token: str = "") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["curl", "-s", "-f", "-L", "-o", str(dest)]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(
            f"Échec téléchargement {url} → exit {result.returncode}: {result.stderr.decode()[:300]}"
        )


def extract_download_urls(result: dict, fmt: str) -> list[str]:
    """
    Retourne TOUTES les URLs de téléchargement pour le format demandé.
    Napkin génère jusqu'à 4 variations — on les télécharge toutes.
    Champs connus : generated_files[].url (ou .svg_url / .png_url selon version).
    """
    urls: list[str] = []

    # Format principal : generated_files (doc officielle)
    for f in result.get("generated_files") or []:
        u = f.get("url") or f.get(f"{fmt}_url")
        if u:
            urls.append(u)

    # Fallbacks pour d'éventuelles variations de l'API
    if not urls:
        candidates = [
            result.get(f"{fmt}_url"),
            result.get("url"),
            (result.get("urls") or {}).get(fmt),
            (result.get("files") or {}).get(fmt),
            result.get("download_url"),
        ]
        urls = [u for u in candidates if u]

    if not urls:
        raise RuntimeError(
            f"Impossible de trouver une URL de téléchargement {fmt}.\n"
            f"Réponse brute : {json.dumps(result, indent=2)[:800]}"
        )
    return urls


# ---------------------------------------------------------------------------
# Génération d'un seul visuel
# ---------------------------------------------------------------------------
def generate_one(section_id: str, fmt: str, token: str) -> list[Path]:
    if section_id not in VISUALS:
        raise ValueError(f"Section inconnue : '{section_id}'. Disponibles : {list(VISUALS)}")

    spec = VISUALS[section_id]

    print(f"→ [{section_id}] {spec['title']}")
    print(f"  Envoi du texte à Napkin API…", flush=True)

    request_id = create_visual(token, spec["text"].strip(), fmt)
    print(f"  request_id={request_id}")

    result = poll_visual(token, request_id)

    # Sauvegarde les métadonnées brutes (debug + réponse complète)
    meta_path = VISUALS_DIR / f"{section_id}.meta.json"
    meta_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    # Napkin génère jusqu'à 4 variations — on les télécharge toutes
    urls = extract_download_urls(result, fmt)
    saved: list[Path] = []
    for i, url in enumerate(urls):
        suffix = f"_{i+1}" if len(urls) > 1 else ""
        dest = VISUALS_DIR / f"{section_id}{suffix}.{fmt}"
        print(f"  Téléchargement variation {i+1}/{len(urls)} → {dest.relative_to(PROJECT_DIR)}", flush=True)
        download_file(url, dest, token)
        saved.append(dest)
        print(f"  ✅ {dest.name} ({dest.stat().st_size // 1024} KB)")

    return saved


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    _load_env()

    parser = argparse.ArgumentParser(description="Génère des visuels Napkin AI depuis les docs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="Affiche les sections disponibles")
    group.add_argument("--section", metavar="ID", help="Génère le visuel d'une section")
    group.add_argument("--all", action="store_true", help="Génère tous les visuels")
    parser.add_argument(
        "--format", choices=["svg", "png"], default="svg", help="Format de sortie (défaut: svg)"
    )
    args = parser.parse_args()

    if args.list:
        print("Sections disponibles :")
        for sid, spec in VISUALS.items():
            print(f"  {sid:<22} — {spec['title']}")
        return

    token = os.environ.get("NAPKIN_API_TOKEN", "").strip()
    if not token:
        print(
            "❌ NAPKIN_API_TOKEN absent ou vide dans .env\n"
            "   → Récupère ton token sur https://app.napkin.ai dans Réglages > API"
        )
        sys.exit(1)

    VISUALS_DIR.mkdir(parents=True, exist_ok=True)

    sections = list(VISUALS) if args.all else [args.section]
    errors: list[str] = []
    total_files: list[Path] = []

    for sid in sections:
        try:
            saved = generate_one(sid, args.format, token)
            total_files.extend(saved)
        except Exception as exc:
            print(f"  ❌ Erreur sur [{sid}] : {exc}")
            errors.append(sid)

    print()
    if errors:
        print(f"Terminé avec {len(errors)} erreur(s) : {errors}")
        sys.exit(1)
    else:
        print(f"✅ {len(total_files)} fichier(s) dans docs/visuals/")


if __name__ == "__main__":
    main()
