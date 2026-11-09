(function () {
  "use strict";

  // ---- Chart crosshair tooltips (the chart is complete without them) ----
  function fmt(v) {
    var a = Math.abs(v);
    var d = a >= 1000 ? 0 : a >= 100 ? 1 : 2;
    return v.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtDate(s) {
    var p = s.split("-");
    var dt = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    return dt.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }
  function wireChart(box) {
    var data;
    try { data = JSON.parse(box.getAttribute("data-chart")); } catch (e) { return; }
    var svg = box.querySelector("svg");
    if (!svg || !data || !data.p || data.p.length < 2) return;
    var fig = box.closest("figure") || box;
    var ns = "http://www.w3.org/2000/svg";
    var g = document.createElementNS(ns, "g");
    g.setAttribute("class", "hover");
    g.style.display = "none";
    var ln = document.createElementNS(ns, "line");
    ln.setAttribute("y1", data.y0); ln.setAttribute("y2", data.y1);
    var c = document.createElementNS(ns, "circle"); c.setAttribute("r", "4");
    g.appendChild(ln); g.appendChild(c); svg.appendChild(g);
    var tip = document.createElement("div"); tip.className = "tip"; tip.hidden = true; fig.appendChild(tip);
    var n = data.p.length;
    function show(clientX) {
      var r = svg.getBoundingClientRect();
      var sx = (clientX - r.left) * (data.w / r.width);
      var i = Math.round((sx - data.x0) / (data.x1 - data.x0) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      var x = data.x0 + (data.x1 - data.x0) * i / (n - 1);
      var v = data.p[i][1];
      var y = data.y1 - (data.y1 - data.y0) * (v - data.lo) / (data.hi - data.lo);
      ln.setAttribute("x1", x); ln.setAttribute("x2", x);
      c.setAttribute("cx", x); c.setAttribute("cy", y);
      g.style.display = "";
      var fr = fig.getBoundingClientRect();
      tip.textContent = fmtDate(data.p[i][0]) + "  ·  " + fmt(v);
      tip.style.left = (r.left - fr.left + x * r.width / data.w) + "px";
      tip.style.top = (r.top - fr.top + y * r.height / data.h) + "px";
      tip.hidden = false;
    }
    function hide() { g.style.display = "none"; tip.hidden = true; }
    svg.addEventListener("pointermove", function (e) { show(e.clientX); });
    svg.addEventListener("pointerdown", function (e) { show(e.clientX); });
    svg.addEventListener("pointerleave", hide);
  }
  function wireCharts(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll(".svgbox[data-chart]"), wireChart);
  }

  // ---- Freshness check: never let an old edition pass as today's ----
  function checkFreshness(root) {
    var el = (root || document).querySelector("[data-next-expected]");
    if (!el) return;
    var due = Date.parse(el.getAttribute("data-next-expected"));
    var slot = document.getElementById("freshness");
    if (!slot || isNaN(due)) return;
    var grace = 90 * 60 * 1000;
    if (Date.now() > due + grace) {
      var d = new Date(due);
      slot.innerHTML = "";
      var b = document.createElement("div");
      b.className = "banner crit";
      b.setAttribute("role", "status");
      var span = document.createElement("span");
      var s = document.createElement("strong");
      s.textContent = "Not today's edition. ";
      span.appendChild(s);
      b.appendChild(span);
      span.appendChild(document.createTextNode(
        "A newer edition was due by " +
        d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" }) +
        " London time and has not been published. Prices and views below are from the date shown in the masthead. Check the run status in Sources & method."));
      slot.appendChild(b);
      slot.hidden = false;
    }
  }


  // ---- Reader preferences: language, second currency, theme (kept in this browser only) ----
  var KEY = "cheez.prefs";
  var LANG_ATTR = { "en": "en", "zh-Hant": "zhHant", "zh-Hans": "zhHans" };
  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { return {}; }
  }
  function savePrefs(p) {
    try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) { /* private mode: preferences last for this visit */ }
  }
  var main0 = document.getElementById("edition");
  var defaults = { lang: main0 ? main0.getAttribute("data-lang") || "en" : "en", fx: main0 ? main0.getAttribute("data-fx") || "" : "" };
  var prefs = loadPrefs();
  function pref(k) { return Object.prototype.hasOwnProperty.call(prefs, k) ? prefs[k] : defaults[k]; }

  // Rates and formatting rules come from the edition (mirrors format.converted() on the server).
  function fxTable(root) {
    var el = (root || document).querySelector("script.cheez-fx");
    try { return JSON.parse(el.textContent); } catch (e) { return {}; }
  }
  function convert(v, from, to, fx, suf) {
    var rates = fx.per_usd || {};
    if (!to || to === from || !rates[from] || !rates[to]) return null;
    var x = v / rates[from] * rates[to];
    var sym = (fx.symbols || {})[to] || to + " ";
    if (suf) return "≈" + sym + (x / fx.suffix[suf]).toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + suf;
    var d = (fx.zero_decimal || []).indexOf(to) >= 0 || Math.abs(x) >= 10000 ? 0 : 2;
    return "≈" + sym + x.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function applyFx(root) {
    var to = pref("fx");
    var fx = fxTable(root);
    Array.prototype.forEach.call((root || document).querySelectorAll("ruby.m"), function (r) {
      Array.prototype.slice.call(r.querySelectorAll("rt, rp")).forEach(function (n) { n.remove(); });
      var txt = convert(parseFloat(r.getAttribute("data-v")), r.getAttribute("data-c"), to, fx, r.getAttribute("data-s"));
      if (!txt) return;
      var rp1 = document.createElement("rp"); rp1.textContent = "(";
      var rt = document.createElement("rt"); rt.textContent = txt;
      var rp2 = document.createElement("rp"); rp2.textContent = ")";
      r.appendChild(rp1); r.appendChild(rt); r.appendChild(rp2);
    });
  }
  function applyLang(root) {
    var lang = pref("lang");
    var key = LANG_ATTR[lang] || "en";
    Array.prototype.forEach.call((root || document).querySelectorAll("[data-i18n]"), function (el) {
      var val = el.dataset[key] || el.dataset.en;
      if (val == null) return;
      if (el.getAttribute("data-i18n") === "h") el.innerHTML = val; else el.textContent = val;
    });
    document.documentElement.setAttribute("lang", lang === "en" ? "en-GB" : lang);
  }
  function applyTheme() {
    var t = pref("theme");
    if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
  }
  function applyPrefs(root) { applyLang(root); applyFx(root); }

  function wireSettings() {
    var dlg = document.getElementById("settings");
    var btn = document.getElementById("open-settings");
    if (!dlg || !btn) return;
    var form = dlg.querySelector("form");
    function sync() {
      Array.prototype.forEach.call(form.querySelectorAll("input[name=lang]"), function (i) { i.checked = i.value === pref("lang"); });
      Array.prototype.forEach.call(form.querySelectorAll("input[name=theme]"), function (i) { i.checked = i.value === (pref("theme") || ""); });
      var sel = form.querySelector("select[name=fx]");
      if (sel) sel.value = pref("fx") || "";
    }
    btn.addEventListener("click", function () {
      sync();
      if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
    });
    form.addEventListener("change", function (e) {
      var t = e.target;
      if (!t || !t.name) return;
      prefs[t.name] = t.value;
      savePrefs(prefs);
      if (t.name === "theme") applyTheme(); else applyPrefs(document);
    });
  }

  // ---- Highlight the section in view ----
  function wireNav() {
    var links = Array.prototype.slice.call(document.querySelectorAll(".edbar nav a[href^='#']"));
    if (!("IntersectionObserver" in window) || !links.length) return;
    var byId = {};
    links.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (a) { a.classList.remove("active"); });
        var a = byId[en.target.id];
        if (a) a.classList.add("active");
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    Object.keys(byId).forEach(function (id) { var el = document.getElementById(id); if (el) io.observe(el); });
  }

  // ---- Archive: open past editions in place (index page only) ----
  var main = document.getElementById("edition");
  var latestHTML = main ? main.innerHTML : null;
  function openEdition(id) {
    if (!main) return;
    if (!id || id === "latest") {
      main.innerHTML = latestHTML;
      wireCharts(main); checkFreshness(main); applyPrefs(main);
      return;
    }
    if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z-]+$/.test(id)) return;
    var tpl = document.getElementById("tpl-" + id);
    if (tpl && tpl.content) {
      main.innerHTML = "";
      var note = document.createElement("div");
      note.className = "wrap";
      note.innerHTML = "<div class=\"banner warn\" role=\"note\"><span><strong>Archive edition.</strong> You are reading a past edition; prices and views are as of its date. <a href=\"#latest\">Return to the latest edition</a>.</span></div>";
      main.appendChild(note);
      main.appendChild(tpl.content.cloneNode(true));
      wireCharts(main); applyPrefs(main);
      window.scrollTo(0, 0);
      return;
    }
    var url = "editions/" + id + ".html";
    fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (txt) {
      var doc = new DOMParser().parseFromString(txt, "text/html");
      var m = doc.getElementById("edition");
      if (!m) throw new Error("no edition");
      main.innerHTML = m.innerHTML;
      var back = document.createElement("div");
      back.className = "banner warn";
      back.innerHTML = "<span><strong>Archive edition.</strong> You are reading a past edition. <a href=\"#latest\">Return to the latest edition</a>.</span>";
      main.insertBefore(back, main.firstChild);
      wireCharts(main); applyPrefs(main);
      window.scrollTo(0, 0);
    }).catch(function () {
      window.location.href = url;  // fall back to opening the file directly
    });
  }
  function route() {
    var h = (location.hash || "").replace(/^#/, "");
    if (h.indexOf("ed-") === 0) openEdition(h.slice(3));
    else if (h === "latest") openEdition("latest");
  }
  window.addEventListener("hashchange", route);

  applyTheme();
  wireCharts(document);
  checkFreshness(document);
  if (pref("lang") !== defaults.lang || pref("fx") !== defaults.fx) applyPrefs(document);
  wireSettings();
  wireNav();
  route();
})();
