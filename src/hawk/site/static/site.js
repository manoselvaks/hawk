// Theme toggle, mobile menu and scroll reveals. No dependencies.
(function () {
  "use strict";
  var root = document.documentElement;
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function effective() {
    return root.dataset.theme || (media.matches ? "dark" : "light");
  }
  function sync() {
    root.dataset.themeEffective = effective();
    var meta = document.querySelectorAll('meta[name="theme-color"]');
    var bg = getComputedStyle(root).getPropertyValue("--bg").trim();
    meta.forEach(function (m) { m.setAttribute("content", bg); });
    document.dispatchEvent(new CustomEvent("hawk:theme"));
  }
  sync();
  media.addEventListener("change", function () { if (!root.dataset.theme) sync(); });

  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = effective() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("hawk-theme", next); } catch (e) { /* private mode */ }
      sync();
    });
  }

  var navBtn = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");
  if (navBtn && links) {
    navBtn.addEventListener("click", function () {
      var open = navBtn.getAttribute("aria-expanded") !== "true";
      navBtn.setAttribute("aria-expanded", String(open));
      links.classList.toggle("open", open);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && links.classList.contains("open")) {
        navBtn.setAttribute("aria-expanded", "false");
        links.classList.remove("open");
        navBtn.focus();
      }
    });
  }

  // Reveal on scroll. Elements already on screen appear straight away.
  var items = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    items.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -6% 0px" });
    items.forEach(function (el, i) {
      el.style.transitionDelay = Math.min(i % 6, 5) * 50 + "ms";
      io.observe(el);
    });
  }
})();
