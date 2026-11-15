// Wetland Pulse: aba "Série temporal", contrato de dados v2
// (web/data/manifest.json + series/model.json + series/metrics.json).
// Ver docs/DATA_CONTRACT.md. Detecção (kind:"fit") e projeção (kind:"forecast")
// nunca são misturadas no mesmo eixo/unidade: detecção em km², projeção em % (docs/DATA_REVIEW.md).
"use strict";

(function () {
  const $ = id => document.getElementById(id);
  const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const fmtDate = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]} ${y}`; };
  const fmtShort = ds => { const [y, m, d] = ds.split("-").map(Number); return `${d} ${MESES[m - 1]}`; };
  const fmtNum = (n, max = 0) => (n == null ? "—" : Number(n).toLocaleString("pt-BR", { maximumFractionDigits: max }));
  const fmtSigned = (n, max = 0) => (n == null ? "—" : `${n >= 0 ? "+" : ""}${fmtNum(n, max)}`);

  Promise.all([
    fetch("data/manifest.json").then(r => { if (!r.ok) throw new Error("manifest"); return r.json(); }),
  ]).then(([manifest]) =>
    Promise.all([
      Promise.resolve(manifest),
      fetch("data/series/" + manifest.series.model).then(r => r.json()),
      fetch("data/series/" + manifest.series.metrics).then(r => r.json()),
    ])
  )
    .then(([manifest, model, metrics]) => renderSeries(manifest, model, metrics))
    .catch(err => {
      console.error("Falha ao carregar a série temporal", err);
      const box = $("chartBox");
      if (box) box.innerHTML = '<p class="muted small">Sem dados. Rode <code>python -m pantanal_sar.cli timeseries</code>.</p>';
    });

  function renderSeries(manifest, model, metrics) {
    const fit = model.filter(r => r.kind === "fit").sort((a, b) => a.date.localeCompare(b.date));
    const forecast = model.filter(r => r.kind === "forecast").sort((a, b) => a.date.localeCompare(b.date));
    if (!fit.length) return;
    const last = fit[fit.length - 1];

    renderStatus(last);
    renderCards(last, metrics);
    renderLegend();
    renderChart(fit);
    renderForecastPanel(forecast, manifest.forecast);
    renderValidation(metrics);
    renderLimitations(metrics);
    renderSources(manifest.sources || []);
  }

  function renderSources(sources) {
    const box = $("sourcesList");
    if (!box) return;
    box.innerHTML = sources.map((s, i) => {
      const chip = s.calibrated
        ? '<span class="chip chip--primary"><span class="dot"></span><span class="label">Calibrado</span></span>'
        : '<span class="chip chip--pending"><span class="dot"></span><span class="label">Não calibrado</span></span>';
      const last = i === sources.length - 1 ? "" : 'style="border-bottom:1px solid var(--borda-padrao);"';
      return `<div class="evidence-row" ${last}>
        <div><strong>${s.label_pt}</strong><p class="muted small">${s.citation} · ${s.n_obs} observações (${s.first} a ${s.last}).</p></div>
        ${chip}
      </div>`;
    }).join("");
  }

  function renderStatus(last) {
    const el = $("statusChip");
    const out = !!last.anomaly;
    el.className = "chip " + (out ? "chip--bad" : "chip--ok");
    el.querySelector(".label").textContent = last.label_pt || (out ? "Fora da faixa esperada (95%)" : "Observado");
  }

  function renderCards(last, metrics) {
    const perMonth = metrics.trend_km2_per_day != null ? metrics.trend_km2_per_day * 30 : null;
    const range = metrics.trend_range_km2_per_day;
    const cards = [
      {
        label: "Água aberta (última passagem)",
        value: `${fmtNum(last.observed_km2)} km²`,
        detail: `Medido em ${fmtDate(last.date)} · limiar ±1 dB: ${fmtNum(last.method_lo_km2)}–${fmtNum(last.method_hi_km2)} km²`,
      },
      {
        label: "Esperado (modelo Prophet)",
        value: `${fmtNum(last.expected_km2)} km²`,
        detail: `Faixa esperada (95%): ${fmtNum(last.lo95_km2)}–${fmtNum(last.hi95_km2)} km²`,
      },
      {
        label: "Tendência",
        value: perMonth != null ? `${fmtSigned(perMonth)} km²/mês` : "—",
        detail: range ? `Sensível ao limiar: ${fmtSigned(range.min * 30)} a ${fmtSigned(range.max * 30)} km²/mês` : "Tendência + changepoints (Prophet)",
      },
    ];
    $("metricCards").innerHTML = cards.map(c => (
      `<div class="card"><p class="label">${c.label}</p><p class="value">${c.value}</p><p class="detail">${c.detail}</p></div>`
    )).join("");
  }

  function lineSwatch() {
    return `<svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true">
      <line x1="1" y1="5" x2="17" y2="5" stroke="var(--agua-principal)" stroke-width="2" stroke-linecap="round" />
    </svg>`;
  }

  function renderLegend() {
    const items = [
      { kind: "dot", text: "Medido (NISAR)" },
      { kind: "line", text: "Esperado (modelo Prophet)" },
      { kind: "band", text: "Faixa esperada (95%)" },
      { kind: "whisker", text: "Incerteza do limiar (±1 dB)" },
    ];
    $("legend").innerHTML = items.map(it => {
      const sw = it.kind === "dot" ? '<span class="sw-dot"></span>'
        : it.kind === "band" ? '<span class="sw-band"></span>'
        : it.kind === "whisker" ? '<span class="sw-band" style="background:var(--texto-secundario);width:3px;"></span>'
        : lineSwatch();
      return `<span class="legend-item">${sw}${it.text}</span>`;
    }).join("");
  }

  function renderChart(fit) {
    const W = 1000, H = 300, L = 48, R = 16, T = 12, B = 28;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;

    const t0 = new Date(fit[0].date).getTime();
    const t1 = new Date(fit[fit.length - 1].date).getTime();
    const span = Math.max(1, t1 - t0);
    const x = ds => x0 + ((new Date(ds).getTime() - t0) / span) * (x1 - x0);

    const vals = fit.flatMap(p => [p.lo95_km2, p.hi95_km2, p.method_lo_km2, p.method_hi_km2, p.observed_km2].filter(v => v != null));
    const vMin = Math.max(0, Math.min(...vals) * 0.92);
    const vMax = Math.max(...vals) * 1.08;
    const vSpan = Math.max(1, vMax - vMin);
    const y = v => y1 - ((v - vMin) / vSpan) * (y1 - y0);

    const bandPath = () => {
      const up = fit.map(p => `${x(p.date).toFixed(2)} ${y(p.hi95_km2).toFixed(2)}`);
      const down = [...fit].reverse().map(p => `${x(p.date).toFixed(2)} ${y(p.lo95_km2).toFixed(2)}`);
      return `M ${up.join(" L ")} L ${down.join(" L ")} Z`;
    };
    const linePath = `M ${fit.map(p => `${x(p.date).toFixed(2)} ${y(p.expected_km2).toFixed(2)}`).join(" L ")}`;

    const gridN = 4;
    const gridLines = Array.from({ length: gridN + 1 }, (_, i) => {
      const v = vMin + (vSpan * i) / gridN;
      const yy = y(v);
      return `<line x1="${x0}" y1="${yy.toFixed(2)}" x2="${x1}" y2="${yy.toFixed(2)}" stroke="var(--borda-padrao)" stroke-width="1" />
        <text x="${x0 - 8}" y="${(yy + 4).toFixed(2)}" font-size="10" fill="var(--texto-secundario)" text-anchor="end">${fmtNum(v)}</text>`;
    }).join("");

    const ticks = fit.map(p => (
      `<text x="${x(p.date).toFixed(2)}" y="${y1 + 18}" font-size="10" fill="var(--texto-secundario)" text-anchor="middle">${fmtShort(p.date)}</text>`
    )).join("");

    const whiskers = fit.map(p => {
      if (p.method_lo_km2 == null || p.method_hi_km2 == null) return "";
      const cx = x(p.date).toFixed(2);
      const yLo = y(p.method_lo_km2).toFixed(2), yHi = y(p.method_hi_km2).toFixed(2);
      return `<line x1="${cx}" y1="${yLo}" x2="${cx}" y2="${yHi}" stroke="var(--texto-secundario)" stroke-width="2" stroke-linecap="round" opacity="0.55" />`;
    }).join("");

    const dots = fit.map(p => {
      const cx = x(p.date).toFixed(2), cy = y(p.observed_km2).toFixed(2);
      const fill = p.anomaly ? "var(--status-critico)" : "var(--agua-principal)";
      return `<circle cx="${cx}" cy="${cy}" r="4.5" fill="${fill}" stroke="var(--fundo-superficie)" stroke-width="1.5">
        <title>${fmtDate(p.date)}: medido ${fmtNum(p.observed_km2)} km² (limiar ±1 dB: ${fmtNum(p.method_lo_km2)}–${fmtNum(p.method_hi_km2)}), esperado ${fmtNum(p.expected_km2)} km²${p.anomaly ? ", fora da faixa esperada (95%)" : ""}</title>
      </circle>`;
    }).join("");

    $("chartBox").innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Água aberta medida pelo NISAR, com o esperado pelo modelo Prophet">
        ${gridLines}
        <path d="${bandPath()}" fill="var(--agua-clara)" opacity="0.75" />
        <path d="${linePath}" fill="none" stroke="var(--agua-principal)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        ${whiskers}
        ${dots}
        <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}" stroke="var(--borda-padrao)" stroke-width="1" />
        ${ticks}
      </svg>`;
  }

  function renderForecastPanel(forecast, forecastMeta) {
    const section = $("forecastPanel");
    if (!section) return;
    if (!forecast.length) { section.hidden = true; return; }
    section.hidden = false;

    const W = 1000, H = 180, L = 48, R = 16, T = 16, B = 28;
    const x0 = L, x1 = W - R, y0 = T, y1 = H - B;
    const dates = forecast.map(p => p.date);
    const t0 = new Date(dates[0]).getTime(), t1 = new Date(dates[dates.length - 1]).getTime();
    const span = Math.max(1, t1 - t0);
    const x = ds => dates.length > 1 ? x0 + ((new Date(ds).getTime() - t0) / span) * (x1 - x0) : (x0 + x1) / 2;

    const vals = forecast.flatMap(p => [p.lo80_pct, p.hi80_pct, p.forecast_pct]).filter(v => v != null);
    vals.push(0);
    const vMin = Math.min(...vals) * 1.15, vMax = Math.max(...vals) * 1.15;
    const vSpan = Math.max(1, vMax - vMin);
    const y = v => y1 - ((v - vMin) / vSpan) * (y1 - y0);

    const bandPath = `M ${forecast.map(p => `${x(p.date).toFixed(2)} ${y(p.hi80_pct).toFixed(2)}`).join(" L ")} L ${[...forecast].reverse().map(p => `${x(p.date).toFixed(2)} ${y(p.lo80_pct).toFixed(2)}`).join(" L ")} Z`;
    const linePath = `M ${forecast.map(p => `${x(p.date).toFixed(2)} ${y(p.forecast_pct).toFixed(2)}`).join(" L ")}`;
    const zeroY = y(0).toFixed(2);

    const dots = forecast.map(p => {
      const cx = x(p.date).toFixed(2), cy = y(p.forecast_pct).toFixed(2);
      const flag = p.check_same_direction === true ? "✓ Sentinel-1: mesma direção" : p.check_same_direction === false ? "Sentinel-1: direção diferente" : "";
      return `<circle cx="${cx}" cy="${cy}" r="4" fill="var(--agua-principal)" stroke="var(--fundo-superficie)" stroke-width="1.5">
        <title>${fmtDate(p.date)}: ${fmtSigned(p.forecast_pct, 1)}% (faixa 80%: ${fmtSigned(p.lo80_pct, 1)}% a ${fmtSigned(p.hi80_pct, 1)}%)${flag ? " · " + flag : ""}</title>
      </circle>`;
    }).join("");
    const ticks = forecast.map(p => `<text x="${x(p.date).toFixed(2)}" y="${y1 + 18}" font-size="10" fill="var(--texto-secundario)" text-anchor="middle">${fmtShort(p.date)}</text>`).join("");

    const sourceLabel = forecastMeta && forecastMeta.source === "opera_dswx_hls" ? "OPERA DSWx-HLS" : (forecastMeta ? forecastMeta.source : "—");
    $("forecastTitle").textContent = `Projeção (${sourceLabel}, variação relativa)`;
    $("forecastWarning").textContent = forecastMeta && forecastMeta.level_calibrated === false
      ? "Nível em km² não calibrado para esta fonte; os valores abaixo são variação percentual relativa à última observação, não uma nova medição do radar."
      : "";
    $("forecastBox").innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Projeção de curto prazo em variação percentual">
        <line x1="${x0}" y1="${zeroY}" x2="${x1}" y2="${zeroY}" stroke="var(--borda-padrao)" stroke-width="1" stroke-dasharray="3 3" />
        <text x="${x0 - 8}" y="${(Number(zeroY) + 4)}" font-size="10" fill="var(--texto-secundario)" text-anchor="end">0%</text>
        <path d="${bandPath}" fill="var(--confianca-baixa)" opacity="0.35" />
        <path d="${linePath}" fill="none" stroke="var(--agua-principal)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="6 5" />
        ${dots}
        <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}" stroke="var(--borda-padrao)" stroke-width="1" />
        ${ticks}
      </svg>`;
  }

  function renderValidation(metrics) {
    const h = metrics.holdout || {};
    $("validationCaption").textContent =
      `Detecção: faixa esperada de ${Math.round((metrics.detection_interval || 0.95) * 100)}%. Validação fora da amostra: MAE ${fmtNum(h.mae_km2)} km² · MAPE ${fmtNum(h.mape_pct, 1)}% (${h.desc || "-"}).`;
  }

  function renderLimitations(metrics) {
    const box = $("limitationsList");
    if (!box) return;
    const items = metrics.limitations_pt || [];
    box.innerHTML = items.map(t => `<li>${t}</li>`).join("");
  }
})();
