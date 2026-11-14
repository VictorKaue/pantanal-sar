// Pantanal SAR: frontend estático. Lê data/manifest.json e data/firms.geojson
// (gerados por `python -m pantanal_sar.cli export`). Contrato em web/README.md.
"use strict";

const SOURCE_LABEL = { measured: "Medido (NISAR)", derived: "Derivado (NISAR + FIRMS)" };
// Ordem e estado inicial das camadas.
const TYPES = [
  { type: "open_water", on: true },
  { type: "flooded_veg", on: false },
  { type: "dried", on: true },
  { type: "burn", on: true },
  { type: "dried_then_burned", on: false, note: "acumulado" },
  { type: "backscatter", on: false },
];
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

const $ = id => document.getElementById(id);
const fmtDate = d => { const [y, m, dd] = d.split("-"); return `${+dd} ${MONTHS[m - 1]} ${y}`; };
const fmtNum = n => (n == null ? "-" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 1 }));

const map = L.map("map", { zoomControl: true }).setView([-17, -57.8], 8);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 14, attribution: "&copy; OpenStreetMap contributors | NISAR: NASA/ISRO, ASF DAAC | FIRMS: NASA",
}).addTo(map);
L.control.scale({ imperial: false }).addTo(map);

const state = { m: null, i: 0, on: Object.fromEntries(TYPES.map(t => [t.type, t.on])), opacity: 0.9, firms: [] };
let overlays = [];
const firmsLayer = L.layerGroup().addTo(map);

fetch("data/manifest.json")
  .then(r => r.json())
  .then(init)
  .catch(() => { /* mantém a mensagem "Sem dados" */ });

function init(m) {
  if (!m.layers || !m.layers.length) return;
  state.m = m;
  state.i = m.dates.length - 1;
  $("empty").hidden = true;
  ["when", "cards", "layersBox"].forEach(id => ($(id).hidden = false));
  $("banner").hidden = !m.demo;
  const [w, s, e, n] = m.bbox;
  const aoi = [[s, w], [n, e]];
  map.invalidateSize();
  map.fitBounds(aoi);
  // Se o mapa nasceu sem tamanho (aba oculta, painel redimensionado), reenquadra ao ganhar tamanho.
  let userMoved = false;
  const mark = () => (userMoved = true);
  map.once("dragstart", mark);
  ["wheel", "dblclick", "touchstart"].forEach(ev => $("map").addEventListener(ev, mark, { once: true, passive: true }));
  map.zoomControl.getContainer().addEventListener("click", mark, { once: true });
  new ResizeObserver(() => { map.invalidateSize(); if (!userMoved) map.fitBounds(aoi); }).observe($("map"));
  L.rectangle([[s, w], [n, e]], { color: "#333", weight: 1, fill: false, dashArray: "4 4", interactive: false }).addTo(map);

  const slider = $("date");
  slider.max = m.dates.length - 1;
  slider.value = state.i;
  slider.oninput = () => go(+slider.value);
  $("prev").onclick = () => go(state.i - 1);
  $("next").onclick = () => go(state.i + 1);
  document.addEventListener("keydown", ev => {
    if (ev.target.tagName === "INPUT" && ev.target.type !== "checkbox") return;
    if (ev.key === "ArrowLeft") go(state.i - 1);
    if (ev.key === "ArrowRight") go(state.i + 1);
  });
  $("ticks").innerHTML = m.dates.map(d => `<span>${fmtDate(d).slice(0, -5)}</span>`).join("");

  buildLayerList(m);
  $("firms").onchange = draw;
  $("opacity").oninput = ev => { state.opacity = +ev.target.value; overlays.forEach(o => o.setOpacity(state.opacity)); };

  showAnalysis(m.stats);
  if (m.firms) {
    fetch("data/" + m.firms).then(r => r.json()).then(g => { state.firms = g.features || []; draw(); }).catch(() => {});
  }
  draw();
}

function buildLayerList(m) {
  const box = $("layers");
  TYPES.forEach(({ type, note }) => {
    const ex = m.layers.find(l => l.type === type);
    if (!ex) return;
    const lab = document.createElement("label");
    lab.className = "layer";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = state.on[type];
    input.onchange = () => { state.on[type] = input.checked; draw(); };
    const sw = document.createElement("span");
    sw.className = "sw" + (type === "backscatter" ? " grad" : "");
    if (ex.color) sw.style.background = ex.color;
    const name = document.createElement("span");
    name.textContent = ex.label_pt + (note ? ` (${note})` : "");
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = SOURCE_LABEL[ex.source] || ex.source;
    lab.append(input, sw, name, tag);
    box.appendChild(lab);
  });
}

function go(i) {
  const m = state.m;
  if (!m) return;
  state.i = Math.max(0, Math.min(m.dates.length - 1, i));
  $("date").value = state.i;
  draw();
}

function draw() {
  const m = state.m;
  if (!m) return;
  const i = state.i, d = m.dates[i], prev = i > 0 ? m.dates[i - 1] : null;
  $("dateLabel").textContent = fmtDate(d);
  $("prev").disabled = i === 0;
  $("next").disabled = i === m.dates.length - 1;
  $("period").textContent = prev
    ? `Mudanças entre ${fmtDate(prev)} e ${fmtDate(d)}.`
    : "Primeira data: só água. Mudanças aparecem a partir da segunda.";

  overlays.forEach(o => map.removeLayer(o));
  overlays = [];
  // Desenha na ordem de TYPES invertida para água ficar por cima do radar.
  [...TYPES].reverse().forEach(({ type }) => {
    if (!state.on[type]) return;
    m.layers
      .filter(l => l.type === type && (l.date === d || (type === "dried_then_burned" && i === m.dates.length - 1)))
      .forEach(l => overlays.push(L.imageOverlay("data/" + l.file, l.bounds, { opacity: state.opacity }).addTo(map)));
  });

  firmsLayer.clearLayers();
  let nFirms = 0;
  if ($("firms").checked) {
    state.firms
      .filter(f => f.properties.date > (prev || "0000") && f.properties.date <= d)
      .forEach(f => {
        nFirms++;
        const [lon, lat] = f.geometry.coordinates;
        L.circleMarker([lat, lon], { radius: 4, color: "#7a4a00", weight: 1, fillColor: "#ffb000", fillOpacity: 0.9 })
          .bindTooltip(`Foco ${f.properties.date}${f.properties.frp ? ` · FRP ${f.properties.frp} MW` : ""}`)
          .addTo(firmsLayer);
      });
  }
  showCards(d, prev, nFirms);
}

function showCards(d, prev, nFirms) {
  const s = state.m.stats || {};
  const day = (s.per_date || {})[d] || {};
  const pair = prev ? (s.per_pair || {})[`${prev}_${d}`] || {} : {};
  const cards = [
    ["Água aberta", day.open_water_km2, "km²"],
    ["Secou no período", prev ? pair.dried_km2 : null, "km²"],
    ["Queimada (NISAR)", prev ? pair.burn_km2 : null, "km²"],
    ["Focos FIRMS", $("firms").checked ? nFirms : null, ""],
  ];
  $("cards").innerHTML = cards
    .map(([k, v, u]) => `<div class="card"><div class="v">${fmtNum(v)}${v != null && u ? ` <small>${u}</small>` : ""}</div><div class="k">${k}</div></div>`)
    .join("");
}

function showAnalysis(s) {
  const t = s && s.analysis && s.analysis.dried_vs_always_dry;
  if (!t || !t.odds_ratio) return;
  $("analysis").hidden = false;
  const pct = x => (x * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  $("analysisText").textContent =
    `Nas áreas que secaram, ${pct(t.burn_rate_a)}% queimaram; nas que estavam sempre secas, ${pct(t.burn_rate_b)}%. ` +
    `Razão de chances ${fmtNum(t.odds_ratio)} (IC 95%: ${fmtNum(t.ci95[0])} a ${fmtNum(t.ci95[1])}).`;
}
