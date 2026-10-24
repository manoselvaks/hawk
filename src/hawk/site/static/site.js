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

  // Reveal on scroll, as progressive enhancement: everything is visible until this runs,
  // and only elements that start below the fold are hidden and faded in. Skipped for
  // reduced motion and automated browsers (screenshots, audits).
  var items = document.querySelectorAll(".reveal");
  var skip = !("IntersectionObserver" in window) || navigator.webdriver ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!skip) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -6% 0px" });
    var fold = window.innerHeight;
    var n = 0;
    items.forEach(function (el) {
      if (el.getBoundingClientRect().top < fold) return;
      el.classList.add("reveal-pending");
      el.style.transitionDelay = Math.min(n++ % 6, 5) * 50 + "ms";
      io.observe(el);
    });
  }
})();
