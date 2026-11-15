// Wetland Pulse: aba "Mapa" — contrato v2. Mapa real (Leaflet + OpenStreetMap)
// com as camadas medidas do NISAR (água aberta / radar HH) por passagem, e uma
// régua de comparação de verdade entre a data da esquerda e da direita.
"use strict";

(function () {
  const $ = id => document.getElementById(id);
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const fmtDate = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]} ${y}`; };
  const fmtShort = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]}`; };

  let manifest = null;
  let map = null;
  let initialized = false;
  let leftIdx = 0, rightIdx = 0;
  let paneLeftLayers = [], paneRightLayers = [];

  fetch("data/manifest.json")
    .then(r => { if (!r.ok) throw new Error("manifest"); return r.json(); })
    .then(m => { manifest = m; leftIdx = 0; rightIdx = m.dates.length - 1; })
    .catch(err => console.error("Falha ao carregar manifest.json", err));

  const mapaTabBtn = document.querySelector('.tab[data-tab="mapa"]');
  if (mapaTabBtn) mapaTabBtn.addEventListener("click", tryInit);

  function tryInit() {
    if (initialized || !manifest) return;
    initialized = true;
    requestAnimationFrame(() => requestAnimationFrame(initMap));
  }

  function layerFor(date, type) {
    return manifest.layers.find(l => l.date === date && l.type === type);
  }

  function initMap() {
    const [w, s, e, n] = manifest.aoi.bbox;
    const bounds = [[s, w], [n, e]];

    $("mapTitle").textContent = manifest.aoi.name === "pantanal-norte" ? "Área de estudo" : manifest.aoi.name;
    $("mapSub").textContent = `Pantanal norte (MT) · Trilha NISAR 132 · ${manifest.aoi.area_km2.toLocaleString("pt-BR", { maximumFractionDigits: 0 })} km² de AOI`;

    map = L.map("leafletMap", {
      zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
      boxZoom: false, keyboard: false, touchZoom: false, tap: false,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 14,
      attribution: "&copy; OpenStreetMap | NISAR: NASA/ISRO, ASF DAAC | OPERA: NASA/JPL",
    }).addTo(map);
    map.fitBounds(bounds);
    L.rectangle(bounds, { color: "#1b2a22", weight: 1.5, fill: false, dashArray: "6 4", interactive: false }).addTo(map);

    map.createPane("paneLeft"); map.getPane("paneLeft").style.zIndex = 450;
    map.createPane("paneRight"); map.getPane("paneRight").style.zIndex = 451;

    buildOverlayUI();
    buildDateList();
    renderOverlays();

    $("toggleHH").addEventListener("change", renderOverlays);

    new ResizeObserver(() => { map.invalidateSize(); map.fitBounds(bounds); positionSlider(currentSliderPx()); }).observe($("leafletMap"));
  }

  // --- slider (comparison line) ---
  let sliderPx = null;

  function currentSliderPx() {
    const rect = document.querySelector(".map-canvas").getBoundingClientRect();
    return sliderPx == null ? rect.width / 2 : Math.max(40, Math.min(rect.width - 40, sliderPx));
  }

  function buildOverlayUI() {
    const ui = $("mapOverlayUI");
    ui.innerHTML = `
      <div class="slider-line" id="sliderLine"></div>
      <div class="slider-handle" id="sliderHandle">
        <div class="hit">
          <svg width="24" height="24" viewBox="0 0 24 24"><path d="M9 7 L5 12 L9 17 M15 7 L19 12 L15 17 M5 12 L19 12" fill="none" stroke="#1b2a22" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </div>
      </div>
      <div class="map-pill" id="pillLeft" style="top:16px; left:16px;"></div>
      <div class="map-pill" id="pillRight" style="top:16px; right:16px;"></div>`;

    const handle = $("sliderHandle");
    let dragging = false;
    handle.addEventListener("pointerdown", ev => { dragging = true; handle.setPointerCapture(ev.pointerId); });
    handle.addEventListener("pointermove", ev => {
      if (!dragging) return;
      const rect = document.querySelector(".map-canvas").getBoundingClientRect();
      const px = Math.max(40, Math.min(rect.width - 40, ev.clientX - rect.left));
      positionSlider(px);
    });
    handle.addEventListener("pointerup", () => { dragging = false; });
    handle.addEventListener("pointercancel", () => { dragging = false; });

    positionSlider(currentSliderPx());
  }

  function positionSlider(px) {
    sliderPx = px;
    $("sliderLine").style.left = px + "px";
    $("sliderHandle").style.left = px + "px";
    applyClip(px);
  }

  function applyClip(px) {
    if (!map) return;
    const w = map.getSize().x;
    map.getPane("paneLeft").style.clipPath = `inset(0 ${Math.max(0, w - px)}px 0 0)`;
    map.getPane("paneRight").style.clipPath = `inset(0 0 0 ${Math.max(0, px)}px)`;
  }

  // --- overlays per side ---
  function clearSide(list) { list.forEach(o => map.removeLayer(o)); return []; }

  function addSide(dateIdx, pane) {
    const date = manifest.dates[dateIdx];
    const list = [];
    if ($("toggleHH").checked) {
      const hh = layerFor(date, "backscatter");
      if (hh) list.push(L.imageOverlay("data/" + hh.file, hh.bounds, { pane, opacity: 0.95 }).addTo(map));
    }
    const ow = layerFor(date, "open_water");
    if (ow) list.push(L.imageOverlay("data/" + ow.file, ow.bounds, { pane, opacity: 0.9 }).addTo(map));
    return list;
  }

  function renderOverlays() {
    paneLeftLayers = clearSide(paneLeftLayers);
    paneRightLayers = clearSide(paneRightLayers);
    paneLeftLayers = addSide(leftIdx, "paneLeft");
    paneRightLayers = addSide(rightIdx, "paneRight");
    updateLabels();
  }

  function updateLabels() {
    const left = manifest.dates[leftIdx], right = manifest.dates[rightIdx];
    const owL = layerFor(left, "open_water"), owR = layerFor(right, "open_water");
    $("pillLeft").textContent = `Esquerda · ${fmtDate(left)}${owL ? " · " + owL.water_km2.toLocaleString("pt-BR") + " km²" : ""}`;
    $("pillRight").textContent = `Direita · ${fmtDate(right)}${owR ? " · " + owR.water_km2.toLocaleString("pt-BR") + " km²" : ""}`;
  }

  // --- sidebar date list ---
  function buildDateList() {
    $("dateList").innerHTML = manifest.dates.map((d, i) => (
      `<div class="date-row" data-idx="${i}">
        <span>${fmtShort(d)}</span>
        <span class="toggles">
          <button class="toggle" data-side="left" aria-label="Usar como esquerda">E</button>
          <button class="toggle" data-side="right" aria-label="Usar como direita">D</button>
        </span>
      </div>`
    )).join("");

    $("dateList").addEventListener("click", ev => {
      const btn = ev.target.closest(".toggle");
      if (!btn) return;
      const idx = Number(btn.closest(".date-row").dataset.idx);
      if (btn.dataset.side === "left") leftIdx = idx; else rightIdx = idx;
      renderOverlays();
      markActiveToggles();
    });
    markActiveToggles();
  }

  function markActiveToggles() {
    document.querySelectorAll(".date-row").forEach(row => {
      const idx = Number(row.dataset.idx);
      row.querySelector('[data-side="left"]').classList.toggle("active-e", idx === leftIdx);
      row.querySelector('[data-side="right"]').classList.toggle("active-d", idx === rightIdx);
    });
  }
})();
