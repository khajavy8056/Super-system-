/* Jalali (Persian) calendar helpers — pure arithmetic, offline, no deps.
 * Algorithm: Behrooz Kamali / jalaali-js (MIT-compatible, re-implemented). */
(function (global) {
  "use strict";
  function div(a, b) { return ~~(a / b); }
  function mod(a, b) { return a - ~~(a / b) * b; }
  function g2d(gy, gm, gd) {
    var d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4) + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408;
    return d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
  }
  function d2g(jdn) {
    var j = 4 * jdn + 139361631; j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
    var i = div(mod(j, 1461), 4) * 5 + 308;
    var gd = div(mod(i, 153), 5) + 1, gm = mod(div(i, 153), 12) + 1, gy = div(j, 1461) - 100100 + div(8 - gm, 6);
    return [gy, gm, gd];
  }
  function jalCal(jy) {
    var breaks = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];
    var bl = breaks.length, gy = jy + 621, leapJ = -14, jp = breaks[0], jm, jump, leap, n, i;
    for (i = 1; i < bl; i += 1) { jm = breaks[i]; jump = jm - jp; if (jy < jm) break; leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4); jp = jm; }
    n = jy - jp; leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
    if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
    var leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150, march = 20 + leapJ - leapG;
    if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
    leap = mod(mod(n + 1, 33) - 1, 4); if (leap === -1) leap = 4;
    return { leap: leap, gy: gy, march: march };
  }
  function j2d(jy, jm, jd) { var r = jalCal(jy); return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1; }
  function d2j(jdn) {
    var gy = d2g(jdn)[0], jy = gy - 621, r = jalCal(jy), jdn1f = g2d(gy, 3, r.march), jd, jm, k;
    k = jdn - jdn1f;
    if (k >= 0) { if (k <= 185) { jm = 1 + div(k, 31); jd = mod(k, 31) + 1; return [jy, jm, jd]; } else k -= 186; }
    else { jy -= 1; k += 179; if (r.leap === 1) k += 1; }
    jm = 7 + div(k, 30); jd = mod(k, 30) + 1; return [jy, jm, jd];
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  var MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
  var J = {
    months: MONTHS,
    toJalali: function (gy, gm, gd) { return d2j(g2d(gy, gm, gd)); },
    toGregorian: function (jy, jm, jd) { return d2g(j2d(jy, jm, jd)); },
    monthLength: function (jy, jm) { if (jm <= 6) return 31; if (jm <= 11) return 30; return jalCal(jy).leap === 0 ? 30 : 29; },
    /* "1403/06/15" -> "2024-09-05" (returns null on invalid) */
    toIso: function (jstr) {
      if (!jstr) return null;
      var s = String(jstr).replace(/[۰-۹]/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹".indexOf(d); }).trim();
      var m = s.match(/^(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})$/);
      if (!m) return null;
      var jy = +m[1], jm = +m[2], jd = +m[3];
      if (jm < 1 || jm > 12 || jd < 1 || jd > J.monthLength(jy, jm)) return null;
      var g = d2g(j2d(jy, jm, jd)); return g[0] + "-" + pad(g[1]) + "-" + pad(g[2]);
    },
    /* "2024-09-05" (or ISO datetime) -> "۱۴۰۳/۰۶/۱۵" */
    fromIso: function (iso, opts) {
      if (!iso) return "";
      var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/); if (!m) return "";
      var j = d2j(g2d(+m[1], +m[2], +m[3]));
      var out = j[0] + "/" + pad(j[1]) + "/" + pad(j[2]);
      return (opts && opts.latin) ? out : out.replace(/\d/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹"[d]; });
    },
    todayIso: function () { var d = new Date(); return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); },
    todayJalali: function () { return J.fromIso(J.todayIso(), { latin: true }); },
    /* Upgrade an <input> into a Jalali date field. Reads/writes ISO via el.value
       through a hidden mirror: the visible box shows/accepts ۱۴۰۳/۰۶/۱۵. */
    attach: function (input) {
      if (!input || input.dataset.jalali) return input;
      input.dataset.jalali = "1";
      var iso = input.value || "";
      var hidden = document.createElement("input");
      hidden.type = "hidden"; hidden.id = input.id; hidden.name = input.name || ""; hidden.value = iso;
      input.removeAttribute("id"); input.removeAttribute("name"); input.type = "text";
      input.setAttribute("dir", "ltr"); input.setAttribute("inputmode", "numeric");
      input.placeholder = "۱۴۰۳/۰۶/۱۵"; input.classList.add("jdate");
      input.value = iso ? J.fromIso(iso) : "";
      input.parentNode.insertBefore(hidden, input.nextSibling);
      var wrap = document.createElement("div"); wrap.className = "jdate-wrap";
      input.parentNode.insertBefore(wrap, input); wrap.appendChild(input); wrap.appendChild(hidden);
      var btn = document.createElement("button"); btn.type = "button"; btn.className = "jdate-btn"; btn.title = "تقویم"; btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>';
      wrap.appendChild(btn);
      function sync() {
        var v = J.toIso(input.value);
        input.classList.toggle("bad", !!input.value && !v);
        hidden.value = v || "";
        hidden.dispatchEvent(new Event("change", { bubbles: true }));
      }
      input.addEventListener("input", sync); input.addEventListener("blur", function () { if (hidden.value) input.value = J.fromIso(hidden.value); });
      btn.addEventListener("click", function () { J.openPicker(hidden.value || J.todayIso(), function (isoPicked) { hidden.value = isoPicked; input.value = J.fromIso(isoPicked); input.classList.remove("bad"); hidden.dispatchEvent(new Event("change", { bubbles: true })); }); });
      Object.defineProperty(hidden, "jalaliInput", { value: input });
      hidden.setIso = function (isoNew) { hidden.value = isoNew || ""; input.value = isoNew ? J.fromIso(isoNew) : ""; input.classList.remove("bad"); };
      return hidden;
    },
    setValue: function (el, iso) { if (!el) return; if (el.setIso) el.setIso(iso); else el.value = iso || ""; },
    attachAll: function (root) { (root || document).querySelectorAll('input[type="date"]').forEach(J.attach); },
    openPicker: function (iso, onPick) {
      var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
      var j = m ? d2j(g2d(+m[1], +m[2], +m[3])) : d2j(g2d(new Date().getFullYear(), new Date().getMonth() + 1, new Date().getDate()));
      var jy = j[0], jm = j[1], sel = j.slice();
      var ov = document.createElement("div"); ov.className = "jdate-overlay";
      function fa(n) { return String(n).replace(/\d/g, function (d) { return "۰۱۲۳۴۵۶۷۸۹"[d]; }); }
      function render() {
        var first = j2d(jy, jm, 1), dow = mod(first + 1, 7); // 0 = شنبه
        var len = J.monthLength(jy, jm), cells = "";
        for (var i = 0; i < dow; i++) cells += "<span></span>";
        for (var d = 1; d <= len; d++) {
          var is = (jy === sel[0] && jm === sel[1] && d === sel[2]) ? " sel" : "";
          cells += '<button type="button" class="jd' + is + '" data-d="' + d + '">' + fa(d) + "</button>";
        }
        ov.innerHTML = '<div class="jdate-pop">' +
          '<div class="jdate-head"><button type="button" data-nav="-1">‹</button>' +
          '<select class="jdate-m">' + MONTHS.map(function (n, i) { return '<option value="' + (i + 1) + '"' + (i + 1 === jm ? " selected" : "") + ">" + n + "</option>"; }).join("") + "</select>" +
          '<input class="jdate-y" type="number" value="' + jy + '" />' +
          '<button type="button" data-nav="1">›</button></div>' +
          '<div class="jdate-dows">' + ["ش", "ی", "د", "س", "چ", "پ", "ج"].map(function (x) { return "<span>" + x + "</span>"; }).join("") + "</div>" +
          '<div class="jdate-grid">' + cells + "</div>" +
          '<div class="jdate-foot"><button type="button" class="btn btn-sm" data-today="1">امروز</button><button type="button" class="btn btn-sm btn-ghost" data-close="1">بستن</button></div></div>';
        ov.querySelectorAll("[data-nav]").forEach(function (b) { b.onclick = function () { jm += +b.dataset.nav; if (jm < 1) { jm = 12; jy--; } if (jm > 12) { jm = 1; jy++; } render(); }; });
        ov.querySelector(".jdate-m").onchange = function (e) { jm = +e.target.value; render(); };
        ov.querySelector(".jdate-y").onchange = function (e) { jy = +e.target.value || jy; render(); };
        ov.querySelectorAll(".jd").forEach(function (b) { b.onclick = function () { var g = d2g(j2d(jy, jm, +b.dataset.d)); onPick(g[0] + "-" + pad(g[1]) + "-" + pad(g[2])); close(); }; });
        ov.querySelector("[data-today]").onclick = function () { onPick(J.todayIso()); close(); };
        ov.querySelector("[data-close]").onclick = close;
      }
      function close() { ov.remove(); }
      ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
      render(); document.body.appendChild(ov);
    }
  };
  global.Jalali = J;
})(window);
