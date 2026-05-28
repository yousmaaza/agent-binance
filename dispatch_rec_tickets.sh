#!/usr/bin/env bash
# Dispatch binance-dev-auto pour tickets [REC] + In progress + AUTO du board.
# Mode interactif : liste numérotée, sélection simple ou multiple.
# Usage : ./dispatch_rec_tickets.sh [--dry-run] [--all]

set -euo pipefail

REPO="yousmaaza/agent-binance"
PROJECT_ID="PVT_kwHOC0Dy0s4BYYhT"
DRY_RUN=false
SELECT_ALL=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --all|-a)  SELECT_ALL=true ;;
  esac
done

echo "=== Recherche tickets [REC] + In progress + AUTO ==="

# Pagination : GitHub limite à 100 items par page, on boucle sur toutes les pages
ITEMS=$(python3 - <<'PYEOF'
import subprocess, json, sys

PROJECT_ID = "PVT_kwHOC0Dy0s4BYYhT"
QUERY = """
query($projectId: ID!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          fieldValues(first: 10) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
          content {
            ... on Issue {
              number
              title
              labels(first: 20) { nodes { name } }
            }
          }
        }
      }
    }
  }
}
"""

cursor = None
all_nodes = []
while True:
    args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"projectId={PROJECT_ID}"]
    if cursor:
        args += ["-F", f"cursor={cursor}"]
    else:
        args += ["-F", "cursor="]
    r = subprocess.run(args, capture_output=True, text=True)
    data = json.loads(r.stdout)
    items = data["data"]["node"]["items"]
    all_nodes.extend(items["nodes"])
    if not items["pageInfo"]["hasNextPage"]:
        break
    cursor = items["pageInfo"]["endCursor"]

for node in all_nodes:
    content = node.get("content") or {}
    title = content.get("title", "")
    number = content.get("number")
    if not title or not number:
        continue
    if not title.startswith("[REC]"):
        continue
    labels = [l["name"] for l in content.get("labels", {}).get("nodes", [])]
    if "AUTO" not in labels:
        continue
    status = next(
        (fv["name"] for fv in node["fieldValues"]["nodes"]
         if isinstance(fv, dict) and fv.get("field", {}).get("name") == "Status"),
        None
    )
    if status != "In progress":
        continue
    print(f"{node['id']}|{number}|{title}")
PYEOF
)

if [[ -z "$ITEMS" ]]; then
  echo "Aucun ticket éligible trouvé."
  exit 0
fi

# Charger en arrays
declare -a NODE_IDS NUMBERS TITLES
while IFS='|' read -r node num title; do
  NODE_IDS+=("$node")
  NUMBERS+=("$num")
  TITLES+=("$title")
done <<< "$ITEMS"

TOTAL=${#NUMBERS[@]}

echo ""
echo "Tickets éligibles ($TOTAL) :"
echo ""
for i in "${!NUMBERS[@]}"; do
  printf "  [%2d] #%-4s %s\n" "$((i+1))" "${NUMBERS[$i]}" "${TITLES[$i]}"
done
echo ""

# Construire liste d'indices à dispatcher
declare -a SELECTED_IDX

if [[ "$SELECT_ALL" == "true" || "$DRY_RUN" == "true" ]]; then
  for i in "${!NUMBERS[@]}"; do SELECTED_IDX+=("$i"); done
else
  echo "Sélection (exemples : '1'  '1,3,5'  '2-5'  '1,3-5'  'all') :"
  echo "  Laisser vide ou 'q' pour annuler."
  echo ""
  read -p "> " CHOICE

  if [[ -z "$CHOICE" || "$CHOICE" == "q" ]]; then
    echo "Annulé."
    exit 0
  fi

  if [[ "$CHOICE" == "all" || "$CHOICE" == "a" ]]; then
    for i in "${!NUMBERS[@]}"; do SELECTED_IDX+=("$i"); done
  else
    IFS=',' read -ra PARTS <<< "$CHOICE"
    for part in "${PARTS[@]}"; do
      part=$(echo "$part" | tr -d ' ')
      if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
        START="${BASH_REMATCH[1]}"
        END="${BASH_REMATCH[2]}"
        for ((j=START; j<=END; j++)); do
          if (( j >= 1 && j <= TOTAL )); then
            SELECTED_IDX+=("$((j-1))")
          else
            echo "⚠️  $j hors plage (1-$TOTAL), ignoré."
          fi
        done
      elif [[ "$part" =~ ^[0-9]+$ ]]; then
        if (( part >= 1 && part <= TOTAL )); then
          SELECTED_IDX+=("$((part-1))")
        else
          echo "⚠️  $part hors plage (1-$TOTAL), ignoré."
        fi
      else
        echo "⚠️  Entrée invalide : '$part', ignorée."
      fi
    done
  fi
fi

# Dédupliquer + trier
SELECTED_IDX=($(printf "%s\n" "${SELECTED_IDX[@]}" | sort -nu))

if [[ ${#SELECTED_IDX[@]} -eq 0 ]]; then
  echo "Aucune sélection valide."
  exit 0
fi

echo ""
echo "Tickets sélectionnés (${#SELECTED_IDX[@]}) :"
for idx in "${SELECTED_IDX[@]}"; do
  echo "  • #${NUMBERS[$idx]} — ${TITLES[$idx]}"
done
echo ""

if [[ "$DRY_RUN" == "false" ]]; then
  read -p "Confirmer le dispatch ? [y/N] " CONFIRM
  if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Annulé."
    exit 0
  fi
fi

echo ""
echo "=== Dispatch en cours ==="

for idx in "${SELECTED_IDX[@]}"; do
  N="${NUMBERS[$idx]}"
  T="${TITLES[$idx]}"
  NODE="${NODE_IDS[$idx]}"

  echo ""
  echo "→ #$N — $T"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [dry-run] gh workflow run binance-dev-auto.yml -f issue_number=$N -f item_node_id=$NODE"
  else
    gh workflow run binance-dev-auto.yml \
      --repo "$REPO" \
      --ref main \
      -f issue_number="$N" \
      -f item_node_id="$NODE"
    echo "  ✓ dispatché"
    sleep 10
  fi
done

echo ""
echo "=== Terminé ==="
