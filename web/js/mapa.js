// Wetland Pulse: aba "Mapa". Mapa esquemático (não é imagem de satélite) com
// uma régua de comparação de verdade, arrastável, entre duas passagens reais do NISAR.
"use strict";

(function () {
  const $ = id => document.getElementById(id);
  const W = 1140, H = 836;
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const fmtDate = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]} ${y}`; };

  let dates = [];
  let state = { leftIdx: 0, rightIdx: 0, sliderX: 600 };

  fetch("data/water_series.json")
    .then(r => { if (!r.ok) throw new Error("sem arquivo"); return r.json(); })
    .then(data => {
      dates = (data.points || []).filter(p => p.kind === "observado").sort((a, b) => a.ds.localeCompare(b.ds));
      if (!dates.length) return;
      state.leftIdx = 0;
      state.rightIdx = dates.length - 1;
      buildCanvas();
      buildDateList();
      updateAll();
    })
    .catch(err => console.error("Falha ao carregar water_series.json", err));

  function radiusFor(km2) {
    const r = 70 * Math.sqrt(km2 / 250);
    return Math.max(55, Math.min(190, r));
  }

  function buildCanvas() {
    const canvas = $("mapCanvas");
    canvas.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Área de estudo com régua de comparação entre duas datas">
        <defs>
          <pattern id="scan" width="40" height="40" patternUnits="userSpaceOnUse" patternTransform="rotate(12 690 400)">
            <rect width="40" height="2" fill="var(--texto-secundario)" opacity="0.45" />
          </pattern>
          <clipPath id="clipLeft"><rect id="clipLeftRect" x="0" y="0" width="${state.sliderX}" height="${H}" /></clipPath>
          <clipPath id="clipRight"><rect id="clipRightRect" x="${state.sliderX}" y="0" width="${W - state.sliderX}" height="${H}" /></clipPath>
        </defs>

        <rect width="${W}" height="${H}" fill="var(--fundo-mapa-terra)" />
        <ellipse cx="180" cy="90" rx="260" ry="210" fill="var(--fundo-mapa-vegetacao)" opacity="0.8" />
        <ellipse cx="1050" cy="140" rx="230" ry="200" fill="var(--fundo-mapa-vegetacao)" opacity="0.8" />
        <ellipse cx="1000" cy="690" rx="260" ry="210" fill="var(--fundo-mapa-vegetacao)" opacity="0.7" />
        <ellipse cx="150" cy="700" rx="210" ry="180" fill="var(--fundo-mapa-vegetacao)" opacity="0.6" />

        <path d="M -20 220 Q 320 320 620 260 Q 900 210 1160 420" fill="none" stroke="var(--agua-principal)" stroke-width="9" stroke-linecap="round" opacity="0.45" />

        <rect x="520" y="-300" width="340" height="1400" transform="rotate(12 690 400)" fill="var(--confianca-baixa)" opacity="0.4" stroke="var(--texto-principal)" stroke-width="2" />
        <rect x="520" y="-300" width="340" height="1400" transform="rotate(12 690 400)" fill="url(#scan)" />

        <rect x="160" y="100" width="940" height="640" fill="none" stroke="var(--texto-principal)" stroke-width="1.5" stroke-dasharray="6 4" />
        <text x="172" y="112" font-size="11" font-weight="600" fill="var(--texto-principal)" letter-spacing="0.6">ÁREA DE ESTUDO</text>
        <text x="164" y="754" font-size="10" fill="var(--texto-secundario)">-17.5°, -58.3°</text>
        <text x="938" y="104" font-size="10" fill="var(--texto-secundario)" text-anchor="end">-16.5°, -57.3°</text>

        <g>
          <rect x="560" y="20" width="170" height="28" rx="14" fill="var(--fundo-superficie)" />
          <text x="645" y="39" font-size="12" font-weight="600" fill="var(--texto-principal)" text-anchor="middle">Trilha 132 ↑ (ascendente)</text>
        </g>

        <g clip-path="url(#clipLeft)">
          <ellipse id="waterLeft" cx="480" cy="380" rx="150" ry="100" fill="var(--agua-principal)" opacity="0.85" />
        </g>
        <g clip-path="url(#clipRight)">
          <ellipse id="waterRight" cx="480" cy="380" rx="120" ry="80" fill="var(--agua-principal)" opacity="0.5" />
        </g>

        <line id="sliderLine" x1="${state.sliderX}" y1="0" x2="${state.sliderX}" y2="${H}" stroke="var(--texto-principal)" stroke-width="3" />

        <g id="handleGroup" class="slider-handle-svg" style="cursor:ew-resize" transform="translate(${state.sliderX} ${H / 2})">
          <circle r="28" fill="var(--fundo-superficie)" stroke="var(--texto-principal)" stroke-width="2" />
          <path d="M -15 -7 L -22 0 L -15 7 M 15 -7 L 22 0 L 15 7 M -22 0 L 22 0" fill="none" stroke="var(--texto-principal)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </g>

        <g id="labelLeftGroup" transform="translate(40 40)">
          <rect id="labelLeftBg" x="0" y="0" width="150" height="28" rx="14" fill="var(--fundo-superficie)" />
          <text id="labelLeft" x="75" y="19" font-size="12" font-weight="600" fill="var(--agua-principal)" text-anchor="middle"></text>
        </g>
        <g id="labelRightGroup" transform="translate(${W - 190} 40)">
          <rect id="labelRightBg" x="0" y="0" width="150" height="28" rx="14" fill="var(--fundo-superficie)" />
          <text id="labelRight" x="75" y="19" font-size="12" font-weight="600" fill="var(--texto-principal)" text-anchor="middle"></text>
        </g>

        <text x="1080" y="38" font-size="13" font-weight="700" fill="var(--texto-principal)" text-anchor="middle">N</text>
        <path d="M 1080 60 L 1080 46 L 1075 52 M 1080 46 L 1085 52" fill="none" stroke="var(--texto-principal)" stroke-width="1.5" />

        <path d="M 40 696 L 140 696 M 40 690 L 40 702 M 140 690 L 140 702" fill="none" stroke="var(--texto-principal)" stroke-width="1.5" />
        <text x="40" y="716" font-size="11" fill="var(--texto-secundario)">~50 km</text>
      </svg>`;

    const svg = canvas.querySelector("svg");
    const handle = $("handleGroup");
    let dragging = false;

    function toSvgX(clientX) {
      const rect = svg.getBoundingClientRect();
      const scale = W / rect.width;
      return Math.max(80, Math.min(W - 80, (clientX - rect.left) * scale));
    }
    function startDrag(ev) {
      dragging = true;
      handle.setPointerCapture(ev.pointerId);
    }
    function moveDrag(ev) {
      if (!dragging) return;
      state.sliderX = toSvgX(ev.clientX);
      applySlider();
    }
    function endDrag() { dragging = false; }

    handle.addEventListener("pointerdown", startDrag);
    handle.addEventListener("pointermove", moveDrag);
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  }

  function applySlider() {
    $("clipLeftRect").setAttribute("width", state.sliderX);
    $("clipRightRect").setAttribute("x", state.sliderX);
    $("clipRightRect").setAttribute("width", W - state.sliderX);
    $("sliderLine").setAttribute("x1", state.sliderX);
    $("sliderLine").setAttribute("x2", state.sliderX);
    $("handleGroup").setAttribute("transform", `translate(${state.sliderX} ${H / 2})`);
  }

  function buildDateList() {
    $("dateList").innerHTML = dates.map((p, i) => (
      `<div class="date-row" data-idx="${i}">
        <span>${fmtDate(p.ds).replace(` ${p.ds.slice(0, 4)}`, "")}</span>
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
      if (btn.dataset.side === "left") state.leftIdx = idx; else state.rightIdx = idx;
      updateAll();
    });
  }

  function updateAll() {
    const left = dates[state.leftIdx], right = dates[state.rightIdx];
    $("waterLeft").setAttribute("rx", radiusFor(left.observed_km2));
    $("waterLeft").setAttribute("ry", radiusFor(left.observed_km2) * 0.67);
    $("waterRight").setAttribute("rx", radiusFor(right.observed_km2));
    $("waterRight").setAttribute("ry", radiusFor(right.observed_km2) * 0.67);
    $("labelLeft").textContent = `Esquerda · ${fmtDate(left.ds)}`;
    $("labelRight").textContent = `Direita · ${fmtDate(right.ds)}`;

    document.querySelectorAll(".date-row").forEach(row => {
      const idx = Number(row.dataset.idx);
      row.querySelector('[data-side="left"]').classList.toggle("active-e", idx === state.leftIdx);
      row.querySelector('[data-side="right"]').classList.toggle("active-d", idx === state.rightIdx);
    });
  }
})();
