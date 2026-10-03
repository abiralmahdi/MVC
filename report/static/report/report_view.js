/* Renders every diagram of a report and builds the PDF. */
(function () {
  'use strict';

  const MVC = window.MVC;
  const configs = JSON.parse(document.getElementById('diagram-configs').textContent);
  const byId = (id) => document.getElementById(id);
  const THEME = MVC.chartTheme;
  const colorFor = (i, alpha = 1) => MVC.seriesColor(i, alpha);
  // Ink for the dark screen and for the white PDF capture.
  const INK_SCREEN = { text: THEME.INK.secondary, muted: THEME.INK.muted, title: THEME.INK.primary, grid: THEME.INK.grid, border: THEME.SURFACE.panel };
  const INK_PAPER = { text: '#374151', muted: '#6b7280', title: '#111827', grid: 'rgba(17,24,39,0.10)', border: '#ffffff' };
  const timeFormat = new Intl.DateTimeFormat('en-GB', { timeZone: MVC.timeZone, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
  const renderers = {};
  const pending = [];

  function status(config, text, kind = 'secondary') {
    const el = byId(`diagram-status-${config.id}`);
    if (el) { el.textContent = text || ''; el.className = `small diagram-status text-${kind === 'secondary' ? 'muted' : kind}`; }
  }

  function fmt(value, digits = 2) {
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: digits }) : '';
  }

  const baseScales = () => ({
    x: { ticks: { color: INK_SCREEN.muted }, grid: { display: false } },
    y: { ticks: { color: INK_SCREEN.muted }, grid: { color: INK_SCREEN.grid }, border: { display: false } },
  });

  /** Re-colour every Chart.js chart inside ``root`` for screen or paper. */
  function applyInk(root, ink) {
    root.querySelectorAll('canvas').forEach(canvas => {
      const chart = window.Chart && Chart.getChart(canvas);
      if (!chart) return;
      const o = chart.options;
      o.color = ink.text;
      if (o.plugins.legend) o.plugins.legend.labels.color = ink.text;
      if (o.plugins.title) o.plugins.title.color = ink.title;
      Object.values(o.scales || {}).forEach(scale => {
        if (scale.ticks) scale.ticks.color = ink.muted;
        if (scale.title) scale.title.color = ink.muted;
        if (scale.grid && scale.grid.display !== false) scale.grid.color = ink.grid;
      });
      chart.data.datasets.forEach(ds => { if (chart.config.type === 'pie' || chart.config.type === 'doughnut') ds.borderColor = ink.border; });
      chart.update('none');
    });
  }

  renderers.line = async (config) => {
    const res = await MVC.fetchJSON(`/reports/getLineDiagramData/${config.id}`);
    const byMeter = {};
    res.data.forEach(p => { (byMeter[p.meter_id] = byMeter[p.meter_id] || []).push({ x: p.ts, y: p.value }); });
    const datasets = config.meters.filter(m => byMeter[m.id]).map((m, i) => ({
      label: m.name, data: byMeter[m.id], borderColor: colorFor(i), pointBackgroundColor: colorFor(i), backgroundColor: colorFor(i), pointRadius: 0, borderWidth: 1.6, tension: 0.2,
    }));
    if (!datasets.length) { status(config, `No readings between ${config.start} and ${config.end}.`, 'warning'); return; }
    const scales = baseScales();
    scales.x.type = 'linear';
    scales.x.ticks.callback = (v) => timeFormat.format(new Date(v));
    scales.x.ticks.maxTicksLimit = 10;
    scales.y.grace = '5%';
    scales.y.title = { display: !!res.unit, text: res.unit, color: INK_SCREEN.muted };
    new Chart(byId(`diagram-${config.id}`), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, parsing: false, normalized: true,
        plugins: {
          legend: { position: 'top', align: 'start' },
          title: { display: true, align: 'start', text: `${res.measurement}${res.unit ? ' (' + res.unit + ')' : ''}` },
          tooltip: { callbacks: { title: (items) => items.length ? timeFormat.format(new Date(items[0].parsed.x)) : '' } },
        },
        scales,
      },
    });
    status(config, `${config.start} → ${config.end}`);
  };

  async function periodData(config) {
    const res = await MVC.fetchJSON(`/reports/getDiagramData/${config.id}`);
    if (!res.data.length) { status(config, `No ${res.measurement} data for the selected ${res.period} periods.`, 'warning'); return null; }
    return res;
  }

  renderers.bar = async (config) => {
    const res = await periodData(config);
    if (!res) return;
    const labels = [...new Set(res.data.map(d => d.period))].sort();
    const datasets = config.meters.map((m, i) => ({
      label: m.name,
      data: labels.map(p => { const row = res.data.find(d => d.period === p && d.meter_id === m.id); return row ? row.value : null; }),
      backgroundColor: colorFor(i),
      maxBarThickness: 28,
    })).filter(ds => ds.data.some(v => v !== null));
    const scales = baseScales();
    scales.y.beginAtZero = true;
    scales.y.title = { display: !!res.unit, text: res.unit, color: INK_SCREEN.muted };
    new Chart(byId(`diagram-${config.id}`), {
      type: 'bar',
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { position: 'top', align: 'start' }, title: { display: true, align: 'start', text: `${res.measurement} – ${res.period}${res.cumulative ? ' consumption' : ' average'}` } },
        scales,
      },
    });
    status(config, `${config.start} → ${config.end}`);
  };

  renderers.pie = async (config) => {
    const res = await periodData(config);
    if (!res) return;
    const totals = {};
    res.data.forEach(d => {
      if (res.cumulative) totals[d.meter_id] = (totals[d.meter_id] || 0) + d.value;
      else (totals[d.meter_id] = totals[d.meter_id] || []).push(d.value);
    });
    const meters = config.meters.filter(m => totals[m.id] !== undefined);
    const values = meters.map(m => res.cumulative ? totals[m.id] : totals[m.id].reduce((a, b) => a + b, 0) / totals[m.id].length);
    new Chart(byId(`diagram-${config.id}`), {
      type: 'doughnut',
      data: { labels: meters.map(m => m.name), datasets: [{ data: values.map(v => Math.max(0, v)), backgroundColor: meters.map((_, i) => colorFor(i)), borderColor: INK_SCREEN.border, borderWidth: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, cutout: '58%',
        plugins: {
          legend: { position: 'right' },
          title: { display: true, align: 'start', text: `${res.measurement} – ${res.cumulative ? 'total' : 'average'} ${config.start} → ${config.end}` },
          tooltip: { callbacks: { label: (item) => `${item.label}: ${fmt(values[item.dataIndex])} ${res.unit}` } },
        },
      },
    });
    status(config, '');
  };

  renderers.table = async (config) => {
    const res = await MVC.fetchJSON(`/reports/getTableData/${config.id}`);
    const head = byId(`table-head-${config.id}`);
    const body = byId(`table-body-${config.id}`);
    head.replaceChildren(...res.columns.map(c => Object.assign(document.createElement('th'), { textContent: c })));
    body.replaceChildren(...res.rows.map(row => {
      const tr = document.createElement('tr');
      res.columns.forEach(c => {
        const value = row[c];
        tr.appendChild(Object.assign(document.createElement('td'), { textContent: typeof value === 'number' ? fmt(value, 3) : (value ?? '') }));
      });
      return tr;
    }));
    status(config, res.rows.length ? `${res.rows.length} rows${res.truncated ? ' (truncated to the latest 2000)' : ''}` : 'No readings in this date range.', res.rows.length ? 'secondary' : 'warning');
  };

  function echartsFor(config) {
    if (!window.echarts) throw new Error('Chart library failed to load.');
    return echarts.init(byId(`echarts-${config.id}`));
  }

  renderers.heatmap = async (config) => {
    const res = await MVC.fetchJSON(`/reports/heatmap/${config.id}`);
    if (!res.data.length) { status(config, 'No readings in this date range.', 'warning'); return; }
    const days = [];
    for (let d = new Date(res.start + 'T00:00:00Z'); d <= new Date(res.end + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1)) days.push(d.toISOString().slice(0, 10));
    const index = Object.fromEntries(days.map((d, i) => [d, i]));
    const points = res.data.filter(p => p.day in index).map(p => [index[p.day], p.hour, p.value]);
    const values = points.map(p => p[2]);
    const min = Math.min(...values), max = Math.max(...values);
    echartsFor(config).setOption({
      ...MVC.echartsBase(),
      animation: false,
      tooltip: { ...MVC.echartsBase().tooltip, position: 'top', formatter: (p) => `${days[p.data[0]]} ${String(p.data[1]).padStart(2, '0')}:00<br>${MVC.escapeHtml(res.measurement)}: ${fmt(p.data[2], 3)} ${MVC.escapeHtml(res.unit)}` },
      grid: { height: '72%', top: '4%', left: 56, right: 16 },
      xAxis: { type: 'category', data: days, axisLabel: { color: '#7a8694', fontSize: 10 }, axisTick: { show: false } },
      yAxis: { type: 'category', data: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`), axisLabel: { color: '#7a8694', fontSize: 10 }, axisTick: { show: false }, axisLine: { show: false } },
      visualMap: { min, max: max > min ? max : min + 1, calculable: true, orient: 'horizontal', left: 'center', bottom: '2%', itemHeight: 220, itemWidth: 10, textStyle: { color: '#7a8694' }, inRange: { color: THEME.HEAT } },
      series: [{ type: 'heatmap', data: points, itemStyle: { borderWidth: 1, borderColor: 'rgba(128,128,128,0.15)', borderRadius: 2 } }],
    });
    status(config, `${res.meter} · ${res.measurement} ${res.mode === 'consumption' ? 'consumption per hour' : 'hourly average'}${res.unit ? ' (' + res.unit + ')' : ''}`);
  };

  renderers.sankey = async (config) => {
    const res = await MVC.fetchJSON(`/reports/sankey_data/${config.id}`);
    const measurement = res.measurement;
    const labels = { site: res.site };
    const links = [];
    const colors = { site: THEME.SERIES[0] };
    for (const [bName, building] of Object.entries(res.hierarchy.buildings || {})) {
      const bId = `b:${bName}`; labels[bId] = bName; colors[bId] = THEME.SERIES[2];
      let bSum = 0;
      for (const [aName, area] of Object.entries(building.areas || {})) {
        const aId = `a:${bName}/${aName}`; labels[aId] = aName; colors[aId] = THEME.SERIES[3];
        let aSum = 0;
        for (const [mName, meter] of Object.entries(area.meters || {})) {
          const value = Number((meter.data || {})[measurement]);
          if (!(value > 0)) continue;
          const mId = `m:${bName}/${aName}/${mName}`; labels[mId] = mName; colors[mId] = THEME.SERIES[1];
          const lId = `l:${meter.loadType || 'Unknown'}`; labels[lId] = `Load Type: ${meter.loadType || 'Unknown'}`; colors[lId] = THEME.SERIES[6];
          links.push({ source: aId, target: mId, value }, { source: mId, target: lId, value });
          aSum += value;
        }
        if (aSum > 0) { links.push({ source: bId, target: aId, value: aSum }); bSum += aSum; }
      }
      if (bSum > 0) links.push({ source: 'site', target: bId, value: bSum });
    }
    if (!links.length) { status(config, `No positive ${measurement} values in this period.`, 'warning'); return; }
    const used = [...new Set(links.flatMap(l => [l.source, l.target]))];
    echartsFor(config).setOption({
      ...MVC.echartsBase(),
      animation: false,
      tooltip: { ...MVC.echartsBase().tooltip, trigger: 'item', formatter: (p) => p.dataType === 'edge' ? `${MVC.escapeHtml(labels[p.data.source])} → ${MVC.escapeHtml(labels[p.data.target])}<br/>${fmt(p.data.value)} ${MVC.escapeHtml(res.unit)}` : MVC.escapeHtml(labels[p.data.name]) },
      series: [{ type: 'sankey', data: used.map(id => ({ name: id, itemStyle: { color: colors[id] } })), links, emphasis: { focus: 'adjacency' }, lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.3 }, nodeWidth: 12, nodeGap: 12, right: 140, label: { color: '#7a8694', fontSize: 11, formatter: (p) => labels[p.name] } }],
    });
    status(config, `${measurement}${res.unit ? ' (' + res.unit + ')' : ''} · ${config.period} from ${res.start_date}${res.exact ? '' : ' (latest available)'}`, res.exact ? 'secondary' : 'warning');
  };

  configs.forEach(config => {
    const render = renderers[config.type];
    if (!render) { status(config, `Unknown diagram type ${config.type}`, 'danger'); return; }
    pending.push(render(config).catch(error => status(config, error.message, 'danger')));
  });

  // ---------------- PDF ----------------
  const button = byId('reportButton');
  const pdfStatus = byId('pdf-status');
  button.addEventListener('click', async () => {
    if (!window.html2canvas) { alert('The screenshot library could not be loaded.'); return; }
    button.disabled = true;
    try {
      pdfStatus.textContent = 'Waiting for charts…';
      await Promise.allSettled(pending);
      const containers = document.querySelectorAll('.diagram-container');
      let index = 0;
      for (const container of containers) {
        index += 1;
        pdfStatus.textContent = `Capturing diagram ${index} of ${containers.length}…`;
        container.classList.add('light-mode');
        applyInk(container, INK_PAPER);
        // setTimeout (not requestAnimationFrame) so capture continues if the tab is in the background.
        await new Promise(r => setTimeout(r, 60));
        let canvas;
        try {
          canvas = await html2canvas(container, { backgroundColor: '#ffffff', scale: 2, logging: false });
        } finally {
          container.classList.remove('light-mode');
          applyInk(container, INK_SCREEN);
        }
        await MVC.fetchJSON(`/reports/saveDiagramImage/${container.dataset.diagramId}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: canvas.toDataURL('image/png') }),
        });
      }
      pdfStatus.textContent = 'Building PDF…';
      window.location.href = `/reports/generate_pdf/${button.dataset.reportId}`;
      setTimeout(() => { pdfStatus.textContent = 'PDF downloaded. It is also available under Saved Reports.'; }, 1500);
    } catch (error) {
      pdfStatus.textContent = `PDF failed: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
})();
