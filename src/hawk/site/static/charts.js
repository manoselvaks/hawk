// Thin wrapper over uPlot: theme-aware colours, era bands, markers and a tooltip.
// Charts are rebuilt when the theme changes and resized with their container.
(function () {
  "use strict";
  var css = function (name) {
    return getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();
  };
  var fmtStance = function (v) {
    if (v == null) return "–";
    return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2);
  };
  var fmtMonth = function (t) {
    return new Date(t * 1000).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
  };
  var fmtDay = function (t) {
    return new Date(t * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  };

  // Line or fill coloured hawk above zero and dove below it.
  function signedGradient(u, alphaKeys) {
    var ctx = u.ctx, top = u.bbox.top, h = u.bbox.height;
    var y0 = u.valToPos(0, "y", true);
    var f = Math.min(1, Math.max(0, (y0 - top) / h));
    var g = ctx.createLinearGradient(0, top, 0, top + h);
    g.addColorStop(0, css(alphaKeys[0]));
    g.addColorStop(f, css(alphaKeys[0]));
    g.addColorStop(f, css(alphaKeys[1]));
    g.addColorStop(1, css(alphaKeys[1]));
    return g;
  }

  function drawBands(u, bands, labels) {
    var ctx = u.ctx, b = u.bbox;
    ctx.save();
    ctx.fillStyle = css("era");
    var lastEnd = -Infinity;
    bands.forEach(function (e) {
      var x0 = Math.max(b.left, u.valToPos(e.from, "x", true));
      var x1 = Math.min(b.left + b.width, u.valToPos(e.to, "x", true));
      if (x1 <= x0) return;
      ctx.fillRect(x0, b.top, x1 - x0, b.height);
      if (labels && x1 - x0 > 0) {
        ctx.fillStyle = css("muted");
        ctx.font = "600 " + Math.round(10.5 * devicePixelRatio) + "px " + css("font");
        ctx.textBaseline = "top";
        var short = u.width < 560;
        var text = short ? e.label.split(" ")[0] : e.label;
        var tx = Math.max(x0 + 4 * devicePixelRatio, lastEnd + 8 * devicePixelRatio);
        var tw = ctx.measureText(text).width;
        if (tx + tw <= b.left + b.width) {
          ctx.fillText(text, tx, b.top + 4 * devicePixelRatio);
          lastEnd = tx + tw;
        }
        ctx.fillStyle = css("era");
      }
    });
    ctx.restore();
  }

  function drawZero(u) {
    var ctx = u.ctx, b = u.bbox, y = u.valToPos(0, "y", true);
    if (y < b.top || y > b.top + b.height) return;
    ctx.save();
    ctx.strokeStyle = css("line-strong");
    ctx.lineWidth = devicePixelRatio;
    ctx.beginPath(); ctx.moveTo(b.left, y); ctx.lineTo(b.left + b.width, y); ctx.stroke();
    ctx.restore();
  }

  function drawMarkers(u, markers) {
    var ctx = u.ctx, r = 4.5 * devicePixelRatio;
    ctx.save();
    markers.forEach(function (m) {
      var x = u.valToPos(m.x, "x", true), y = u.valToPos(m.y, "y", true);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = css(m.color);
      ctx.fill();
      ctx.lineWidth = 1.5 * devicePixelRatio;
      ctx.strokeStyle = css("surface");
      ctx.stroke();
    });
    ctx.restore();
  }

  function axis(opts) {
    return Object.assign({
      stroke: css("muted"),
      font: "11px " + css("font"),
      grid: { stroke: css("line"), width: 1 },
      ticks: { show: false },
      gap: 6,
    }, opts || {});
  }

  /**
   * spec: {
   *   data: [x[], y1[], ...], series: [{label, color, kind: line|step|points, width, signed, fmt}],
   *   time: bool, y: [min, max] | fn, x: [min, max], bands: [{from,to,label}], bandLabels: bool,
   *   markers: [{x, y, color, label}], zero: bool, sync: key, tipX: fn(x)
   * }
   */
  function chart(el, spec) {
    var u = null, tip = document.createElement("div");
    tip.className = "tip";
    tip.setAttribute("aria-hidden", "true");

    function build() {
      if (u) u.destroy();
      el.textContent = "";
      el.appendChild(tip);
      var series = [{}].concat(spec.series.map(function (s) {
        var out = {
          label: s.label,
          width: s.width || 2,
          spanGaps: !!s.spanGaps,
          points: { show: false },
        };
        if (s.signed) {
          out.stroke = function (u) { return signedGradient(u, ["hawk", "dove"]); };
          out.fill = function (u) { return signedGradient(u, ["hawk-soft", "dove-soft"]); };
          out.fillTo = 0;
        } else {
          out.stroke = css(s.color);
        }
        if (s.kind === "step") out.paths = uPlot.paths.stepped({ align: 1 });
        if (s.kind === "points") {
          out.paths = function () { return null; };
          out.points = { show: true, size: 10, width: 1.5, fill: css(s.color), stroke: css("surface") };
        }
        return out;
      }));
      var opts = {
        width: el.clientWidth,
        height: el.clientHeight,
        padding: [8, 4, 0, 0],
        legend: { show: false },
        cursor: {
          drag: { x: false, y: false },
          points: { size: 8, width: 2, fill: css("surface") },
          sync: spec.sync ? { key: spec.sync } : undefined,
          focus: { prox: 30 },
        },
        scales: {
          x: { time: !!spec.time, range: spec.x ? function () { return spec.x; } : undefined },
          y: { range: spec.y },
        },
        axes: [
          axis({ space: 60, values: spec.time ? undefined : spec.xValues }),
          axis({ size: 42, values: spec.yValues }),
        ],
        series: series,
        hooks: {
          drawAxes: [function (u) {
            if (spec.bands) drawBands(u, spec.bands, spec.bandLabels);
            if (spec.zero) drawZero(u);
          }],
          draw: [function (u) { if (spec.markers) drawMarkers(u, spec.markers); }],
          setCursor: [function (u) {
            var i = u.cursor.idx;
            if (i == null || u.cursor.left < 0) { tip.classList.remove("on"); return; }
            var x = u.data[0][i];
            if (spec.tipAt) { show(u, spec.tipAt(u.posToVal(u.cursor.left, "x"))); return; }
            var rows = spec.series.map(function (s, k) {
              var v = u.data[k + 1][i];
              if (v == null || s.tip === false) return "";
              return '<div><span class="k">' + s.label + "</span> <b>" + (s.fmt || fmtStance)(v) + "</b></div>";
            }).join("");
            if (spec.tipExtra) rows += spec.tipExtra(x);
            if (!rows) { tip.classList.remove("on"); return; }
            show(u, "<div>" + (spec.tipX || (spec.time ? fmtMonth : String))(x) + "</div>" + rows);
          }],
        },
      };
      function show(u, html) {
            if (!html) { tip.classList.remove("on"); return; }
            tip.innerHTML = html;
            var left = u.cursor.left + u.bbox.left / devicePixelRatio;
            var w = tip.offsetWidth;
            tip.style.left = Math.min(Math.max(0, left - w / 2), el.clientWidth - w) + "px";
            tip.style.top = "-6px";
            tip.style.transform = "translateY(-100%)";
            tip.classList.add("on");
      }
      u = new uPlot(opts, spec.data, el);
      el.addEventListener("mouseleave", function () { tip.classList.remove("on"); });
    }
    build();
    document.addEventListener("hawk:theme", build);
    if ("ResizeObserver" in window) {
      var last = el.clientWidth;
      new ResizeObserver(function () {
        if (u && el.clientWidth !== last) { last = el.clientWidth; u.setSize({ width: el.clientWidth, height: el.clientHeight }); }
      }).observe(el);
    }
    return { get: function () { return u; } };
  }

  window.HawkCharts = { chart: chart, css: css, fmtStance: fmtStance, fmtMonth: fmtMonth, fmtDay: fmtDay };
})();
