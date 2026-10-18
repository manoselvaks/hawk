// Member page: one dot per speech, coloured by stance, over the committee's trailing tone.
(function () {
  "use strict";
  var H = window.HawkCharts;
  var d = JSON.parse(document.getElementById("member-data").textContent);
  var c = d.chart;
  var pick = function (test) { return c.stance.map(function (v) { return test(v) ? v : null; }); };
  // uPlot needs one x array: merge speech dates with the committee's month ends.
  var joined = uPlot.join([
    [c.x, pick(function (v) { return v > 0; }), pick(function (v) { return v < 0; }), pick(function (v) { return v === 0; })],
    [d.committee.x, d.committee.tone],
  ]);
  var all = c.stance.concat(d.committee.tone.filter(function (v) { return v != null; }));
  var m = Math.max(1, Math.ceil(Math.max.apply(null, all.map(Math.abs)) * 2) / 2);
  H.chart(document.getElementById("member-chart"), {
    data: joined,
    series: [
      { label: "Hawkish speech", color: "hawk", kind: "points" },
      { label: "Dovish speech", color: "dove", kind: "points" },
      { label: "Neutral speech", color: "neutral", kind: "points" },
      { label: "Committee", color: "ink-2", width: 1.5, spanGaps: true },
    ],
    time: true, y: [-m, m], zero: true,
    x: [Math.min(c.first, c.x[0]) - 86400 * 30, Math.max(c.last, c.x[c.x.length - 1]) + 86400 * 30],
    tipX: H.fmtDay,
    yValues: function (u, ticks) { return ticks.map(H.fmtStance); },
  });
})();
