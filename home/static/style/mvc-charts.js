/*
 * Shared chart theme for Chart.js and ECharts.
 *
 * Categorical colours are a fixed, colour-blind-validated order (checked
 * against the #0f151d panel surface): series keep their colour by position,
 * they are never generated.
 */
(function () {
  'use strict';

  const MVC = (window.MVC = window.MVC || {});

  const SERIES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
  const INK = { primary: '#e6edf3', secondary: '#a9b4c0', muted: '#7a8694', grid: 'rgba(148,163,184,0.10)', axis: 'rgba(148,163,184,0.22)' };
  const SURFACE = { panel: '#0f151d', raised: '#141c26', border: 'rgba(148,163,184,0.22)' };
  // Sequential ramp (low -> high), one hue, for heat maps on a dark surface.
  const SEQUENTIAL = ['#0d366b', '#184f95', '#2a78d6', '#5598e7', '#9ec5f4', '#e3effd'];
  // Heat maps and the 3D building map: green (low) -> yellow -> red (high).
  const HEAT = ['#1a9850', '#66bd63', '#a6d96a', '#fee08b', '#fdae61', '#f46d43', '#d73027'];
  const FONT = '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

  function hexToRgba(hex, alpha) {
    const value = hex.replace('#', '');
    const n = parseInt(value.length === 3 ? value.split('').map(c => c + c).join('') : value, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
  }

  MVC.chartTheme = { SERIES, INK, SURFACE, SEQUENTIAL, HEAT, FONT };
  /** Colour of the i-th series; alpha < 1 gives a translucent variant of the same hue. */
  MVC.seriesColor = function (index, alpha = 1) {
    const hex = SERIES[((index % SERIES.length) + SERIES.length) % SERIES.length];
    return alpha >= 1 ? hex : hexToRgba(hex, alpha);
  };
  MVC.hexToRgba = hexToRgba;

  if (window.Chart) {
    const d = Chart.defaults;
    d.font.family = FONT;
    d.font.size = 11;
    d.color = INK.secondary;
    d.borderColor = INK.grid;
    d.maintainAspectRatio = true;
    d.animation = { duration: 350 };

    d.elements.line.borderWidth = 2;
    d.elements.line.tension = 0.25;
    d.elements.point.radius = 0;
    d.elements.point.hoverRadius = 4;
    d.elements.point.hitRadius = 8;
    d.elements.bar.borderRadius = 4;
    d.elements.bar.borderSkipped = 'start';
    d.elements.arc.borderWidth = 2;
    d.elements.arc.borderColor = SURFACE.panel;

    d.plugins.legend.labels.usePointStyle = true;
    d.plugins.legend.labels.pointStyle = 'circle';
    d.plugins.legend.labels.boxWidth = 8;
    d.plugins.legend.labels.boxHeight = 8;
    d.plugins.legend.labels.color = INK.secondary;
    d.plugins.title.color = INK.primary;
    d.plugins.title.font = { weight: '600', size: 12 };

    Object.assign(d.plugins.tooltip, {
      backgroundColor: 'rgba(20,28,38,0.96)',
      borderColor: SURFACE.border,
      borderWidth: 1,
      titleColor: INK.primary,
      bodyColor: INK.secondary,
      titleFont: { weight: '600', size: 12 },
      bodyFont: { size: 12 },
      padding: 10,
      cornerRadius: 8,
      boxPadding: 4,
      usePointStyle: true,
    });

    const scale = d.scale;
    scale.grid.color = INK.grid;
    scale.border = Object.assign(scale.border || {}, { color: INK.axis });
    scale.ticks.color = INK.muted;
  }

  /** Base ECharts option: transparent background, theme fonts, dark tooltip. */
  MVC.echartsBase = function () {
    return {
      backgroundColor: 'transparent',
      color: SERIES,
      textStyle: { fontFamily: FONT, color: INK.secondary },
      tooltip: {
        backgroundColor: 'rgba(20,28,38,0.96)',
        borderColor: SURFACE.border,
        borderWidth: 1,
        textStyle: { color: INK.primary, fontSize: 12 },
        extraCssText: 'border-radius:8px;box-shadow:0 12px 32px -12px rgba(0,0,0,.8);',
      },
    };
  };
})();
