"use strict";
/* Hullabaloo's face on Home: his pixel-art front view, built into a sprite sheet by tools/face/make_face.py
   (12 emotions x [closed ah oh ee oo fv blink], 72x78 each). Eyes, brows, cheeks and mustache change per
   emotion; the mouth follows the lip-sync visemes; it blinks every few seconds. Drawn with no smoothing. */
const Face = (() => {
  const img = new Image(); let meta = null, ready = false, blinkUntil = 0, nextBlink = performance.now() + 2500;
  img.onload = () => { ready = true; if (typeof drawFace === "function") drawFace(); };
  img.src = "assets/face/face_sheet.png";
  fetch("assets/face/face_sheet.json").then(r => r.json()).then(m => { meta = m; if (typeof drawFace === "function") drawFace(); }).catch(() => { });
  let last = null;
  function draw(c, st) {
    last = [c, st];
    const g = c.getContext("2d"); g.imageSmoothingEnabled = false;
    g.clearRect(0, 0, c.width, c.height);
    const glass = document.getElementById("stage").classList.contains("glass");
    const bgr = g.createRadialGradient(c.width / 2, c.height * .42, 30, c.width / 2, c.height / 2, c.width * .8);
    bgr.addColorStop(0, glass ? "rgba(120,200,230,.28)" : "#3d6a70"); bgr.addColorStop(1, glass ? "rgba(10,25,40,.25)" : "#1d3438");
    g.fillStyle = bgr; g.fillRect(0, 0, c.width, c.height);
    if (!ready || !meta) return;
    const W = meta.w, H = meta.h;
    let emo = st.emotion || "neutral";
    if (st.state === "sleeping" || st.booting) emo = "sleepy";
    const row = Math.max(0, meta.emotions.indexOf(emo));
    const now = performance.now();
    const blinking = now < blinkUntil && st.mouth === "closed";
    let col = blinking ? meta.columns.indexOf("blink") : meta.columns.indexOf(st.mouth || "closed");
    if (col < 0) col = 0;
    if (st.state === "sleeping" || st.booting) col = meta.columns.indexOf("blink");
    const k = Math.floor(Math.min(c.width / W, c.height / H));          /* whole-pixel scale only */
    const x = Math.round((c.width - W * k) / 2), y = Math.round((c.height - H * k) / 2) + k * 2;
    g.drawImage(img, col * W, row * H, W, H, x, y, W * k, H * k);
  }
  /* blink loop: every 2.5 to 6 s, 140 ms */
  setInterval(() => {
    const now = performance.now();
    if (now > nextBlink) { blinkUntil = now + 140; nextBlink = now + 2500 + Math.random() * 3500; if (last) draw(...last); setTimeout(() => { if (last) draw(...last); }, 150); }
  }, 100);
  return { draw };
})();
