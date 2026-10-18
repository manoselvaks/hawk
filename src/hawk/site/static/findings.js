// Findings page: event-study lines (weeks before the decision on the x axis).
(function () {
  "use strict";
  var H = window.HawkCharts;
  var el = document.getElementById("es-chart");
  if (!el) return;
  var es = JSON.parse(document.getElementById("es-data").textContent);
  var colour = { hike: "hawk", cut: "dove", hold: "neutral" };
  var all = [];
  es.series.forEach(function (s) { all = all.concat(s.mean.filter(function (v) { return v != null; })); });
  var m = Math.max(0.5, Math.ceil(Math.max.apply(null, all.map(Math.abs)) * 4 + 0.5) / 4);
  var label = function (w) { return w === 0 ? "0" : w + "w"; };
  H.chart(el, {
    data: [es.offsets_weeks].concat(es.series.map(function (s) { return s.mean; })),
    series: es.series.map(function (s) {
      return { label: s.decision.charAt(0).toUpperCase() + s.decision.slice(1), color: colour[s.decision] || "ink-2", width: 2.5 };
    }),
    y: [-m, m], zero: true,
    xValues: function (u, ticks) { return ticks.map(label); },
    yValues: function (u, ticks) { return ticks.map(H.fmtStance); },
    tipX: function (w) { return w === 0 ? "Week of the decision" : Math.abs(w) + " weeks before"; },
  });
})();
