"use strict";
/* Boot. The demo loop lives in js/demo.js and is loaded ONLY with ?demo=1: the shipped UI never shows fake data. */
(function boot() {
  const h0 = location.hash.slice(1); if (["transcript", "settings"].includes(h0)) S.page = h0;
  const start = () => { fit(); render(); connect(); };
  if (DEMO) { const sc = document.createElement("script"); sc.src = "js/demo.js"; sc.onload = start; document.body.appendChild(sc); }
  else start();
})();
