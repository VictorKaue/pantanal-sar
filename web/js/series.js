// Wetland Pulse: aba "Série temporal". Lê data/water_series.json (contrato em
// src/pantanal_sar/timeseries.py) e desenha os cards, o gráfico e o rótulo de validação.
"use strict";

(function () {
  const $ = id => document.getElementById(id);
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const fmtDate = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]} ${y}`; };
  const fmtShort = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]}`; };
  const fmtNum = (n, max = 0) => (n == null ? "—" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: max }));

  fetch("data/water_series.json")
    .then(r => { if (!r.ok) throw new Error("sem arquivo"); return r.json(); })
    .then(renderSeries)
    .catch(err => console.error("Falha ao carregar water_series.json", err));

  function renderSeries(data) {
    const points = [...(data.points || [])].sort((a, b) => a.ds.localeCompare(b.ds));
    if (!points.length) return;
    const observed = points.filter(p => p.kind === "observado");
    const future = points.filter(p => p.kind !== "observado");
    const last = observed[observed.length - 1];
    const first = observed[0];
    const labels = data.labels_pt || {};
    const metrics = data.metrics || {};

    renderStatus(last);
    renderCards(first, last, future, metrics);
    renderLegend(labels);
    renderChart(points, observed, future);
    $("validationCaption").textContent =
      `Validação fora da amostra: MAE ${fmtNum(metrics.mae_km2)} km² · MAPE ${fmtNum(metrics.mape_pct, 1)}% (${metrics.holdout || "-"}).`;
  }

  function renderStatus(last) {
    const anomalous = !!last.is_anomaly;
    const el = $("statusChip");
    el.className = "chip " + (anomalous ? "chip--bad" : "chip--ok");
    el.querySelector(".label").textContent = anomalous ? "Fora do esperado" : "Dentro do esperado";
  }

  function renderCards(first, last, future, metrics) {
    const days = (new Date(last.ds) - new Date(first.ds)) / 86400000;
    const perMonth = days > 0 ? ((last.expected_km2 - first.expected_km2) / days) * 30 : 0;
    const cards = [
      {
        label: "Água aberta (última passagem)",
        value: `${fmtNum(last.observed_km2)} km²`,
        detail: `Medido em ${fmtDate(last.ds)} · esperado ${fmtNum(last.expected_km2)} km²`,
      },
      {
        label: "Tendência do modelo",
        value: `${perMonth >= 0 ? "+" : ""}${fmtNum(perMonth)} km²/mês`,
        detail: "Prophet: tendência + changepoints, sem sazonalidade anual (fase 1)",
      },
    ];
    $("metricCards").innerHTML = cards.map(c => (
      `<div class="card"><p class="label">${c.label}</p><p class="value">${c.value}</p><p class="detail">${c.detail}</p></div>`
    )).join("");
  }

  function lineSwatch(dashed) {
    return `<svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true">
      <line x1="1" y1="5" x2="17" y2="5" stroke="var(--agua-principal)" stroke-width="2" stroke-linecap="round"${dashed ? ' stroke-dasharray="4 3"' : ""} />
    </svg>`;
  }

  function renderLegend(labels) {
    const items = [
      { kind: "dot", text: labels.observado || "Medido (NISAR)" },
      { kind: "line", text: labels.esperado || "Esperado (modelo Prophet)" },
      { kind: "dashed", text: labels.projecao || "Projeção (não é medição)" },
      { kind: "band", text: labels.intervalo || "Intervalo de incerteza" },
    ];
    $("legend").innerHTML = items.map(it => {
      const sw = it.kind === "dot" ? '<span class="sw-dot"></span>'
        : it.kind === "band" ? '<span class="sw-band"></span>'
        : lineSwatch(it.kind === "dashed");
      return `<span class="legend-item">${sw}${it.text}</span>`;
    }).join("");
  }

  function renderChart(points, observed, future) {
    const W = 1000, H = 300, L = 48, R = 16, T = 12, B = 28;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;

    const t0 = new Date(points[0].ds).getTime();
    const t1 = new Date(points[points.length - 1].ds).getTime();
    const span = Math.max(1, t1 - t0);
    const x = ds => x0 + ((new Date(ds).getTime() - t0) / span) * (x1 - x0);

    const vals = points.flatMap(p => [p.lower_km2, p.upper_km2].filter(v => v != null));
    observed.forEach(p => { if (p.observed_km2 != null) vals.push(p.observed_km2); });
    const vMin = Math.max(0, Math.min(...vals) * 0.92);
    const vMax = Math.max(...vals) * 1.08;
    const vSpan = Math.max(1, vMax - vMin);
    const y = v => y1 - ((v - vMin) / vSpan) * (y1 - y0);

    const bridge = observed[observed.length - 1];
    const bandPath = pts => {
      const up = pts.map(p => `${x(p.ds).toFixed(2)} ${y(p.upper_km2).toFixed(2)}`);
      const down = [...pts].reverse().map(p => `${x(p.ds).toFixed(2)} ${y(p.lower_km2).toFixed(2)}`);
      return `M ${up.join(" L ")} L ${down.join(" L ")} Z`;
    };
    const linePath = pts => `M ${pts.map(p => `${x(p.ds).toFixed(2)} ${y(p.expected_km2).toFixed(2)}`).join(" L ")}`;

    const bandObserved = observed.length > 1 ? bandPath(observed) : "";
    const bandFuture = future.length ? bandPath([bridge, ...future]) : "";
    const lineObserved = linePath(observed);
    const lineFuture = future.length ? linePath([bridge, ...future]) : "";

    const gridN = 4;
    const gridLines = Array.from({ length: gridN + 1 }, (_, i) => {
      const v = vMin + (vSpan * i) / gridN;
      const yy = y(v);
      return `<line x1="${x0}" y1="${yy.toFixed(2)}" x2="${x1}" y2="${yy.toFixed(2)}" stroke="var(--borda-padrao)" stroke-width="1" />
        <text x="${x0 - 8}" y="${(yy + 4).toFixed(2)}" font-size="10" fill="var(--texto-secundario)" text-anchor="end">${fmtNum(v)}</text>`;
    }).join("");

    const ticks = points.map(p => (
      `<text x="${x(p.ds).toFixed(2)}" y="${y1 + 18}" font-size="10" fill="var(--texto-secundario)" text-anchor="middle">${fmtShort(p.ds)}</text>`
    )).join("");

    const dots = observed.map(p => {
      const cx = x(p.ds).toFixed(2), cy = y(p.observed_km2).toFixed(2);
      const fill = p.is_anomaly ? "var(--status-critico)" : "var(--agua-principal)";
      return `<circle cx="${cx}" cy="${cy}" r="4.5" fill="${fill}" stroke="var(--fundo-superficie)" stroke-width="1.5">
        <title>${fmtDate(p.ds)}: medido ${fmtNum(p.observed_km2)} km², esperado ${fmtNum(p.expected_km2)} km²${p.is_anomaly ? " (fora do intervalo)" : ""}</title>
      </circle>`;
    }).join("");

    const todayX = x(bridge.ds).toFixed(2);
    const nextProj = future[0];
    const annotation = nextProj
      ? `<text x="${(x(nextProj.ds) + 10).toFixed(2)}" y="${(y(nextProj.expected_km2) - 10).toFixed(2)}" font-size="11" font-weight="600" fill="var(--texto-principal)">${fmtNum(nextProj.expected_km2)} km² · próxima passagem (projeção)</text>`
      : "";

    $("chartBox").innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Água aberta ao longo do tempo: medido, esperado e projeção">
        ${gridLines}
        ${bandObserved ? `<path d="${bandObserved}" fill="var(--agua-clara)" opacity="0.75" />` : ""}
        ${bandFuture ? `<path d="${bandFuture}" fill="var(--confianca-baixa)" opacity="0.4" />` : ""}
        <line x1="${todayX}" y1="${y0}" x2="${todayX}" y2="${y1}" stroke="var(--texto-secundario)" stroke-width="1" stroke-dasharray="2 3" />
        <path d="${lineObserved}" fill="none" stroke="var(--agua-principal)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        ${lineFuture ? `<path d="${lineFuture}" fill="none" stroke="var(--agua-principal)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="6 5" />` : ""}
        ${annotation}
        ${dots}
        <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}" stroke="var(--borda-padrao)" stroke-width="1" />
        ${ticks}
      </svg>`;
  }
})();
