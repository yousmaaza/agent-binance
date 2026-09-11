#!/usr/bin/env python3
"""Génère docs/strategie.md depuis docs/strategie.html (#486).

Le HTML est la source : c'est lui qui est publié comme artefact. Le markdown en est
dérivé pour être lisible et diffable en PR — il ne doit jamais être édité à la main.
Même motif que docs/visuals/, où les .svg sont générés depuis les .d2 / .mmd.

    python3 scripts/strategie_to_md.py            # régénère le markdown
    python3 scripts/strategie_to_md.py --check    # échoue si le markdown est périmé

Les trois figures SVG du HTML n'ont pas d'équivalent markdown : elles sont remplacées,
dans l'ordre où elles apparaissent, par les diagrammes mermaid définis dans MERMAID.
"""
import html
import os
import re
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(PROJECT_DIR, "docs", "strategie.html")
CIBLE = os.path.join(PROJECT_DIR, "docs", "strategie.md")
MERMAID = {
0: """```mermaid
flowchart LR
  U["Univers<br/>~46 paires USDC"] --> S["Scan<br/>phase 1"]
  S --> A["Score<br/>phases 2-3"]
  A --> T["Taille<br/>phase 4"]
  T --> E["Execution<br/>phase 5"]
  E --> OK(["achat"])
  S -. rejet .-> D["TYPE_D<br/>volume, spread, pic isole"]
  A -. rejet .-> B["TYPE_A<br/>score faible, quota, correlation"]
  T -. rejet .-> C["TYPE_B<br/>montant trop petit, stop negatif"]
  E -. rejet .-> F["TYPE_C<br/>derive du prix, solde, non rempli"]
```""",
1: """```mermaid
flowchart TD
  Q["score >= seuil effectif<br/>ET signal_4h haussier"] --> V1{"deja en portefeuille ?"}
  V1 -- oui --> H["HOLD"]
  V1 -- non --> V2{"mode degrade ET RSI hors zone ?"}
  V2 -- oui --> S2["SKIP TYPE_A"]
  V2 -- non --> V3{"quota de positions atteint ?"}
  V3 -- oui --> S3["SKIP TYPE_A"]
  V3 -- non --> V4{"trop de correlees ?"}
  V4 -- oui --> S4["SKIP TYPE_A"]
  V4 -- non --> BUY(["BUY - candidat retenu"])
```""",
2: """```mermaid
flowchart TD
  T["tick du watcher maker"] --> R{"ordre rempli ?"}
  R -- oui --> FIN(["position ouverte, stop pose"])
  R -- non --> X{"termine autrement ?"}
  X -- oui --> REC["reconciliation"]
  X -- non --> P{"prix invalide ?"}
  P -- oui --> AB["abandon"]
  P -- non --> L{"concession epuisee<br/>ou delai depasse ?"}
  L -- oui --> MK["repli marche ou abandon"]
  L -- non --> M{"le meilleur achat a bouge ?"}
  M -- oui --> AM["order amend - jamais annuler puis reposer"]
  M -- non --> W["rien a faire"]
```"""}

def texte(s):
    """Inline HTML -> markdown."""
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<span class="cfg[^"]*">(.*?)</span>', r'`\1`', s, flags=re.S)
    s = re.sub(r'<code>(.*?)</code>', r'`\1`', s, flags=re.S)
    s = re.sub(r'<b>(.*?)</b>', r'**\1**', s, flags=re.S)
    s = re.sub(r'<em>(.*?)</em>', r'*\1*', s, flags=re.S)
    s = re.sub(r'<sup>(.*?)</sup>', r'\1', s, flags=re.S)
    s = re.sub(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', s, flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    return s.strip()

def bloc_pre(s):
    """Formules et exemples : texte monospace, conserve les retours a la ligne."""
    s = re.sub(r'<span class="tag">(.*?)</span>', r'[\1]\n', s, flags=re.S)
    s = re.sub(r'<span class="cm">(.*?)</span>', r'\1', s, flags=re.S)
    s = re.sub(r'<br\s*/?>[ \t]*\n?', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    s = re.sub(r'\u00a0', ' ', s)
    lignes = [re.sub(r'[ \t]+', ' ', ligne).strip() for ligne in s.split('\n')]
    out = []
    for ligne in lignes:
        # jamais deux lignes vides d'affilée, jamais de vide en tête
        if not ligne and (not out or not out[-1]):
            continue
        out.append(ligne)
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out)

def table(t):
    heads = [texte(c) for c in re.findall(r'<th[^>]*>(.*?)</th>', t, re.S)]
    out = ['| ' + ' | '.join(heads) + ' |', '|' + '---|' * len(heads)]
    corps = t[t.index('<tbody>'):] if '<tbody>' in t else t
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', corps, re.S):
        cells = [texte(c).replace('\n', ' ') for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if not cells:
            continue
        while len(cells) < len(heads):
            cells.append('')
        out.append('| ' + ' | '.join(cells[:len(heads)]) + ' |')
    return '\n'.join(out)

src = open(SOURCE, encoding="utf-8").read()
# on ne garde que le corps rédactionnel
src = src[src.index('<div class="sheet">'):src.rindex('</div>')]

sortie = []
i_fig = 0
for bloc in re.findall(
        r'<h2>.*?</h2>|<h3>.*?</h3>|<p class="lede">.*?</p>|<p class="note"[^>]*>.*?</p>'
        r'|<p>.*?</p>|<div class="f">.*?</div>|<div class="ex[^"]*">.*?</div>'
        r'|<figure>.*?</figure>|<table>.*?</table>|<div class="skips">.*?</div>\s*</div>'
        r'|<header class="mast">.*?</header>|<footer>.*?</footer>', src, re.S):
    if bloc.startswith('<header'):
        h1 = texte(re.search(r'<h1>(.*?)</h1>', bloc, re.S).group(1))
        sf = texte(re.search(r'<p class="standfirst">(.*?)</p>', bloc, re.S).group(1))
        sortie += [f'# {h1}', '', sf]
    elif bloc.startswith('<footer'):
        sortie += ['---', '', f'*{texte(bloc)}*']
    elif bloc.startswith('<h2>'):
        ph = re.search(r'<span class="ph">(.*?)</span>', bloc, re.S)
        titre = texte(re.sub(r'<span class="ph">.*?</span>', '', bloc, flags=re.S))
        sortie += ['', f'## {texte(ph.group(1)) + " — " if ph else ""}{titre}']
    elif bloc.startswith('<h3>'):
        sortie += ['', f'### {texte(bloc)}']
    elif bloc.startswith('<p class="note"'):
        sortie += ['', '\n'.join('> ' + ligne for ligne in texte(bloc).split('\n'))]
    elif bloc.startswith('<div class="f">'):
        sortie += ['', '```text', bloc_pre(bloc), '```']
    elif bloc.startswith('<div class="ex'):
        sortie += ['', '```text', bloc_pre(bloc), '```']
    elif bloc.startswith('<table>'):
        sortie += ['', table(bloc)]
    elif bloc.startswith('<div class="skips">'):
        for d in re.findall(r'<div class="skip">(.*?)</div>', bloc, re.S):
            b = re.search(r'<b>(.*?)</b>', d, re.S).group(1)
            sp = re.search(r'<span>(.*?)</span>', d, re.S).group(1)
            sortie.append(f'- **{texte(b)}** — {texte(sp)}')
    elif bloc.startswith('<figure>'):
        sortie += ['', MERMAID.get(i_fig, '<!-- diagramme -->')]
        cap = re.search(r'<figcaption>(.*?)</figcaption>', bloc, re.S)
        if cap:
            sortie += ['', f'*{texte(cap.group(1))}*']
        i_fig += 1
    else:
        sortie += ['', texte(bloc)]

md = re.sub(r'\n{3,}', '\n\n', '\n'.join(sortie)) + '\n'

if "--check" in sys.argv:
    actuel = open(CIBLE, encoding="utf-8").read() if os.path.exists(CIBLE) else ""
    if actuel != md:
        print("docs/strategie.md est périmé : régénère-le avec "
              "python3 scripts/strategie_to_md.py", file=sys.stderr)
        sys.exit(1)
    print("docs/strategie.md est à jour")
else:
    open(CIBLE, "w", encoding="utf-8").write(md)
    print(f"docs/strategie.md régénéré : {len(md)} octets, "
          f"{md.count(chr(10) + '## ')} sections, {i_fig} figures")
