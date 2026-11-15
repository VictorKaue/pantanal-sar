// Wetland Pulse: navegação entre abas e modal "Sobre os dados".
"use strict";

(function () {
  const $ = id => document.getElementById(id);

  const tabs = Array.from(document.querySelectorAll(".tab"));
  const views = {
    serie: $("view-serie"),
    mapa: $("view-mapa"),
    story: $("view-story"),
  };

  tabs.forEach(btn => btn.addEventListener("click", () => {
    tabs.forEach(b => {
      const active = b === btn;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", String(active));
    });
    Object.entries(views).forEach(([key, el]) => el.classList.toggle("active", key === btn.dataset.tab));
  }));

  const modal = $("infoModal");
  function openModal() { modal.hidden = false; }
  function closeModal() { modal.hidden = true; }

  $("infoBtn").addEventListener("click", openModal);
  $("modalCloseX").addEventListener("click", closeModal);
  $("modalCloseBtn").addEventListener("click", closeModal);
  modal.addEventListener("click", ev => { if (ev.target === modal) closeModal(); });
  document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !modal.hidden) closeModal(); });
})();
