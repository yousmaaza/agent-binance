#!/usr/bin/env bash
# Consolide les PRs AUTO ouvertes en une seule PR de consolidation.
# Les tickets liés sont fermés automatiquement au merge via "Closes #N".
# Les PRs individuelles sont fermées (superseded) après création de la PR consolidée.
# Usage : ./consolidate_rec_prs.sh [--dry-run]

set -euo pipefail

REPO="yousmaaza/agent-binance"
BASE_BRANCH="main"
DATE=$(date +%Y%m%d_%H%M%S)
CONSOLIDATION_BRANCH="feat/consolidate-rec-${DATE}"
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in --dry-run) DRY_RUN=true ;; esac
done

echo "=== Récupération des PRs AUTO ouvertes ==="

PR_DATA=$(python3 - "$REPO" <<'PYEOF'
import json, re, sys, subprocess
from collections import defaultdict

repo = sys.argv[1]

r = subprocess.run(
    ["gh", "pr", "list", "--repo", repo, "--state", "open",
     "--json", "number,title,headRefName,body,createdAt", "--limit", "100"],
    capture_output=True, text=True
)
prs = json.loads(r.stdout)

# Garder uniquement les branches feat/issue-*
prs = [p for p in prs if re.match(r'feat/issue-', p['headRefName'])]

# Dédupliquer : pour une même issue, garder la PR la plus récente
by_issue = defaultdict(list)
for pr in prs:
    branch = pr['headRefName']
    body = pr.get('body', '') or ''

    issues = list(dict.fromkeys(re.findall(
        r'(?:closes?|fixes?|resolves?)\s+#(\d+)', body, re.IGNORECASE
    )))
    if not issues:
        m = re.search(r'feat/issue-(\d+)', branch)
        if m:
            issues = [m.group(1)]

    key = issues[0] if issues else branch
    by_issue[key].append((pr['createdAt'], pr['number'], branch, issues, pr['title']))

for key, entries in sorted(by_issue.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
    entries.sort(reverse=True)
    _, pr_num, branch, issues, title = entries[0]
    issues_str = ','.join(issues) if issues else ''
    print(f"{pr_num}|{branch}|{issues_str}|{title}")
    for _, dup_num, dup_branch, _, _ in entries[1:]:
        sys.stderr.write(f"  ⚠️  Doublon ignoré : PR#{dup_num} ({dup_branch})\n")
PYEOF
)

if [[ -z "$PR_DATA" ]]; then
  echo "Aucune PR AUTO ouverte trouvée."
  exit 0
fi

declare -a PR_NUMBERS PR_BRANCHES PR_ISSUES PR_TITLES
while IFS='|' read -r num branch issues title; do
  PR_NUMBERS+=("$num")
  PR_BRANCHES+=("$branch")
  PR_ISSUES+=("$issues")
  PR_TITLES+=("$title")
done <<< "$PR_DATA"

TOTAL=${#PR_NUMBERS[@]}

echo ""
echo "PRs éligibles ($TOTAL) :"
echo ""
for i in "${!PR_NUMBERS[@]}"; do
  printf "  [%2d] PR#%-5s branch: %-45s issues: %s\n" \
    "$((i+1))" "${PR_NUMBERS[$i]}" "${PR_BRANCHES[$i]}" "${PR_ISSUES[$i]}"
  printf "        %s\n" "${PR_TITLES[$i]}"
done
echo ""

declare -a SELECTED_IDX

if [[ "$DRY_RUN" == "true" ]]; then
  for i in "${!PR_NUMBERS[@]}"; do SELECTED_IDX+=("$i"); done
else
  echo "Sélection (exemples : '1'  '1,3,5'  '2-5'  'all') :"
  echo "  Laisser vide ou 'q' pour annuler."
  echo ""
  read -p "> " CHOICE

  if [[ -z "$CHOICE" || "$CHOICE" == "q" ]]; then
    echo "Annulé."
    exit 0
  fi

  if [[ "$CHOICE" == "all" || "$CHOICE" == "a" ]]; then
    for i in "${!PR_NUMBERS[@]}"; do SELECTED_IDX+=("$i"); done
  else
    IFS=',' read -ra PARTS <<< "$CHOICE"
    for part in "${PARTS[@]}"; do
      part=$(echo "$part" | tr -d ' ')
      if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
        START="${BASH_REMATCH[1]}"; END="${BASH_REMATCH[2]}"
        for ((j=START; j<=END; j++)); do
          if (( j >= 1 && j <= TOTAL )); then SELECTED_IDX+=("$((j-1))")
          else echo "⚠️  $j hors plage (1-$TOTAL), ignoré."; fi
        done
      elif [[ "$part" =~ ^[0-9]+$ ]]; then
        if (( part >= 1 && part <= TOTAL )); then SELECTED_IDX+=("$((part-1))")
        else echo "⚠️  $part hors plage (1-$TOTAL), ignoré."; fi
      else
        echo "⚠️  Entrée invalide : '$part', ignorée."
      fi
    done
  fi
fi

SELECTED_IDX=($(printf "%s\n" "${SELECTED_IDX[@]}" | sort -nu))

if [[ ${#SELECTED_IDX[@]} -eq 0 ]]; then
  echo "Aucune sélection valide."
  exit 0
fi

# Collecter toutes les issues liées
declare -a ALL_ISSUES
for idx in "${SELECTED_IDX[@]}"; do
  IFS=',' read -ra issues <<< "${PR_ISSUES[$idx]}"
  for issue in "${issues[@]}"; do
    [[ -n "$issue" ]] && ALL_ISSUES+=("$issue")
  done
done
ALL_ISSUES=($(printf "%s\n" "${ALL_ISSUES[@]}" | sort -nu))

echo ""
echo "PRs sélectionnées (${#SELECTED_IDX[@]}) :"
for idx in "${SELECTED_IDX[@]}"; do
  echo "  • PR#${PR_NUMBERS[$idx]} — ${PR_TITLES[$idx]}"
done
echo ""
if [[ ${#ALL_ISSUES[@]} -gt 0 ]]; then
  echo "Issues fermées au merge : $(printf '#%s ' "${ALL_ISSUES[@]}")"
else
  echo "⚠️  Aucune issue liée détectée — les tickets devront être fermés manuellement."
fi
echo ""

if [[ "$DRY_RUN" == "true" ]]; then
  echo "[dry-run] Branche de consolidation : $CONSOLIDATION_BRANCH"
  echo "[dry-run] Closes : $(printf 'Closes #%s  ' "${ALL_ISSUES[@]}")"
  exit 0
fi

read -p "Confirmer la consolidation ? [y/N] " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
  echo "Annulé."
  exit 0
fi

echo ""
echo "=== Consolidation en cours ==="

# S'assurer que git-perso est chargé si disponible
command -v git-perso &>/dev/null && git-perso || true

git fetch --all --prune

git checkout "$BASE_BRANCH"
git pull origin "$BASE_BRANCH"
git checkout -b "$CONSOLIDATION_BRANCH"

declare -a MERGED_PRS SKIPPED_PRS

for idx in "${SELECTED_IDX[@]}"; do
  branch="${PR_BRANCHES[$idx]}"
  pr_num="${PR_NUMBERS[$idx]}"

  echo ""
  echo "→ Merge PR#$pr_num — $branch"

  # Vérifier que la branche distante existe
  if ! git ls-remote --exit-code --heads origin "$branch" &>/dev/null; then
    echo "  ✗ branche absente sur origin — skip"
    SKIPPED_PRS+=("$pr_num")
    continue
  fi

  if git merge --no-edit -X theirs "origin/$branch" 2>/dev/null; then
    echo "  ✓ mergé"
    MERGED_PRS+=("$pr_num")
  else
    echo "  ✗ conflit non résolvable — skip"
    git merge --abort 2>/dev/null || true
    SKIPPED_PRS+=("$pr_num")
  fi
done

if [[ ${#MERGED_PRS[@]} -eq 0 ]]; then
  echo ""
  echo "Aucun merge réussi. Nettoyage."
  git checkout "$BASE_BRANCH"
  git branch -D "$CONSOLIDATION_BRANCH"
  exit 1
fi

git push -u origin "$CONSOLIDATION_BRANCH"

# Construire le corps de la PR
CLOSES_LINES=$(printf "Closes #%s\n" "${ALL_ISSUES[@]}")
MERGED_LIST=$(printf -- "- PR #%s\n" "${MERGED_PRS[@]}")
if [[ ${#SKIPPED_PRS[@]} -gt 0 ]]; then
  SKIPPED_NOTE="⚠️ PRs ignorées (conflit non résolvable) : $(printf '#%s ' "${SKIPPED_PRS[@]}")"
else
  SKIPPED_NOTE=""
fi

CONSOLIDATION_PR_URL=$(gh pr create \
  --repo "$REPO" \
  --base "$BASE_BRANCH" \
  --head "$CONSOLIDATION_BRANCH" \
  --label "AUTO" \
  --title "chore: consolidation [REC] AUTO — $(date +%Y-%m-%d)" \
  --body "$(cat <<EOF
## Consolidation des PRs [REC] AUTO

Ce PR regroupe ${#MERGED_PRS[@]} PR(s) [REC] générées automatiquement.

### PRs incluses
$MERGED_LIST

### Fermeture automatique des tickets au merge
$CLOSES_LINES

$SKIPPED_NOTE

---
🤖 Généré par \`consolidate_rec_prs.sh\`
EOF
)")

echo ""
echo "✓ PR de consolidation créée : $CONSOLIDATION_PR_URL"

# Fermer les PRs individuelles (superseded) — itérer directement sur MERGED_PRS
echo ""
echo "=== Fermeture des PRs individuelles ==="
for pr_num in "${MERGED_PRS[@]}"; do
  gh pr close "$pr_num" \
    --repo "$REPO" \
    --comment "Superseded par la PR de consolidation : $CONSOLIDATION_PR_URL" \
    2>/dev/null && echo "  ✓ PR#$pr_num fermée" || echo "  ⚠️  PR#$pr_num : fermeture échouée"
done

echo ""
echo "=== Terminé ==="
echo "→ Branche   : $CONSOLIDATION_BRANCH"
echo "→ PR        : $CONSOLIDATION_PR_URL"
echo "→ Au merge  : $(printf '#%s ' "${ALL_ISSUES[@]}") seront fermés automatiquement"
if [[ ${#SKIPPED_PRS[@]} -gt 0 ]]; then
  echo "→ Skippées  : $(printf 'PR#%s ' "${SKIPPED_PRS[@]}")"
fi
