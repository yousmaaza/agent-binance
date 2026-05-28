#!/usr/bin/env bash
# Ajoute le label AUTO sur tous les tickets [REC] du board, quel que soit leur statut.
# Usage : ./label_rec_auto.sh [--dry-run]

set -euo pipefail

REPO="yousmaaza/agent-binance"
PROJECT_ID="PVT_kwHOC0Dy0s4BYYhT"
DRY_RUN=false

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

echo "=== Recherche tickets [REC] sans label AUTO ==="

ISSUES=$(gh api graphql -f query='
  query($projectId: ID!) {
    node(id: $projectId) {
      ... on ProjectV2 {
        items(first: 100) {
          nodes {
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
    .content.title != null
    and (.content.title | startswith("[REC]"))
    and ([.content.labels.nodes[].name] | contains(["AUTO"]) | not)
  ) | "\(.content.number)|\(.content.title)"')

if [[ -z "$ISSUES" ]]; then
  echo "Tous les tickets [REC] ont déjà le label AUTO."
  exit 0
fi

COUNT=$(echo "$ISSUES" | wc -l | tr -d ' ')
echo "Tickets [REC] sans AUTO : $COUNT"

echo "$ISSUES" | while IFS='|' read -r ISSUE_NUMBER ISSUE_TITLE; do
  echo "→ #$ISSUE_NUMBER — $ISSUE_TITLE"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [dry-run] gh issue edit $ISSUE_NUMBER --add-label AUTO"
  else
    gh issue edit "$ISSUE_NUMBER" --repo "$REPO" --add-label "AUTO"
    echo "  ✓ label AUTO ajouté"
  fi
done

echo ""
echo "=== Terminé ==="
