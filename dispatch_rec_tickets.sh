#!/usr/bin/env bash
# Dispatch binance-dev-auto pour chaque ticket [REC] + In progress + AUTO du board.
# Usage : ./dispatch_rec_tickets.sh [--dry-run]

set -euo pipefail

REPO="yousmaaza/agent-binance"
PROJECT_ID="PVT_kwHOC0Dy0s4BYYhT"
DRY_RUN=false

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

echo "=== Recherche tickets [REC] + In progress + AUTO ==="

ITEMS=$(gh api graphql -f query='
  query($projectId: ID!) {
    node(id: $projectId) {
      ... on ProjectV2 {
        items(first: 100) {
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
  }' \
  -F projectId="$PROJECT_ID" \
  --jq '.data.node.items.nodes[] | select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name) == "In progress"
    and (.content.title | startswith("[REC]"))
    and ([.content.labels.nodes[].name] | contains(["AUTO"]))
  ) | "\(.id)|\(.content.number)|\(.content.title)"')

if [[ -z "$ITEMS" ]]; then
  echo "Aucun ticket éligible trouvé."
  exit 0
fi

echo "$ITEMS" | while IFS='|' read -r ITEM_NODE_ID ISSUE_NUMBER ISSUE_TITLE; do
  echo ""
  echo "→ #$ISSUE_NUMBER — $ISSUE_TITLE"
  echo "  item_node_id: $ITEM_NODE_ID"

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [dry-run] gh workflow run binance-dev-auto.yml -f issue_number=$ISSUE_NUMBER -f item_node_id=$ITEM_NODE_ID"
  else
    gh workflow run binance-dev-auto.yml \
      --repo "$REPO" \
      --ref main \
      -f issue_number="$ISSUE_NUMBER" \
      -f item_node_id="$ITEM_NODE_ID"
    echo "  ✓ dispatché"
    # Pause entre chaque dispatch pour éviter les races conditions
    sleep 10
  fi
done

echo ""
echo "=== Terminé ==="
