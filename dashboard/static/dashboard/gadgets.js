/*
 * MarksVision dashboard gadgets.
 *
 * Every gadget is described by a JSON config rendered by the server
 * (#gadget-configs) and initialised here by type. Nothing is declared in the
 * global scope, so any number of gadgets of the same type can live on a page.
 */
(function () {
  'use strict';

  const MVC = window.MVC;
  const configEl = document.getElementById('gadget-configs');
  const contextEl = document.getElementById('dashboard-context');
  const CTX = contextEl ? JSON.parse(contextEl.textContent) : {};
  const GADGETS = configEl ? JSON.parse(configEl.textContent) : [];

  const LIVE_POLL_MS = 5000;
  const TABLE_POLL_MS = 60000;
  const VALUE_CARD_POLL_MS = 60000;
  const THEME = MVC.chartTheme;
  const TEXT_COLOR = THEME.INK.secondary;
  const TITLE_COLOR = THEME.INK.primary;
  const GRID_COLOR = THEME.INK.grid;

  const byId = (id) => document.getElementById(id);
  const colorFor = (index, alpha = 1) => MVC.seriesColor(index, alpha);

  const timeFormat = new Intl.DateTimeFormat('en-GB', { timeZone: MVC.timeZone, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  const dateTimeFormat = new Intl.DateTimeFormat('en-GB', { timeZone: MVC.timeZone, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  function toNumber(value) {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function formatNumber(value, digits = 2) {
    const n = toNumber(value);
    return n === null ? 'N/A' : n.toLocaleString('en-US', { maximumFractionDigits: digits });
  }

  function setStatus(gadget, message, kind = 'secondary') {
    const el = byId(`gadget-status-${gadget.id}`);
    if (!el) return;
    el.textContent = message || '';
    el.className = `gadget-status small text-${kind}`;
    el.hidden = !message;
  }

  function clearChildren(el) {
    while (el && el.firstChild) el.removeChild(el.firstChild);
  }

  function cell(tag, text, className) {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  /** Parse "YYYY-MM-DD" as a calendar date (no time-zone shifts). */
  function parseISODate(value) {
    const [y, m, d] = value.split('-').map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  }

  function toISODate(date) {
    return date.toISOString().slice(0, 10);
  }

  function addDays(isoDate, days) {
    const d = parseISODate(isoDate);
    d.setUTCDate(d.getUTCDate() + days);
    return toISODate(d);
  }

  /** Repeating task that never overlaps, pauses while the tab is hidden and can be stopped. */
  function poller(task, intervalMs) {
    let timer = null;
    let running = false;
    let stopped = false;
    let loadedOnce = false;

    async function tick() {
      if (stopped) return;
      // Always load once; afterwards skip refreshes while the tab is in the background.
      if (document.hidden && loadedOnce) { schedule(); return; }
      loadedOnce = true;
      if (running) return;
      running = true;
      try { await task(); } catch (e) { /* task reports its own errors */ }
      running = false;
      schedule();
    }

    function schedule() {
      clearTimeout(timer);
      if (!stopped) timer = setTimeout(tick, intervalMs);
    }

    tick();
    return {
      stop() { stopped = true; clearTimeout(timer); },
      start() { if (stopped) { stopped = false; tick(); } },
      refresh() { if (!stopped) tick(); },
    };
  }

  /** Render or update a Chart.js chart in place. */
  function renderChart(canvas, existing, config) {
    if (!canvas || !window.Chart) return null;
    if (existing && existing.config.type === config.type) {
      existing.data = config.data;
      existing.options = config.options;
      existing.update('none');
      return existing;
    }
    if (existing) existing.destroy();
    return new Chart(canvas, config);
  }

  /** Maximize support: gadget.onMaximize(bodyEl) / gadget.onRestore(bodyEl). */
  function bindMaximize(gadget, handlers) {
    const modal = byId(`maximizeModal${gadget.id}`);
    const body = byId(`maximizeModalBody${gadget.id}`);
    if (!modal || !body) return;
    modal.addEventListener('shown.bs.modal', () => handlers.show(body));
    modal.addEventListener('hidden.bs.modal', () => {
      if (handlers.hide) handlers.hide(body);
      clearChildren(body);
    });
  }

  /** A Chart.js gadget with a mirrored chart in the maximize modal. */
  function chartGadget(gadget) {
    const canvas = byId(`gadget-${gadget.id}`);
    let chart = null;
    let maxChart = null;
    let lastConfigFactory = null;

    bindMaximize(gadget, {
      show(body) {
        const maxCanvas = document.createElement('canvas');
        maxCanvas.style.maxHeight = '70vh';
        body.appendChild(maxCanvas);
        if (lastConfigFactory) maxChart = new Chart(maxCanvas, lastConfigFactory(true));
      },
      hide() {
        if (maxChart) maxChart.destroy();
        maxChart = null;
      },
    });

    return {
      draw(configFactory) {
        lastConfigFactory = configFactory;
        chart = renderChart(canvas, chart, configFactory(false));
        requestRelayout();
        if (maxChart) {
          maxChart = renderChart(maxChart.canvas, maxChart, configFactory(true));
        }
      },
      clear() {
        if (chart) chart.destroy();
        chart = null;
        lastConfigFactory = null;
        if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
      },
    };
  }

  function openPicker(input) {
    if (!input) return;
    try {
      input.showPicker();
    } catch (e) {
      // Older browsers: fall back to focusing a temporarily visible input.
      input.classList.remove('invisible-picker');
      input.focus();
      input.addEventListener('blur', () => input.classList.add('invisible-picker'), { once: true });
    }
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-picker]');
    if (trigger) openPicker(byId(trigger.dataset.picker));
  });

  const unitOf = (gadget, name) => (gadget.units && gadget.units[name]) || '';

  // ---------------------------------------------------------------------------
  // Trend graph
  // ---------------------------------------------------------------------------
  function initLine(gadget) {
    const view = chartGadget(gadget);
    const names = gadget.measurements.map(m => m.name);
    const meterOrder = gadget.meters.map(m => m.id);
    const meterNames = Object.fromEntries(gadget.meters.map(m => [m.id, m.name]));
    const picker = byId(`datepicker-${gadget.id}`);
    const liveBtn = byId(`live-btn-${gadget.id}`);

    if (!meterOrder.length || !names.length) {
      setStatus(gadget, 'This gadget has no meters or measurements configured.', 'warning');
      return;
    }

    function draw(readings, subtitle) {
      const series = new Map();
      for (const reading of readings) {
        for (const name of names) {
          const value = toNumber(reading.data[name]);
          if (value === null) continue;
          const key = `${reading.meter_id}|${name}`;
          if (!series.has(key)) series.set(key, []);
          series.get(key).push({ x: reading.ts, y: value });
        }
      }

      const keys = [];
      for (const meterId of meterOrder) {
        for (const name of names) {
          if (series.has(`${meterId}|${name}`)) keys.push([meterId, name]);
        }
      }
      if (!keys.length) {
        view.clear();
        setStatus(gadget, readings.length ? 'The selected measurements are not present in the readings.' : 'No readings received yet.', 'warning');
        return;
      }
      setStatus(gadget, subtitle || '');

      const unitNames = [...new Set(names.map(n => unitOf(gadget, n)).filter(Boolean))];
      view.draw((large) => ({
        type: 'line',
        data: {
          datasets: keys.map(([meterId, name], index) => ({
            label: `${meterNames[meterId] || 'Meter ' + meterId} - ${name}`,
            data: series.get(`${meterId}|${name}`).sort((a, b) => a.x - b.x),
            borderColor: colorFor(index),
            pointBackgroundColor: colorFor(index),
            backgroundColor: keys.length === 1 ? colorFor(index, 0.12) : colorFor(index),
            borderWidth: 2,
            pointRadius: large ? 2 : 0,
            pointHoverRadius: 4,
            tension: 0.3,
            fill: keys.length === 1 ? 'origin' : false,
          })),
        },
        options: {
          responsive: true,
          animation: false,
          parsing: false,
          normalized: true,
          plugins: {
            legend: { position: 'top', align: 'start', labels: { color: TEXT_COLOR, font: { size: large ? 12 : 10 }, padding: 10 } },
            title: { display: large, text: gadget.name, color: TITLE_COLOR },
            tooltip: {
              callbacks: {
                title: (items) => items.length ? dateTimeFormat.format(new Date(items[0].parsed.x)) : '',
                label: (item) => `${item.dataset.label}: ${formatNumber(item.parsed.y, 3)} ${unitOf(gadget, names.find(n => item.dataset.label.endsWith(n))) || ''}`,
              },
            },
          },
          scales: {
            x: {
              type: 'linear',
              ticks: { color: THEME.INK.muted, maxTicksLimit: large ? 10 : 4, font: { size: large ? 11 : 10 }, callback: (value) => timeFormat.format(new Date(value)) },
              grid: { display: false },
            },
            y: {
              grace: '5%',
              title: { display: unitNames.length === 1, text: unitNames[0] || '', color: THEME.INK.muted },
              ticks: { color: THEME.INK.muted, maxTicksLimit: 5, font: { size: large ? 11 : 10 } },
              grid: { color: GRID_COLOR },
              border: { display: false },
            },
          },
        },
      }));
    }

    const live = poller(async () => {
      try {
        const data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/fetchLatestReadings/${gadget.id}/?points=20`);
        draw(data.readingData || []);
      } catch (error) {
        setStatus(gadget, error.message, 'danger');
      }
    }, LIVE_POLL_MS);

    if (picker) {
      picker.addEventListener('change', async () => {
        if (!picker.value) return;
        live.stop();
        if (liveBtn) liveBtn.classList.remove('d-none');
        try {
          const data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/fetchDateTimeWindow/${gadget.id}/${encodeURIComponent(picker.value)}/?minutes=30`);
          const window_ = data.window ? `Showing ${data.window[0]} → ${data.window[1]}` : '';
          draw(data.readingData || [], window_);
          if (!(data.readingData || []).length) setStatus(gadget, `No readings between ${data.window[0]} and ${data.window[1]}.`, 'warning');
        } catch (error) {
          setStatus(gadget, error.message, 'danger');
        }
      });
    }
    if (liveBtn) {
      liveBtn.addEventListener('click', () => {
        liveBtn.classList.add('d-none');
        if (picker) picker.value = '';
        setStatus(gadget, '');
        live.start();
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Pie chart
  // ---------------------------------------------------------------------------
  function initPie(gadget) {
    const view = chartGadget(gadget);
    const dateInput = byId(`datepicker-${gadget.id}`);
    const periodSelector = byId(`period-selector-${gadget.id}`);
    const measurement = gadget.measurements[0] && gadget.measurements[0].name;
    if (!measurement || !gadget.meters.length) {
      setStatus(gadget, 'This gadget has no meters or measurement configured.', 'warning');
      return;
    }

    async function load() {
      const date = dateInput.value || CTX.today;
      const period = periodSelector.value;
      setStatus(gadget, 'Loading…');
      try {
        const response = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/data/${gadget.id}/${encodeURIComponent(measurement)}/${date}/${period}`);
        const rows = response.data || [];
        const unit = response.unit || unitOf(gadget, measurement);
        if (!rows.length) {
          view.clear();
          setStatus(gadget, `No ${measurement} data for this ${period === 'daily' ? 'day' : 'period'} (${response.period_start}).`, 'warning');
          return;
        }
        setStatus(gadget, `${measurement}${unit ? ' (' + unit + ')' : ''} · ${period} from ${response.period_start}`);
        const labels = rows.map(r => r.meter);
        const values = rows.map(r => r.value);
        const colors = labels.map((_, i) => colorFor(i));
        view.draw((large) => ({
          type: 'doughnut',
          data: { labels, datasets: [{ data: values.map(v => Math.max(0, v)), backgroundColor: colors, borderColor: THEME.SURFACE.panel, borderWidth: 2, hoverOffset: 6 }] },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: large ? 2 : 1.15,
            cutout: '62%',
            animation: large ? {} : false,
            plugins: {
              legend: {
                position: large ? 'right' : 'top',
                align: 'start',
                labels: {
                  color: TEXT_COLOR,
                  font: { size: large ? 12 : 10 },
                  padding: 8,
                  generateLabels: (chart) => chart.data.labels.map((label, i) => ({
                    text: `${label} (${formatNumber(values[i])}${unit ? ' ' + unit : ''})`,
                    fillStyle: colors[i],
                    strokeStyle: colors[i],
                    pointStyle: 'circle',
                    fontColor: TEXT_COLOR,
                    lineWidth: 0,
                    hidden: !chart.getDataVisibility(i),
                    index: i,
                  })),
                },
              },
              tooltip: { callbacks: { label: (item) => `${item.label}: ${formatNumber(values[item.dataIndex])} ${unit}` } },
              title: { display: large, text: `${gadget.name} - ${measurement}`, color: TITLE_COLOR },
            },
          },
        }));
      } catch (error) {
        view.clear();
        setStatus(gadget, error.message, 'danger');
      }
    }

    dateInput.addEventListener('change', load);
    periodSelector.addEventListener('change', load);
    load();
  }

  // ---------------------------------------------------------------------------
  // Grouped bar chart: selected year vs previous year
  // ---------------------------------------------------------------------------
  function initBar(gadget) {
    const view = chartGadget(gadget);
    const dateInput = byId(`datepicker-${gadget.id}`);
    const periodSelector = byId(`period-selector-${gadget.id}`);
    const startWeek = byId(`start-week-${gadget.id}`);
    const endWeek = byId(`end-week-${gadget.id}`);
    const startMonth = byId(`start-month-${gadget.id}`);
    const endMonth = byId(`end-month-${gadget.id}`);
    const rangeIcons = byId(`range-selectors-${gadget.id}`);
    const clearRange = byId(`clear-range-${gadget.id}`);
    const onlySelectedYear = byId(`toggle-current-year-${gadget.id}`);
    const measurement = gadget.measurements[0] && gadget.measurements[0].name;
    if (!measurement || !gadget.meters.length) {
      setStatus(gadget, 'This gadget has no meters or measurement configured.', 'warning');
      return;
    }

    function rangeInputs() {
      if (periodSelector.value === 'weekly') return [startWeek, endWeek];
      if (periodSelector.value === 'monthly') return [startMonth, endMonth];
      return [null, null];
    }

    function updateRangeUI() {
      const [start, end] = rangeInputs();
      rangeIcons.classList.toggle('d-none', !start);
      clearRange.classList.toggle('d-none', !(start && (start.value || end.value)));
    }

    byId(`open-start-picker-${gadget.id}`).addEventListener('click', () => openPicker(rangeInputs()[0]));
    byId(`open-end-picker-${gadget.id}`).addEventListener('click', () => openPicker(rangeInputs()[1]));
    clearRange.addEventListener('click', () => {
      [startWeek, endWeek, startMonth, endMonth].forEach(input => { input.value = ''; });
      updateRangeUI();
      load();
    });

    async function load() {
      const date = dateInput.value || CTX.today;
      const period = periodSelector.value;
      const [startInput, endInput] = rangeInputs();
      const params = new URLSearchParams();
      if (startInput && startInput.value && endInput && endInput.value) {
        params.set('start', startInput.value);
        params.set('end', endInput.value);
      }
      updateRangeUI();
      setStatus(gadget, 'Loading…');
      try {
        const response = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/multiYearBarData/${gadget.id}/${encodeURIComponent(measurement)}/${date}/${period}${params.toString() ? '?' + params : ''}`);
        const selectedYear = date.slice(0, 4);
        const years = (response.years || []).filter(y => !onlySelectedYear.checked || y === selectedYear);
        const unit = response.unit || unitOf(gadget, measurement);
        const datasets = [];
        (response.data || []).forEach((meterData, meterIndex) => {
          years.forEach(year => {
            const values = meterData.values[year] || [];
            if (!values.length || values.every(v => !v)) return;
            const latest = year === selectedYear;
            datasets.push({
              label: `${meterData.meter} ${year}`,
              data: values,
              backgroundColor: colorFor(meterIndex, latest ? 1 : 0.35),
              hoverBackgroundColor: colorFor(meterIndex, latest ? 1 : 0.55),
              borderWidth: 0,
              maxBarThickness: 18,
              customYear: year,
            });
          });
        });
        if (!datasets.length) {
          view.clear();
          setStatus(gadget, `No ${measurement} data for ${years.join(' / ') || selectedYear}.`, 'warning');
          return;
        }
        setStatus(gadget, `${measurement}${unit ? ' (' + unit + ')' : ''}`);
        view.draw((large) => ({
          type: 'bar',
          data: { labels: response.labels, datasets },
          options: {
            responsive: true,
            animation: false,
            plugins: {
              legend: { position: 'bottom', labels: { color: TEXT_COLOR, font: { size: large ? 12 : 10 }, padding: 10 } },
              title: { display: large, text: `${measurement} - ${period.charAt(0).toUpperCase() + period.slice(1)}`, color: TITLE_COLOR, font: { size: 14, weight: '600' } },
              tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatNumber(ctx.parsed.y)} ${unit}` } },
            },
            scales: {
              x: { ticks: { color: THEME.INK.muted, font: { size: large ? 11 : 10 } }, grid: { display: false } },
              y: { beginAtZero: true, grace: '10%', ticks: { color: THEME.INK.muted, maxTicksLimit: 5, font: { size: large ? 11 : 10 } }, grid: { color: GRID_COLOR }, border: { display: false } },
            },
          },
        }));
      } catch (error) {
        view.clear();
        setStatus(gadget, error.message, 'danger');
      }
    }

    [dateInput, startWeek, endWeek, startMonth, endMonth, onlySelectedYear].forEach(input => input.addEventListener('change', load));
    periodSelector.addEventListener('change', () => {
      [startWeek, endWeek, startMonth, endMonth].forEach(input => { input.value = ''; });
      load();
    });
    load();
  }

  // ---------------------------------------------------------------------------
  // Tables
  // ---------------------------------------------------------------------------
  function buildTable(head, body, fields, rows) {
    clearChildren(head);
    clearChildren(body);
    fields.forEach(field => head.appendChild(cell('th', field)));
    rows.forEach(row => {
      const tr = document.createElement('tr');
      fields.forEach(field => {
        const value = row[field];
        tr.appendChild(cell('td', typeof value === 'number' ? formatNumber(value, 3) : (value ?? '')));
      });
      body.appendChild(tr);
    });
  }

  function initTable(gadget) {
    const head = byId(`table-head-${gadget.id}`);
    const body = byId(`table-body-${gadget.id}`);
    let lastRows = [];
    let lastFields = [];

    bindMaximize(gadget, {
      show(container) {
        const table = document.createElement('table');
        table.className = 'table table-sm table-dark';
        const thead = document.createElement('thead');
        const tr = document.createElement('tr');
        thead.appendChild(tr);
        const tbody = document.createElement('tbody');
        table.append(thead, tbody);
        container.appendChild(table);
        buildTable(tr, tbody, lastFields, lastRows);
      },
    });

    poller(async () => {
      try {
        const data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/fetchTableData/${gadget.id}`);
        const rows = data.rows || [];
        if (!rows.length) {
          setStatus(gadget, 'No readings received yet.', 'warning');
          return;
        }
        const fields = [...new Set(rows.flatMap(r => Object.keys(r)))];
        lastRows = rows;
        lastFields = fields;
        setStatus(gadget, data.meter ? `Last ${rows.length} readings of ${data.meter}` : '');
        buildTable(head, body, fields, rows);
      } catch (error) {
        setStatus(gadget, error.message, 'danger');
      }
    }, TABLE_POLL_MS);
  }

  function initTool(gadget) {
    const body = byId(`tool-body-${gadget.id}`);
    const updated = byId(`tool-updated-${gadget.id}`);
    const names = gadget.measurements.map(m => m.name);
    let last = null;

    function render(target, reading) {
      clearChildren(target);
      names.forEach(name => {
        const tr = document.createElement('tr');
        tr.appendChild(cell('td', name, 'small'));
        const unit = unitOf(gadget, name);
        tr.appendChild(cell('td', `${formatNumber(reading.data[name], 3)}${unit ? ' ' + unit : ''}`, 'text-info text-end mvc-num'));
        target.appendChild(tr);
      });
    }

    bindMaximize(gadget, {
      show(container) {
        const table = document.createElement('table');
        table.className = 'table table-dark';
        const tbody = document.createElement('tbody');
        table.appendChild(tbody);
        container.appendChild(table);
        if (last) render(tbody, last);
      },
    });

    poller(async () => {
      try {
        const data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/fetchLatestToolData/${gadget.id}/`);
        last = data.reading;
        render(body, data.reading);
        updated.textContent = `${data.reading.meter_name} · updated ${data.reading.timestamp}`;
        setStatus(gadget, '');
      } catch (error) {
        setStatus(gadget, error.message, error.status === 404 ? 'warning' : 'danger');
      }
    }, LIVE_POLL_MS);
  }

  function initMultipleMeterTable(gadget) {
    const head = byId(`mmt-head-${gadget.id}`);
    const body = byId(`mmt-body-${gadget.id}`);

    poller(async () => {
      try {
        const data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/fetchLatestMultipleMeterTableData/${gadget.id}/`);
        const measurements = data.measurements || [];
        clearChildren(head);
        const headers = ['Meter', ...measurements.map(m => unitOf(gadget, m) ? `${m} (${unitOf(gadget, m)})` : m), 'Updated'];
        if (CTX.billingEnabled) headers.push('');
        headers.forEach(text => {
          head.appendChild(cell('th', text));
        });

        clearChildren(body);
        (data.readings || []).forEach(reading => {
          const tr = document.createElement('tr');
          tr.appendChild(cell('td', reading.meter_name, 'fw-semibold'));
          measurements.forEach(m => tr.appendChild(cell('td', formatNumber(reading.data[m], 3), 'text-info mvc-num')));
          tr.appendChild(cell('td', reading.timestamp || 'no data', reading.timestamp ? 'text-muted' : 'text-warning'));
          if (CTX.billingEnabled) {
            const td = document.createElement('td');
            if ((reading.meter_type || '').toLowerCase().includes('electric')) {
              const link = document.createElement('a');
              link.href = `/billing?meter=${encodeURIComponent(reading.meter_id)}`;
              link.className = 'btn btn-sm btn-outline-info py-0';
              link.innerHTML = '<i class="fa-solid fa-receipt me-1"></i> Bill';
              td.appendChild(link);
            }
            tr.appendChild(td);
          }
          body.appendChild(tr);
        });
        setStatus(gadget, (data.readings || []).length ? '' : 'No meters configured.', 'warning');
      } catch (error) {
        setStatus(gadget, error.message, 'danger');
      }
    }, LIVE_POLL_MS);

    bindMaximize(gadget, {
      show(container) {
        const wrapper = head.closest('table').cloneNode(true);
        wrapper.classList.add('w-100');
        container.appendChild(wrapper);
      },
    });
  }

  // ---------------------------------------------------------------------------
  // ECharts helpers
  // ---------------------------------------------------------------------------
  function echartsGadget(gadget, container) {
    if (!window.echarts) {
      setStatus(gadget, 'Chart library failed to load (check the internet connection).', 'danger');
      return null;
    }
    const chart = echarts.init(container, null, { renderer: 'canvas' });
    let lastOption = null;
    let maxChart = null;
    bindMaximize(gadget, {
      show(body) {
        const div = document.createElement('div');
        div.style.width = '100%';
        div.style.height = '70vh';
        body.appendChild(div);
        maxChart = echarts.init(div);
        if (lastOption) maxChart.setOption(lastOption);
      },
      hide() {
        if (maxChart) maxChart.dispose();
        maxChart = null;
      },
    });
    window.addEventListener('resize', () => { chart.resize(); if (maxChart) maxChart.resize(); });
    return {
      set(option) {
        lastOption = option;
        chart.setOption(option, true);
        if (maxChart) maxChart.setOption(option, true);
      },
      clear() {
        lastOption = null;
        chart.clear();
      },
    };
  }

  function roundDate(isoDate, periodType) {
    const d = parseISODate(isoDate);
    if (periodType === 'weekly') {
      const day = d.getUTCDay();
      d.setUTCDate(d.getUTCDate() - (day === 0 ? 6 : day - 1));
    } else if (periodType === 'monthly') {
      d.setUTCDate(1);
    } else if (periodType === 'yearly') {
      d.setUTCMonth(0, 1);
    }
    return toISODate(d);
  }

  // ---------------------------------------------------------------------------
  // Sankey (site -> building -> area -> meter -> load type)
  // ---------------------------------------------------------------------------
  function initSankey(gadget) {
    const chart = echartsGadget(gadget, byId(`sankey_echarts_${gadget.id}`));
    if (!chart) return;
    const datePicker = byId(`datepicker-${gadget.id}`);
    const periodSelector = byId(`period-selector-${gadget.id}`);
    const measurement = gadget.measurements[0] && gadget.measurements[0].name;
    if (!measurement) {
      setStatus(gadget, 'This gadget has no measurement configured.', 'warning');
      return;
    }
    const LEVEL_COLORS = { site: THEME.SERIES[0], building: THEME.SERIES[2], area: THEME.SERIES[3], meter: THEME.SERIES[1], load: THEME.SERIES[6] };

    async function draw() {
      const period = periodSelector.value;
      const date = roundDate(datePicker.value || CTX.today, period);
      setStatus(gadget, 'Loading…');
      let data;
      try {
        data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/hierarchyy/${gadget.siteId}/${encodeURIComponent(measurement)}/${period}/${date}/`);
      } catch (error) {
        chart.clear();
        setStatus(gadget, error.message, error.status === 404 ? 'warning' : 'danger');
        return;
      }

      const hierarchy = data.hierarchy_data || {};
      const unit = data.unit || '';
      const siteName = (data.site && data.site.name) || 'Site';
      const labels = {};
      const levels = {};
      const links = [];
      const loadTotals = {};

      function node(id, label, level) {
        labels[id] = label;
        levels[id] = level;
        return id;
      }

      const site = node('site', siteName, 'site');
      for (const [buildingName, building] of Object.entries(hierarchy.buildings || {})) {
        const buildingId = node(`b:${buildingName}`, buildingName, 'building');
        let buildingSum = 0;
        for (const [areaName, area] of Object.entries(building.areas || {})) {
          const areaId = node(`a:${buildingName}/${areaName}`, areaName, 'area');
          let areaSum = 0;
          for (const [meterName, meter] of Object.entries(area.meters || {})) {
            const value = toNumber((meter.data || {})[measurement]);
            if (value === null || value <= 0) continue;
            const meterId = node(`m:${buildingName}/${areaName}/${meterName}`, meterName, 'meter');
            const loadName = meter.loadType || 'Unknown';
            const loadId = node(`l:${loadName}`, `Load Type: ${loadName}`, 'load');
            links.push({ source: areaId, target: meterId, value });
            links.push({ source: meterId, target: loadId, value });
            loadTotals[loadId] = (loadTotals[loadId] || 0) + value;
            areaSum += value;
          }
          if (areaSum > 0) {
            links.push({ source: buildingId, target: areaId, value: areaSum });
            buildingSum += areaSum;
          }
        }
        if (buildingSum > 0) links.push({ source: site, target: buildingId, value: buildingSum });
      }

      if (!links.length) {
        chart.clear();
        setStatus(gadget, `No positive ${measurement} values in the ${period} aggregate starting ${data.start_date}.`, 'warning');
        return;
      }
      const used = new Set(links.flatMap(l => [l.source, l.target]));
      const note = data.exact ? '' : ` (no data for ${data.requested_date}; showing latest available)`;
      setStatus(gadget, `${measurement}${unit ? ' (' + unit + ')' : ''} · ${period} from ${data.start_date}${note}`, data.exact ? 'secondary' : 'warning');

      const base = MVC.echartsBase();
      chart.set({
        ...base,
        tooltip: {
          ...base.tooltip,
          trigger: 'item',
          formatter: (params) => {
            if (params.dataType === 'edge') {
              return `${MVC.escapeHtml(labels[params.data.source])} → ${MVC.escapeHtml(labels[params.data.target])}<br/>${MVC.escapeHtml(measurement)}: ${formatNumber(params.data.value)} ${MVC.escapeHtml(unit)}`;
            }
            const total = loadTotals[params.data.name];
            return `${MVC.escapeHtml(labels[params.data.name])}${total ? `<br/>Total: ${formatNumber(total)} ${MVC.escapeHtml(unit)}` : ''}`;
          },
        },
        series: [{
          type: 'sankey',
          data: [...used].map(id => ({ name: id, itemStyle: { color: LEVEL_COLORS[levels[id]] } })),
          links,
          emphasis: { focus: 'adjacency' },
          lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.28 },
          itemStyle: { borderWidth: 0 },
          label: { color: TITLE_COLOR, fontSize: 11, formatter: (p) => labels[p.name] },
          nodeWidth: 12,
          nodeGap: 12,
          left: 10, right: 130, top: 10, bottom: 10,
        }],
      });
    }

    datePicker.addEventListener('change', draw);
    periodSelector.addEventListener('change', draw);
    draw();
  }

  // ---------------------------------------------------------------------------
  // Heat map (day x hour)
  // ---------------------------------------------------------------------------
  function initHeatmap(gadget) {
    const chart = echartsGadget(gadget, byId(`heatmap_container_${gadget.id}`));
    if (!chart) return;
    const startPicker = byId(`start-date-${gadget.id}`);
    const endPicker = byId(`end-date-${gadget.id}`);
    const rangeLabel = byId(`heatmap-range-${gadget.id}`);
    const meter = gadget.meters[0];
    const measurement = gadget.measurements[0] && gadget.measurements[0].name;
    if (!meter || !measurement) {
      setStatus(gadget, 'This gadget needs one meter and one measurement.', 'warning');
      return;
    }

    startPicker.value = addDays(CTX.today, -29);
    endPicker.value = CTX.today;

    async function load() {
      let start = startPicker.value;
      let end = endPicker.value;
      if (!start || !end) return;
      if (start > end) [start, end] = [end, start];
      rangeLabel.textContent = `${start} → ${end}`;
      setStatus(gadget, 'Loading…');
      try {
        const res = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/heatmap/${meter.id}/${start}/${end}/${encodeURIComponent(measurement)}/`);
        const raw = res.data || [];
        if (!raw.length) {
          chart.clear();
          setStatus(gadget, `No ${measurement} readings for ${meter.name} in this range.`, 'warning');
          return;
        }
        const days = [];
        for (let d = start; d <= end; d = addDays(d, 1)) days.push(d);
        const dayIndex = Object.fromEntries(days.map((d, i) => [d, i]));
        const points = raw.filter(p => p.day in dayIndex).map(p => [dayIndex[p.day], p.hour, p.value]);
        const values = points.map(p => p[2]);
        const unit = res.unit || '';
        const what = res.mode === 'consumption' ? 'consumption per hour' : 'hourly average';
        setStatus(gadget, `${meter.name} · ${measurement} ${what}${unit ? ' (' + unit + ')' : ''}`);

        const base = MVC.echartsBase();
        chart.set({
          ...base,
          tooltip: {
            ...base.tooltip,
            position: 'top',
            formatter: (p) => `${days[p.data[0]]} ${String(p.data[1]).padStart(2, '0')}:00<br>${MVC.escapeHtml(measurement)}: ${formatNumber(p.data[2], 3)} ${MVC.escapeHtml(unit)}`,
          },
          grid: { height: '72%', top: '4%', left: 56, right: 16 },
          xAxis: { type: 'category', data: days, axisLabel: { color: THEME.INK.muted, fontSize: 10 }, axisLine: { lineStyle: { color: THEME.INK.axis } }, axisTick: { show: false }, splitArea: { show: false } },
          yAxis: { type: 'category', data: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`), axisLabel: { color: THEME.INK.muted, fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: false } },
          visualMap: {
            min: Math.min(...values),
            max: Math.max(...values) > Math.min(...values) ? Math.max(...values) : Math.min(...values) + 1,
            calculable: true,
            orient: 'horizontal',
            left: 'center',
            bottom: '2%',
            itemHeight: 220,
            itemWidth: 10,
            textStyle: { color: THEME.INK.muted },
            inRange: { color: THEME.HEAT },
          },
          series: [{ name: measurement, type: 'heatmap', data: points, itemStyle: { borderWidth: 1, borderColor: THEME.SURFACE.panel, borderRadius: 2 }, emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 1 } } }],
        });
      } catch (error) {
        chart.clear();
        setStatus(gadget, error.message, 'danger');
      }
    }

    startPicker.addEventListener('change', load);
    endPicker.addEventListener('change', load);
    load();
  }

  // ---------------------------------------------------------------------------
  // Value card
  // ---------------------------------------------------------------------------
  function initMachineHealth(gadget) {
    const body = byId(`machineHealth-body-${gadget.id}`);
    if (!body) return;
    let latest = { machines: [], at_risk: 0, scored: 0 };
    const barColor = (pct) => (pct >= 70 ? '#f05252' : pct >= 40 ? '#f5b83d' : '#22c55e');

    function renderList(container, machines, full) {
      clearChildren(container);
      if (!machines.length) {
        const p = document.createElement('p');
        p.className = 'text-muted small mb-0';
        p.textContent = latest.scored
          ? 'All machines are healthy — none near breakdown.'
          : 'No predictions yet. Run scoring on the Machine Learning page.';
        container.appendChild(p);
        return;
      }
      const items = full ? machines : machines.slice(0, 5);
      items.forEach(m => {
        const item = document.createElement('div');
        item.className = 'mh-item';

        const pill = document.createElement('span');
        pill.className = `status-pill ${m.risk === 'high' ? 'bad' : 'warn'}`;
        pill.style.flex = '0 0 auto';
        pill.textContent = m.risk === 'high' ? 'High' : 'Medium';

        const info = document.createElement('div');
        info.style.cssText = 'flex:1 1 auto;min-width:0';
        const name = document.createElement('div');
        name.className = 'mh-name text-truncate';
        name.innerHTML = (m.kind === 'motor' ? '<i class="fa-solid fa-fan me-1"></i>' : '<i class="fa-solid fa-gauge me-1"></i>') + MVC.escapeHtml(m.name);
        const loc = document.createElement('div');
        loc.className = 'mh-loc text-truncate';
        const parts = [];
        if (m.location) parts.push(m.location);
        if (m.days !== null && m.days !== undefined) parts.push(m.days >= 30 ? '30+ days left' : `~${m.days} days left`);
        if (full && m.failure_mode) parts.push(m.failure_mode);
        if (full && m.drivers && m.drivers.length) parts.push(m.drivers.join(', '));
        loc.textContent = parts.join(' · ');
        info.append(name, loc);

        const bar = document.createElement('div');
        bar.className = 'mh-bar';
        const fill = document.createElement('span');
        const pct = m.lifespan == null ? 0 : m.lifespan;
        fill.style.width = `${pct}%`;
        fill.style.background = barColor(pct);
        bar.appendChild(fill);

        const pctLabel = document.createElement('span');
        pctLabel.className = 'mh-pct';
        pctLabel.textContent = m.lifespan == null ? '—' : `${m.lifespan}%`;
        pctLabel.title = 'Lifespan elapsed';

        item.append(pill, info, bar, pctLabel);
        container.appendChild(item);
      });
      if (!full && machines.length > items.length) {
        const more = document.createElement('div');
        more.className = 'small text-muted mt-2';
        more.textContent = `+ ${machines.length - items.length} more — expand to see all`;
        container.appendChild(more);
      }
    }

    const wrap = document.createElement('div');
    wrap.className = 'machine-health';
    body.replaceChildren(wrap);

    poller(async () => {
      try {
        latest = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/machineHealth/${gadget.id}/`);
        renderList(wrap, latest.machines || [], false);
        setStatus(gadget, latest.at_risk ? `${latest.at_risk} machine${latest.at_risk === 1 ? '' : 's'} near breakdown` : '',
          latest.at_risk ? 'warning' : 'secondary');
      } catch (error) {
        setStatus(gadget, error.message, 'danger');
      }
    }, 60000);

    bindMaximize(gadget, {
      show(container) {
        const div = document.createElement('div');
        div.className = 'machine-health';
        container.appendChild(div);
        renderList(div, latest.machines || [], true);
      },
    });
  }

  function initValueCard(gadget) {
    const valueEl = byId(`valueCardValue${gadget.id}`);
    const unitEl = byId(`valueCardUnit${gadget.id}`);
    const captionEl = byId(`valueCardCaption${gadget.id}`);
    const measurement = gadget.measurements[0];
    if (!measurement) {
      valueEl.textContent = 'N/A';
      setStatus(gadget, 'No measurement configured.', 'warning');
      return;
    }
    poller(async () => {
      try {
        const data = await MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/fetchValueCardData/${gadget.siteId}/${measurement.id}`);
        valueEl.textContent = data.value === null || data.value === undefined ? 'N/A' : formatNumber(data.value, 2);
        unitEl.textContent = data.unit || '';
        captionEl.textContent = `${data.measurement} · ${data.source === 'live' ? 'live total' : data.source + ' from ' + data.latest_date}`;
        setStatus(gadget, data.message || '', 'warning');
      } catch (error) {
        valueEl.textContent = 'Error';
        setStatus(gadget, error.message, 'danger');
      }
    }, VALUE_CARD_POLL_MS);
  }

  // ---------------------------------------------------------------------------
  // Picture map: 3D building with floors coloured by consumption
  // ---------------------------------------------------------------------------
  async function initPictureMap(gadget) {
    const container = byId(`building-3d${gadget.id}`);
    const measurement = gadget.measurements[0] && gadget.measurements[0].name;
    if (!gadget.buildingId || !measurement) {
      setStatus(gadget, 'Select a building and a measurement for this picture map.', 'warning');
      return;
    }

    let THREE, CameraControls, data;
    try {
      [THREE, { default: CameraControls }, data] = await Promise.all([
        import('https://cdn.jsdelivr.net/npm/three@0.124.0/build/three.module.js'),
        import('https://cdn.jsdelivr.net/npm/camera-controls@2.9.0/+esm'),
        MVC.fetchJSON(`/dashboard/${gadget.dashboardId}/building_heatmap/${gadget.buildingId}/${encodeURIComponent(measurement)}/`),
      ]);
    } catch (error) {
      setStatus(gadget, error.message || '3D view could not be loaded.', 'danger');
      return;
    }
    CameraControls.install({ THREE });

    const areas = data.areas || [];
    const unit = data.unit || '';
    setStatus(gadget, data.message ? data.message : `${measurement}${unit ? ' (' + unit + ')' : ''} · month from ${data.period}`, data.message ? 'warning' : 'secondary');

    const scene = new THREE.Scene();
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dirLight = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight.position.set(100, 200, 100);
    scene.add(dirLight);
    const floorsGroup = new THREE.Group();
    const metersGroup = new THREE.Group();
    scene.add(floorsGroup, metersGroup);
    let selectedFloor = null;

    const RAMP = THEME.HEAT.map(hex => new THREE.Color(hex));
    function heatColor(value, min, max) {
      const ratio = Math.min(1, Math.max(0, (value - min) / ((max - min) || 1))) * (RAMP.length - 1);
      const i = Math.min(RAMP.length - 2, Math.floor(ratio));
      return RAMP[i].clone().lerp(RAMP[i + 1], ratio - i);
    }

    function textSprite(message) {
      const fontsize = 40;
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      ctx.font = `600 ${fontsize}px Inter, Segoe UI, sans-serif`;
      canvas.width = Math.ceil(ctx.measureText(message).width + 10);
      canvas.height = fontsize + 10;
      ctx.font = `600 ${fontsize}px Inter, Segoe UI, sans-serif`;
      ctx.textBaseline = 'top';
      ctx.lineWidth = 6;
      ctx.strokeStyle = 'rgba(7,11,17,0.9)';
      ctx.strokeText(message, 5, 5);
      ctx.fillStyle = '#e6edf3';
      ctx.fillText(message, 5, 5);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }));
      sprite.scale.set(canvas.width / 5, canvas.height / 5, 1);
      return sprite;
    }

    // Build floors
    const floorHeight = 20, floorSpacing = 5;
    const size = 60 * (1 + Math.max(0, areas.length - 1) * 0.2);
    const values = areas.map(a => a.value);
    const minVal = Math.min(...values), maxVal = Math.max(...values);
    areas.forEach((area, index) => {
      const y = index * (floorHeight + floorSpacing);
      const floor = new THREE.Mesh(
        new THREE.BoxGeometry(size, floorHeight, size),
        new THREE.MeshLambertMaterial({ color: heatColor(area.value, minVal, maxVal), transparent: true, opacity: 0.35 })
      );
      floor.position.set(0, y + floorHeight / 2, 0);
      floor.userData = { type: 'floor', name: area.name, value: area.value, meters: area.meters || [] };
      floorsGroup.add(floor);
      const label = textSprite(`${area.name}: ${formatNumber(area.value)} ${unit}`);
      label.position.set(size / 2 + 25, y + (2 * floorHeight) / 3, 0);
      floor.userData.label = label;
      floorsGroup.add(label);
    });

    function toggleFloor(floor) {
      metersGroup.clear();
      if (selectedFloor === floor) {
        floorsGroup.children.forEach(obj => { obj.visible = true; });
        selectedFloor = null;
        return;
      }
      selectedFloor = floor;
      floorsGroup.children.forEach(obj => { obj.visible = obj === floor || obj === floor.userData.label; });
      const meters = floor.userData.meters;
      const width = size * 0.9;
      const meterWidth = meters.length ? width / meters.length : width;
      const meterValues = meters.map(m => m.value);
      const lo = Math.min(...meterValues), hi = Math.max(...meterValues);
      meters.forEach((meter, idx) => {
        const cube = new THREE.Mesh(
          new THREE.BoxGeometry(Math.max(2, meterWidth - 2), 10, 30),
          new THREE.MeshLambertMaterial({ color: heatColor(meter.value, lo, hi) })
        );
        cube.position.set(-width / 2 + meterWidth / 2 + idx * meterWidth, floor.position.y, 0);
        cube.userData = { name: meter.name, value: meter.value };
        metersGroup.add(cube);
      });
    }

    function createView(target, height) {
      let renderer;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true });
      } catch (error) {
        setStatus(gadget, 'WebGL is not available in this browser.', 'danger');
        return null;
      }
      const width = target.clientWidth || 300;
      renderer.setSize(width, height);
      renderer.setClearColor(0x0f151d);
      target.appendChild(renderer.domElement);
      const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 5000);
      const controls = new CameraControls(camera, renderer.domElement);
      controls.dollyToCursor = true;

      const box = new THREE.Box3().setFromObject(floorsGroup);
      const center = box.getCenter(new THREE.Vector3());
      const dim = Math.max(...box.getSize(new THREE.Vector3()).toArray(), 50);
      const distance = (dim / 2) / Math.tan((camera.fov * Math.PI) / 360) * 1.6;
      controls.setLookAt(center.x + distance * Math.sin(Math.PI / 3), center.y + distance * 0.5, center.z + distance * Math.cos(Math.PI / 3), center.x, center.y, center.z, false);

      const raycaster = new THREE.Raycaster();
      const pointer = new THREE.Vector2();
      function pick(event, objects) {
        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);
        return raycaster.intersectObjects(objects);
      }
      renderer.domElement.addEventListener('click', (event) => {
        const hit = pick(event, floorsGroup.children.filter(o => o.userData.type === 'floor' && o.visible));
        if (hit.length) {
          toggleFloor(hit[0].object);
          views.forEach(v => { v.needsRender = true; });
        }
      });
      renderer.domElement.addEventListener('mousemove', (event) => {
        const meterHit = pick(event, metersGroup.children);
        if (meterHit.length) {
          target.title = `${meterHit[0].object.userData.name}: ${formatNumber(meterHit[0].object.userData.value)} ${unit}`;
          return;
        }
        const floorHit = pick(event, floorsGroup.children.filter(o => o.userData.type === 'floor' && o.visible));
        target.title = floorHit.length ? `${floorHit[0].object.userData.name}: ${formatNumber(floorHit[0].object.userData.value)} ${unit} (click to show meters)` : '';
      });

      const clock = new THREE.Clock();
      const view = { renderer, camera, controls, alive: true, needsRender: true };
      (function loop() {
        if (!view.alive) return;
        const updated = controls.update(clock.getDelta());
        if (updated || view.needsRender) {
          renderer.render(scene, camera);
          view.needsRender = false;
        }
        requestAnimationFrame(loop);
      })();
      view.dispose = () => {
        view.alive = false;
        controls.dispose();
        renderer.dispose();
        if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
      };
      return view;
    }

    const views = [];
    const cardView = createView(container, 420);
    if (cardView) views.push(cardView);

    let modalView = null;
    bindMaximize(gadget, {
      show(body) {
        modalView = createView(body, Math.round(window.innerHeight * 0.7));
        if (modalView) views.push(modalView);
      },
      hide() {
        if (modalView) {
          modalView.dispose();
          views.splice(views.indexOf(modalView), 1);
        }
        modalView = null;
      },
    });
  }

  // ---------------------------------------------------------------------------
  // Page-level widgets
  // ---------------------------------------------------------------------------
  async function initWeather() {
    const button = byId('weather-btn');
    const body = byId('weather-modal-body');
    if (!button || !CTX.dashboardId) return;
    try {
      const data = await MVC.fetchJSON(`/dashboard/${CTX.dashboardId}/weather/`);
      clearChildren(button);
      if (data.current.icon) {
        const icon = document.createElement('img');
        icon.src = data.current.icon;
        icon.alt = data.current.text;
        button.appendChild(icon);
      }
      button.appendChild(document.createTextNode(`${formatNumber(data.current.temp_c, 1)}°C · ${data.current.text}`));

      clearChildren(body);
      const now = document.createElement('div');
      now.className = 'weather-now';
      if (data.current.icon) {
        const icon = document.createElement('img');
        icon.src = data.current.icon;
        icon.alt = data.current.text;
        now.appendChild(icon);
      }
      const nowText = document.createElement('div');
      nowText.append(cell('div', `${formatNumber(data.current.temp_c, 1)}°C`, 'temp'), cell('div', `${data.current.text} · ${data.location}`, 'text-muted small mt-1'));
      now.appendChild(nowText);
      body.appendChild(now);

      const grid = document.createElement('div');
      grid.className = 'weather-days';
      const dayFormat = new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', weekday: 'short', day: '2-digit', month: 'short' });
      data.forecast.forEach(day => {
        const card = document.createElement('div');
        card.className = 'weather-day';
        const parsed = parseISODate(day.date);
        card.appendChild(cell('div', parsed ? dayFormat.format(parsed) : day.date, 'eyebrow mb-1'));
        if (day.icon) {
          const icon = document.createElement('img');
          icon.src = day.icon;
          icon.alt = day.text;
          card.appendChild(icon);
        }
        card.append(cell('div', `${formatNumber(day.avgtemp_c, 1)}°C`, 'day-temp'), cell('div', day.text, 'text-muted small'));
        grid.appendChild(card);
      });
      body.appendChild(grid);
    } catch (error) {
      button.textContent = 'Weather unavailable';
      body.textContent = error.message;
    }
  }

  function initTicker() {
    const items = document.querySelectorAll('#alarm-ticker .ticker-item');
    if (items.length < 2) return;
    let index = 0;
    setInterval(() => {
      items[index].classList.remove('active');
      index = (index + 1) % items.length;
      items[index].classList.add('active');
    }, 3000);
  }

  function initClock() {
    const hour = byId('hourHand'), minute = byId('minuteHand'), second = byId('secondHand'), digital = byId('digitalClock');
    if (!hour) return;
    const partsFormat = new Intl.DateTimeFormat('en-GB', { timeZone: MVC.timeZone, hour: 'numeric', minute: 'numeric', second: 'numeric', hour12: false });
    function update() {
      const parts = Object.fromEntries(partsFormat.formatToParts(new Date()).map(p => [p.type, Number(p.value)]));
      const s = parts.second, m = parts.minute, h = parts.hour;
      second.style.transform = `translateX(-50%) rotate(${s * 6}deg)`;
      minute.style.transform = `translateX(-50%) rotate(${m * 6 + s * 0.1}deg)`;
      hour.style.transform = `translateX(-50%) rotate(${(h % 12) * 30 + m * 0.5}deg)`;
      if (digital) digital.textContent = timeFormat.format(new Date());
    }
    update();
    setInterval(update, 1000);
  }

  function initTree() {
    const tree = byId('tree');
    if (!tree) return;
    tree.querySelectorAll('li.has-children > .tree-label').forEach(label => {
      label.addEventListener('click', (event) => {
        event.stopPropagation();
        const list = label.parentElement.querySelector(':scope > ul');
        if (list) list.classList.toggle('d-none');
      });
    });

    const gadgets = document.querySelectorAll('.gadget-item');
    const meters = tree.querySelectorAll('.meter-item');
    function clear() {
      gadgets.forEach(g => g.classList.remove('gadget-highlight'));
      meters.forEach(m => m.classList.remove('text-info'));
    }
    gadgets.forEach(gadget => {
      gadget.addEventListener('click', (event) => {
        if (event.target.closest('.modal, button, a, select, input, i')) return;
        event.stopPropagation();
        clear();
        gadget.classList.add('gadget-highlight');
        const ids = (gadget.dataset.meterIds || '').split(',').filter(Boolean);
        ids.forEach(id => {
          tree.querySelectorAll(`.meter-item[data-meter-id="${CSS.escape(id)}"]`).forEach(item => {
            item.classList.add('text-info');
            let parent = item.parentElement;
            while (parent && parent !== tree) {
              if (parent.tagName === 'UL') parent.classList.remove('d-none');
              parent = parent.parentElement;
            }
          });
        });
      });
    });
    document.addEventListener('click', clear);
  }

  /** Add/edit gadget forms: show only the fields that make sense for the chosen type. */
  function initGadgetForms() {
    const RULES = {
      line: { meters: 'multiple', measurements: 'multiple', help: 'Live trend of one or more measurements for one or more meters.' },
      'multiple-meter-table': { meters: 'multiple', measurements: 'multiple', help: 'Latest values of several meters side by side.' },
      tool: { meters: 'single', measurements: 'multiple', help: 'Latest values of one meter.' },
      table: { meters: 'single', measurements: 'none', help: 'Last 20 raw readings of one meter.' },
      pie: { meters: 'multiple', measurements: 'single', help: 'Share of each meter for a period (use a counter such as Energy).' },
      bar: { meters: 'multiple', measurements: 'single', help: 'Selected year compared with the previous year.' },
      heatmap: { meters: 'single', measurements: 'single', help: 'Hour-by-day profile of one meter.' },
      sankey: { meters: 'none', measurements: 'single', help: 'Energy flow through the site hierarchy (uses the nightly aggregates).' },
      picturemap: { meters: 'none', measurements: 'single', building: true, help: '3D building coloured by area totals (monthly aggregate).' },
      valueCard: { meters: 'none', measurements: 'single', help: 'Site total of one measurement.' },
      machineHealth: { meters: 'none', measurements: 'none', help: 'Machines the model predicts are close to breaking down (needs the Machine Learning module).' },
    };

    function applyMode(select, section, mode) {
      section.classList.toggle('d-none', mode === 'none');
      select.disabled = mode === 'none';
      select.required = mode !== 'none';
      const wantMultiple = mode === 'multiple';
      if (select.multiple !== wantMultiple) {
        const selected = Array.from(select.selectedOptions).map(o => o.value);
        select.multiple = wantMultiple;
        select.size = 6;
        Array.from(select.options).forEach(o => { o.selected = wantMultiple ? selected.includes(o.value) : o.value === selected[0]; });
      }
    }

    document.querySelectorAll('form.js-gadget-form').forEach(form => {
      const type = form.querySelector('.js-gadget-type');
      const meters = form.querySelector('.js-meters');
      const measurements = form.querySelector('.js-measurements');
      const metersSection = form.querySelector('.js-meters-section');
      const measurementSection = form.querySelector('.js-measurement-section');
      const buildingSection = form.querySelector('.js-building-section');
      const building = form.querySelector('.js-building');
      const help = form.querySelector('.js-type-help');

      function update() {
        const rule = RULES[type.value] || { meters: 'multiple', measurements: 'single', help: '' };
        applyMode(meters, metersSection, rule.meters);
        applyMode(measurements, measurementSection, rule.measurements);
        buildingSection.classList.toggle('d-none', !rule.building);
        building.disabled = !rule.building;
        help.textContent = rule.help;
      }
      type.addEventListener('change', update);
      update();
    });
  }

  let masonry = null;
  let relayoutTimer = null;
  function requestRelayout() {
    clearTimeout(relayoutTimer);
    relayoutTimer = setTimeout(() => { if (masonry) masonry.layout(); }, 120);
  }

  function initMasonry() {
    const grid = byId('masonry-grid');
    if (!grid || !window.Masonry) return;
    masonry = new Masonry(grid, { itemSelector: '.gadget-item', gutter: 20, fitWidth: true });
    // Re-layout whenever a gadget changes height after its data arrives.
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(requestRelayout);
      grid.querySelectorAll('.gadget-item').forEach(item => observer.observe(item));
    }
    window.addEventListener('load', requestRelayout);
  }

  const INITIALISERS = {
    line: initLine,
    pie: initPie,
    bar: initBar,
    table: initTable,
    tool: initTool,
    'multiple-meter-table': initMultipleMeterTable,
    sankey: initSankey,
    heatmap: initHeatmap,
    picturemap: initPictureMap,
    valueCard: initValueCard,
    machineHealth: initMachineHealth,
  };

  function start() {
    initGadgetForms();
    initTicker();
    initClock();
    initTree();
    initWeather();
    GADGETS.forEach(gadget => {
      const init = INITIALISERS[gadget.type];
      if (!init) {
        setStatus(gadget, `Unknown gadget type "${gadget.type}".`, 'danger');
        return;
      }
      try {
        const result = init(gadget);
        if (result && typeof result.catch === 'function') {
          result.catch(error => setStatus(gadget, error.message, 'danger'));
        }
      } catch (error) {
        console.error(`Gadget ${gadget.id} failed`, error);
        setStatus(gadget, `This gadget failed to load: ${error.message}`, 'danger');
      }
    });
    initMasonry();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
