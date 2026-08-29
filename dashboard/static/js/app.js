// Ouverture des explications de cycle (#442). Les onglets sont en CSS pur (radios .tabsel),
// comme dans la maquette — pas de JS à charger pour naviguer entre eux.
document.querySelectorAll(".why[data-dialog]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const dlg = document.getElementById(btn.dataset.dialog);
    if (dlg) dlg.showModal();
  });
});
