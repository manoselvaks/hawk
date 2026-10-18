// Speech explorer: filters live in the query string, the open document in the hash.
(function () {
  "use strict";
  var ROOT = window.HAWK_ROOT || "../";
  var PAGE = 60;
  var $ = function (id) { return document.getElementById(id); };
  var form = $("filters"), list = $("results"), count = $("count"), more = $("more"), dlg = $("detail");
  var docs = [], byId = {}, meta = null, shown = PAGE, matches = [];

  var fmt = function (v) {
    if (v == null) return "–";
    return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2);
  };
  var cls = function (v) { return v == null ? "none" : v > 0.05 ? "hawk" : v < -0.05 ? "dove" : "neutral"; };
  var esc = function (s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var opt = function (sel, value, text) {
    var o = document.createElement("option"); o.value = value; o.textContent = text; sel.appendChild(o);
  };
  var longDate = function (iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  };

  function load(json) {
    meta = json;
    var c = {};
    json.columns.forEach(function (name, i) { c[name] = i; });
    docs = json.rows.map(function (r) {
      var speaker = r[c.speaker] >= 0 ? json.speakers[r[c.speaker]] : null;
      var d = {
        id: r[c.id], kind: r[c.kind], date: r[c.date], year: +r[c.date].slice(0, 4), speaker: speaker,
        title: r[c.title], url: json.url_prefix + r[c.url], mpc: r[c.mpc], rel: r[c.relevance],
        stance: r[c.stance], conf: r[c.confidence], reason: r[c.reason], base: r[c.baseline],
      };
      d.hay = (d.title + " " + (speaker || "MPC minutes")).toLowerCase();
      byId[d.id] = d;
      return d;
    });
    json.speakers.forEach(function (s) { opt($("f-speaker"), s, s); });
    var y0 = docs.length ? docs[0].year : 1997, y1 = docs.length ? docs[docs.length - 1].year : 2026;
    for (var y = y0; y <= y1; y++) { opt($("f-from"), y, y); opt($("f-to"), y, y); }
    for (var s = -2; s <= 2; s += 0.5) {
      var t = s === 0 ? "0" : fmt(s).replace(".00", "").replace(".50", ".5");
      opt($("f-smin"), s, t); opt($("f-smax"), s, t);
    }
    readState();
    apply();
    openFromHash();
  }

  var FIELDS = ["q", "speaker", "kind", "from", "to", "smin", "smax", "rel", "mpc", "sort"];
  function defaults() {
    $("f-from").selectedIndex = 0;
    $("f-to").selectedIndex = $("f-to").options.length - 1;
    $("f-smin").value = "-2"; $("f-smax").value = "2";
    $("f-rel").value = "0"; $("o-rel").textContent = "0.0";
  }
  function readState() {
    defaults();
    var p = new URLSearchParams(location.search);
    FIELDS.forEach(function (k) {
      var el = form.elements[k] || $("f-" + k);
      if (!p.has(k) || !el) return;
      if (el.type === "checkbox") el.checked = p.get(k) === "1"; else el.value = p.get(k);
    });
    $("o-rel").textContent = (+$("f-rel").value).toFixed(1);
  }
  function writeState() {
    var p = new URLSearchParams();
    var def = { from: $("f-from").options[0].value, to: $("f-to").options[$("f-to").options.length - 1].value, smin: "-2", smax: "2", rel: "0", sort: "new" };
    FIELDS.forEach(function (k) {
      var el = form.elements[k] || $("f-" + k);
      var v = el.type === "checkbox" ? (el.checked ? "1" : "") : el.value;
      if (v && v !== def[k]) p.set(k, v);
    });
    var qs = p.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
  }

  function apply() {
    var q = $("f-q").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var speaker = $("f-speaker").value, kind = $("f-kind").value;
    var from = +$("f-from").value, to = +$("f-to").value;
    var smin = +$("f-smin").value, smax = +$("f-smax").value;
    if (smin > smax) { var t = smin; smin = smax; smax = t; }
    var fullStance = smin <= -2 && smax >= 2;
    var rel = +$("f-rel").value, mpcOnly = $("f-mpc").checked;
    matches = docs.filter(function (d) {
      if (kind && d.kind !== kind) return false;
      if (speaker && d.speaker !== speaker) return false;
      if (d.year < from || d.year > to) return false;
      if (mpcOnly && d.kind === "s" && d.mpc !== 1) return false;
      if (rel > 0 && !(d.rel >= rel - 1e-9)) return false;
      if (!fullStance && (d.stance == null || d.stance < smin || d.stance > smax)) return false;
      for (var i = 0; i < q.length; i++) if (d.hay.indexOf(q[i]) < 0) return false;
      return true;
    });
    var sort = $("f-sort").value;
    var key = function (d) { return d.stance == null ? null : d.stance; };
    if (sort === "old") matches.sort(function (a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : 0; });
    else if (sort === "hawk" || sort === "dove") {
      var sign = sort === "hawk" ? -1 : 1;
      matches = matches.filter(function (d) { return key(d) != null; })
        .sort(function (a, b) { return sign * (a.stance - b.stance) || (a.date < b.date ? 1 : -1); });
    } else matches.sort(function (a, b) { return a.date < b.date ? 1 : a.date > b.date ? -1 : 0; });
    shown = PAGE;
    render();
    writeState();
  }

  function row(d) {
    var who = d.kind === "m" ? "Monetary Policy Committee" : (d.speaker || "Unknown speaker");
    var badge = d.kind === "m" ? '<span class="doc-badge">Minutes</span>' : d.mpc === 1 ? '<span class="doc-badge">MPC</span>' : "";
    var stance = d.rel != null && d.rel < 0.3 ? null : d.stance;
    return '<li><button type="button" class="doc" data-id="' + d.id + '">' +
      '<span class="doc-date">' + d.date + "</span>" +
      '<span class="doc-title">' + esc(d.title) + '<span class="doc-sub">' + esc(who) + badge + "</span></span>" +
      '<span class="pill pill-' + cls(stance) + '" aria-label="Stance ' + fmt(stance) + '">' + fmt(stance) + "</span>" +
      "</button></li>";
  }

  function render() {
    var n = matches.length;
    count.textContent = n.toLocaleString("en-GB") + (n === 1 ? " document" : " documents");
    list.innerHTML = matches.slice(0, shown).map(row).join("");
    more.hidden = shown >= n;
    if (!n) list.innerHTML = '<li class="muted" style="padding:24px 12px">Nothing matches these filters.</li>';
  }

  function open(d) {
    $("d-meta").textContent = (d.kind === "m" ? "MPC minutes" : "Speech") + " · published " + longDate(d.date);
    $("d-title").textContent = d.title;
    $("d-speaker").textContent = d.kind === "m" ? "Monetary Policy Committee" :
      (d.speaker || "") + (d.mpc === 1 ? " · sitting MPC member" : d.mpc === 0 ? " · not on the MPC at the time" : "");
    $("d-stance").innerHTML = '<span class="pill pill-' + cls(d.stance) + '">' + fmt(d.stance) + "</span>";
    $("d-rel").textContent = d.rel == null ? "–" : d.rel.toFixed(2);
    $("d-conf").textContent = d.conf == null ? "–" : Math.round(d.conf * 100) + "%";
    $("d-base").textContent = fmt(d.base);
    $("d-reason").textContent = d.reason || (d.stance == null ? "Not about monetary policy, so no stance was given." : "");
    var dot = $("d-dot");
    dot.style.left = d.stance == null ? "50%" : ((d.stance + 2) / 4) * 100 + "%";
    dot.style.opacity = d.stance == null ? "0.3" : "1";
    $("d-link").href = d.url;
    var slug = d.speaker && meta.members[d.speaker];
    $("d-member").hidden = !slug;
    if (slug) $("d-member").href = ROOT + "members/" + slug + "/";
    if (location.hash !== "#doc=" + d.id) history.replaceState(null, "", location.pathname + location.search + "#doc=" + d.id);
    if (!dlg.open) { if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", ""); }
    dlg.querySelector(".sheet-inner").focus();
  }
  function openFromHash() {
    var m = location.hash.match(/^#doc=(.+)$/);
    if (m && byId[m[1]]) open(byId[m[1]]);
  }

  list.addEventListener("click", function (e) {
    var b = e.target.closest(".doc");
    if (b) open(byId[b.dataset.id]);
  });
  dlg.addEventListener("close", function () {
    history.replaceState(null, "", location.pathname + location.search);
  });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  dlg.querySelector(".sheet-close").addEventListener("click", function () { dlg.close(); });
  window.addEventListener("hashchange", openFromHash);
  more.addEventListener("click", function () { shown += PAGE * 2; render(); });

  var timer = null;
  form.addEventListener("input", function (e) {
    if (e.target.id === "f-rel") $("o-rel").textContent = (+e.target.value).toFixed(1);
    clearTimeout(timer);
    timer = setTimeout(apply, e.target.id === "f-q" ? 140 : 0);
  });
  $("f-sort").addEventListener("change", apply);
  form.addEventListener("reset", function () { setTimeout(function () { defaults(); apply(); }, 0); });
  var toggle = form.querySelector(".f-more");
  toggle.addEventListener("click", function () {
    var open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    $("f-panel").classList.toggle("open", open);
  });

  fetch(ROOT + "data/docs.json")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(load)
    .catch(function () { count.textContent = "Could not load the documents."; });
})();
