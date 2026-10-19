// Home page hero: tone index above Bank Rate, sharing one time axis and one cursor.
(function () {
  "use strict";
  var H = window.HawkCharts;
  var data = JSON.parse(document.getElementById("hero-data").textContent);
  var tone = data.tone, rate = data.rate;
  if (!tone.x.length) return;
  var xr = [Math.min(tone.x[0], rate.x[0]), Math.max(tone.x[tone.x.length - 1], rate.x[rate.x.length - 1])];
  xr[0] = Math.max(xr[0], tone.x[0] - 86400 * 60);
  var vals = tone.tone.filter(function (v) { return v != null; });
  var m = Math.max(0.5, Math.ceil(Math.max.apply(null, vals.map(Math.abs)) * 4 + 0.5) / 4);
  var byMonth = {};
  rate.moves.forEach(function (mv) {
    var d = new Date(mv.x * 1000), k = d.getUTCFullYear() * 12 + d.getUTCMonth();
    (byMonth[k] = byMonth[k] || []).push(mv);
  });
  var movesNear = function (x) {
    var d = new Date(x * 1000), k = d.getUTCFullYear() * 12 + d.getUTCMonth();
    return (byMonth[k] || []).map(function (mv) {
      return '<div><span class="k">' + mv.date + "</span> <b class=\"t-" + (mv.decision === "hike" ? "hawk" : "dove") + '">' +
        (mv.bp > 0 ? "+" : "−") + Math.abs(mv.bp) + "bp</b></div>";
    }).join("");
  };

  H.chart(document.getElementById("tone-chart"), {
    data: [tone.x, tone.tone],
    series: [{ label: "Tone", signed: true, width: 2 }],
    time: true, x: xr, y: [-m, m], zero: true, sync: "hero",
    bands: data.eras, bandLabels: true,
    yValues: function (u, ticks) { return ticks.map(H.fmtStance); },
  });
  H.chart(document.getElementById("rate-chart"), {
    data: [rate.x, rate.rate],
    series: [{ label: "Bank Rate", color: "ink-2", kind: "step", width: 1.75, fmt: function (v) { return v.toFixed(2) + "%"; } }],
    time: true, x: xr, y: function (u, lo, hi) { return [0, Math.ceil(hi + 0.5)]; }, sync: "hero",
    bands: data.eras,
    markers: rate.moves.map(function (mv) { return { x: mv.x, y: mv.rate, color: mv.decision === "hike" ? "hawk" : "dove" }; }),
    tipAt: function (x) {
      var r = rate.rate[0];
      for (var i = 0; i < rate.x.length && rate.x[i] <= x; i++) r = rate.rate[i];
      return "<div>" + H.fmtMonth(x) + '</div><div><span class="k">Bank Rate</span> <b>' + r.toFixed(2) + "%</b></div>" + movesNear(x);
    },
    yValues: function (u, ticks) { return ticks.map(function (t) { return t + "%"; }); },
  });
})();
