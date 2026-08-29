// Ouverture des explications de cycle (#442). Les onglets sont en CSS pur (radios .tabsel),
// comme dans la maquette — pas de JS à charger pour naviguer entre eux.
document.querySelectorAll(".why[data-dialog]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const dlg = document.getElementById(btn.dataset.dialog);
    if (dlg) dlg.showModal();
  });
});

// Graphe de PnL par période (#450) : bascule jour/mois et infobulle au survol.
// L'ancienne bande de cadence s'appuyait sur <title> SVG, illisible sur des barres fines —
// d'où une infobulle positionnée à la main, qui suit aussi le focus clavier.
const pnl = document.querySelector("[data-pnl]");
if (pnl) {
  const tip = pnl.querySelector(".pnl-tip");

  pnl.querySelectorAll(".gran button").forEach((btn) => {
    btn.addEventListener("click", () => {
      pnl.querySelectorAll(".gran button").forEach((b) => b.classList.toggle("on", b === btn));
      pnl.querySelectorAll(".pnl-fig").forEach((fig) => {
        fig.hidden = fig.dataset.view !== btn.dataset.gran;
      });
      hide();
    });
  });

  const show = (bar) => {
    const box = bar.getBoundingClientRect();
    const frame = pnl.getBoundingClientRect();
    tip.innerHTML = `${bar.dataset.label}<b>${bar.dataset.value} USDC</b>`;
    tip.hidden = false;
    tip.style.left = `${box.left - frame.left + box.width / 2}px`;
    tip.style.top = `${box.top - frame.top - 6}px`;
  };
  const hide = () => { tip.hidden = true; };

  pnl.querySelectorAll(".pnl-bar").forEach((bar) => {
    bar.addEventListener("mouseenter", () => show(bar));
    bar.addEventListener("focus", () => show(bar));
    bar.addEventListener("mouseleave", hide);
    bar.addEventListener("blur", hide);
  });
}
