"use strict";
/* Liquid glass effects (glass theme only, off when Animations is off):
   1. Dock magnify: buttons near the cursor swell a little, more the closer it is (like his Atrium taskbar).
   2. Liquid: a droplet under the cursor refracts (bends) whatever is beneath it, stretches as you drag it and
      leaves a wake of smaller droplets; clicks and fast flicks send out a ring wave that distorts the page. */
(() => {
  const on = () => { const st = document.getElementById("stage"); return st && st.classList.contains("glass") && !st.classList.contains("still"); };

  /* ---------- 1. dock magnify ---------- */
  const MAG_SEL = ".pill, .tab, .mic.seg button, .cat";
  const RADIUS = 150, MAX = 0.12;                 /* px of influence, +12% at the cursor */
  let magged = [];
  function magnify(x, y) {
    const now = [];
    document.querySelectorAll(MAG_SEL).forEach(el => {
      const r = el.getBoundingClientRect();
      if (!r.width) return;
      const dx = Math.max(r.left - x, 0, x - r.right), dy = Math.max(r.top - y, 0, y - r.bottom);
      const d = Math.hypot(dx, dy);
      if (d < RADIUS) {
        const t = 1 - d / RADIUS;
        const grow = Math.min(MAX, 14 / r.width);         /* at most ~14 px wider, so wide buttons don't burst their column */
        el.style.setProperty("--mag", (1 + grow * t * t).toFixed(3));
        now.push(el);
      }
    });
    magged.forEach(el => { if (!now.includes(el)) el.style.setProperty("--mag", 1); });
    magged = now;
  }
  function unmagnify() { magged.forEach(el => el.style.setProperty("--mag", 1)); magged = []; }

  /* ---------- 2. real liquid: refraction, not drawn circles ----------
     Each droplet/ring is a small element that captures what's behind it (backdrop-filter) and bends it with an
     SVG displacement map (filter), so text and buttons under the cursor actually warp like through water. */
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", "0"); svg.setAttribute("height", "0");
  svg.style.cssText = "position:absolute;width:0;height:0";
  document.body.appendChild(svg);
  function mapURL(kind) {            /* displacement map: R = x shift, G = y shift, 128 = none */
    const n = 128, c = document.createElement("canvas"); c.width = c.height = n;
    const x = c.getContext("2d"), im = x.createImageData(n, n);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const dx = (i + .5) / n * 2 - 1, dy = (j + .5) / n * 2 - 1, r = Math.hypot(dx, dy);
      let f = 0;
      if (kind === "drop" && r < 1) f = -Math.sin(Math.PI * r) * (1 - r * .3);   /* magnifying lens, strongest mid-radius */
      if (kind === "ring" && r > .55 && r < 1) f = Math.sin((r - .55) / .45 * Math.PI);  /* a band that pushes outward */
      const k = (j * n + i) * 4, nx = r ? dx / r : 0, ny = r ? dy / r : 0;
      im.data[k] = 128 + 127 * nx * f; im.data[k + 1] = 128 + 127 * ny * f; im.data[k + 2] = 128; im.data[k + 3] = 255;
    }
    x.putImageData(im, 0, 0); return c.toDataURL();
  }
  const MAPS = { drop: mapURL("drop"), ring: mapURL("ring") };
  let fid = 0;
  function makeFilter(kind, scale) {
    const id = "lq" + (++fid), f = document.createElementNS(NS, "filter");
    f.setAttribute("id", id); f.setAttribute("x", "0"); f.setAttribute("y", "0"); f.setAttribute("width", "1"); f.setAttribute("height", "1");
    f.setAttribute("primitiveUnits", "objectBoundingBox"); f.setAttribute("color-interpolation-filters", "sRGB");
    const im = document.createElementNS(NS, "feImage");
    im.setAttribute("href", MAPS[kind]); im.setAttribute("x", "0"); im.setAttribute("y", "0"); im.setAttribute("width", "1"); im.setAttribute("height", "1");
    im.setAttribute("preserveAspectRatio", "none"); im.setAttribute("result", "m");
    const dm = document.createElementNS(NS, "feDisplacementMap");
    dm.setAttribute("in", "SourceGraphic"); dm.setAttribute("in2", "m"); dm.setAttribute("scale", scale);
    dm.setAttribute("xChannelSelector", "R"); dm.setAttribute("yChannelSelector", "G");
    f.appendChild(im); f.appendChild(dm); svg.appendChild(f);
    return { id, dm, el: f };
  }
  function blob(size, scale) {
    const d = document.createElement("div"), fl = makeFilter("drop", scale);
    d.className = "lqdrop"; d.style.width = d.style.height = size + "px";
    d.style.filter = `url(#${fl.id})`;
    document.body.appendChild(d);
    return { el: d, size, x: -999, y: -999, vx: 0, vy: 0 };
  }
  /* the main droplet and a wake of smaller ones, each chasing the one in front */
  const drops = [blob(120, .16), blob(78, .14), blob(52, .12), blob(34, .1)];
  const STIFF = [.22, .16, .13, .11], DAMP = [.62, .66, .7, .72];
  let px = -999, py = -999, inside = false, lastMove = 0, raf = 0, lastRing = 0, prevX = 0, prevY = 0;
  const rings = [];
  function ring(x, y, power) {
    const fl = makeFilter("ring", .18 * power), el = document.createElement("div");
    el.className = "lqring"; el.style.filter = `url(#${fl.id})`;
    document.body.appendChild(el);
    rings.push({ el, fl, x, y, t: performance.now(), dur: 900 + 300 * power, max: 180 + 120 * power, power });
    if (rings.length > 6) { const r = rings.shift(); r.el.remove(); r.fl.el.remove(); }
  }
  function frame() {
    raf = 0;
    const now = performance.now(), idle = now - lastMove, show = inside && on() && idle < 900;
    let tx = px, ty = py, busy = false;
    drops.forEach((d, i) => {
      if (d.x < -900) { d.x = tx; d.y = ty; }
      d.vx = (d.vx + (tx - d.x) * STIFF[i]) * DAMP[i]; d.vy = (d.vy + (ty - d.y) * STIFF[i]) * DAMP[i];
      d.x += d.vx; d.y += d.vy;
      const sp = Math.hypot(d.vx, d.vy), ang = Math.atan2(d.vy, d.vx);
      const st = Math.min(.55, sp / 40);                                /* stretch along the motion, like a drop being dragged */
      d.el.style.transform = `translate(${d.x - d.size / 2}px,${d.y - d.size / 2}px) rotate(${ang}rad) scale(${1 + st},${1 - st * .5})`;
      d.el.style.opacity = show ? (i ? Math.min(1, sp / 6) * (1 - i * .18) : 1) : 0;
      if (sp > .05 || Math.hypot(tx - d.x, ty - d.y) > .5) busy = true;
      tx = d.x; ty = d.y;
    });
    for (let i = rings.length - 1; i >= 0; i--) {
      const r = rings[i], p = (now - r.t) / r.dur;
      if (p >= 1) { r.el.remove(); r.fl.el.remove(); rings.splice(i, 1); continue; }
      const e = 1 - Math.pow(1 - p, 3), size = 30 + r.max * e;
      r.el.style.width = r.el.style.height = size + "px";
      r.el.style.transform = `translate(${r.x - size / 2}px,${r.y - size / 2}px)`;
      r.fl.dm.setAttribute("scale", (.18 * r.power * (1 - p)).toFixed(3));
      r.el.style.opacity = 1 - p * p;
      busy = true;
    }
    if (busy || show) raf = requestAnimationFrame(frame);
  }
  function kick() { if (!raf) raf = requestAnimationFrame(frame); }

  document.addEventListener("pointermove", e => {
    if (!on()) { if (magged.length) unmagnify(); inside = false; kick(); return; }
    px = e.clientX; py = e.clientY; lastMove = performance.now();
    inside = !!(e.target.closest && e.target.closest("#stage"));
    magnify(px, py);
    const sp = Math.hypot(px - prevX, py - prevY); prevX = px; prevY = py;
    if (inside && sp > 38 && lastMove - lastRing > 160) { ring(px, py, .6); lastRing = lastMove; }   /* fast flick: a small wave */
    kick();
  }, { passive: true });
  document.addEventListener("pointerleave", () => { inside = false; unmagnify(); kick(); });
  document.addEventListener("pointerdown", e => { if (on()) { ring(e.clientX, e.clientY, 1); kick(); } }, { passive: true });
})();
