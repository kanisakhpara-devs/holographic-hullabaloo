"""Rebake the laptop face sheet (72x78 per frame) into 200 x 72 LED cylinder frames.

    python rebake_led.py [theta_face_deg] [out_dir]

Geometry (docs/calculations.md): 200 columns per rev (1.8 deg each), 72 rows, LED rows 2.5 mm apart,
blades 50 mm from the axis. A viewer in front sees column at angle phi at X = 50 mm * sin(phi), so the
front view is wrapped onto the cylinder with x_art = centre + K * sin(phi) (what the viewer sees is the
original picture, edges squeezed naturally by the curve).
  - rows: front.png rows 4..75 map 1:1 onto the 72 LED rows (head is rows 5..74), no resampling
  - face: |phi| <= theta_face is the face sheet, face centre at column FACE_C (default 50, so the index
    pulse at column 0 is just before the face and column 100 (blade 2's swap) is on hair)
  - back: the rest is the back view from his turnaround, same wrapping around phi = 180 deg
Output: faces.bin (indexed, face columns only), face_data.h (palette and sizes), base_back.bin (200x72
hair cylinder), previews.
"""
import json, os, sys, math
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
COLS, ROWS, DEG = 200, 72, 1.8
FACE_C = 50
R_MM, PITCH_MM = 50.0, 2.5
ROW0 = 4                       # first front.png row used (rows 4..75)
GRID = 5.44                    # turnaround pixels per art pixel
BACK_X = (1867, 2075)          # back view in turnaround.png
CX_FRONT = 32.0                # centre of his head in the 72 px wide frame (head spans cols 1..62)
HALF_FRONT = 31.0


def load_back(turn_path):
    im = Image.open(turn_path).convert("RGB")
    w, h = im.size
    small = np.array(im.resize((round(w / GRID), round(h / GRID)), Image.BOX)).astype(np.int32)
    alpha = (small.sum(2) > 90)
    return small, alpha


def bake(sheet, meta, theta_face, back, back_alpha):
    W, H = meta["w"], meta["h"]
    ne, nc = len(meta["emotions"]), len(meta["columns"])
    th = math.radians(theta_face)
    K = HALF_FRONT / math.sin(th)
    bx0, bx1 = BACK_X[0] / GRID, BACK_X[1] / GRID
    bcx, bhalf = (bx0 + bx1) / 2, (bx1 - bx0) / 2
    bK = bhalf / math.sin(math.radians(105))
    brow0 = 150 / GRID
    # hair cylinder (RGB, alpha): used for all columns outside the face
    hair = np.zeros((COLS, ROWS, 4), np.int32)
    face_cols = []
    for c in range(COLS):
        phi = ((c - FACE_C) * DEG + 180) % 360 - 180          # -180..180, 0 = face centre
        if abs(phi) <= theta_face + 1e-6:
            face_cols.append((c, K * math.sin(math.radians(phi))))
        else:
            d = math.radians(phi - math.copysign(180, phi))   # angle from the back
            u = bcx + bK * math.sin(d)
            for r in range(ROWS):
                v = brow0 + ROW0 + r
                x, y = int(math.floor(u)), int(math.floor(v))
                if 0 <= y < back.shape[0] and 0 <= x < back.shape[1] and back_alpha[y, x]:
                    hair[c, r, :3] = back[y, x]; hair[c, r, 3] = 255
    frames = {}
    for e in range(ne):
        for m in range(nc):
            f = sheet[e * H:(e + 1) * H, m * W:(m + 1) * W]
            img = hair.copy()
            for c, dx in face_cols:
                xi = int(math.floor(CX_FRONT + dx))
                xi = min(W - 1, max(0, xi))
                img[c, :, :] = f[ROW0:ROW0 + ROWS, xi, :]
            frames[(e, m)] = img
    return frames, hair, [c for c, _ in face_cols]


def preview(img):
    """What a viewer in front sees: X = R sin(phi) across 100 mm, Y = 2.5 mm per row, 4 px per mm."""
    S = 4
    out = np.zeros((int(ROWS * PITCH_MM * S), int(2 * R_MM * S), 3), np.uint8)
    for px in range(out.shape[1]):
        X = (px + 0.5) / S - R_MM
        phi = math.degrees(math.asin(max(-1, min(1, X / R_MM))))
        c = int(round(FACE_C + phi / DEG)) % COLS
        for r in range(ROWS):
            p = img[c, r]
            if p[3] > 0:
                y0, y1 = int(r * PITCH_MM * S), int((r + 1) * PITCH_MM * S)
                out[y0:y1, px] = p[:3]
    return Image.fromarray(out)


def main():
    theta = float(sys.argv[1]) if len(sys.argv) > 1 else 75.0
    out = sys.argv[2] if len(sys.argv) > 2 else HERE
    meta = json.load(open(os.path.join(HERE, "..", "..", "ui", "assets", "face", "face_sheet.json")))
    sheet = np.array(Image.open(os.path.join(HERE, "..", "..", "ui", "assets", "face", "face_sheet.png")).convert("RGBA")).astype(np.int32)
    back, ba = load_back(os.path.join(HERE, "turnaround.png"))
    frames, hair, fcols = bake(sheet, meta, theta, back, ba)
    os.makedirs(out, exist_ok=True)
    # palette: index 0 = off; his art has ~2600 near-identical colours (from the image generator), so
    # merge them into 255 with median cut, weighted by how often each colour is used
    allpx = np.concatenate([i.reshape(-1, 4) for i in list(frames.values()) + [hair]])
    allpx = allpx[allpx[:, 3] > 0][:, :3]
    uniq, cnt = np.unique(allpx, axis=0, return_counts=True)
    print("unique colours", len(uniq))
    strip = np.repeat(uniq[:, None, :], 1, axis=1).astype(np.uint8)          # N x 1 x 3
    big = np.concatenate([np.repeat(strip[i:i + 1], max(1, int(min(cnt[i], 400))), axis=0) for i in range(len(uniq))])
    q = Image.fromarray(big.reshape(-1, 1, 3)).quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    qp = np.array(q.getpalette()[:255 * 3], np.uint8).reshape(-1, 3)
    pal = [(0, 0, 0)] + [tuple(int(v) for v in p) for p in qp]
    palarr = np.array(pal, np.int32)
    cols = {}
    for u in uniq:
        d = ((palarr[1:] - u) ** 2).sum(1)
        cols[tuple(int(v) for v in u)] = int(d.argmin()) + 1
    cols_off = 0
    def idx(img):
        o = np.zeros(img.shape[:2], np.uint8)
        for c in range(img.shape[0]):
            for r in range(img.shape[1]):
                p = img[c, r]
                o[c, r] = cols[(int(p[0]), int(p[1]), int(p[2]))] if p[3] > 0 else 0
        return o
    f0, f1 = fcols[0], fcols[-1]
    with open(os.path.join(out, "faces.bin"), "wb") as fb:
        for e in range(len(meta["emotions"])):
            for m in range(len(meta["columns"])):
                fb.write(idx(frames[(e, m)][f0:f1 + 1]).tobytes())      # [col][row]
    open(os.path.join(out, "base_back.bin"), "wb").write(idx(hair).tobytes())
    with open(os.path.join(out, "face_data.h"), "w") as h:
        h.write("// Generated by software/tools/face/rebake_led.py. Do not edit by hand.\n#pragma once\n#include <stdint.h>\n")
        h.write(f"#define FACE_THETA_DEG {theta:g}\n#define FACE_FIRST_COL {f0}\n#define FACE_NCOLS {f1 - f0 + 1}\n")
        h.write(f"#define FACE_ROWS {ROWS}\n#define FACE_EMOTIONS {len(meta['emotions'])}\n#define FACE_MOUTHS {len(meta['columns'])}\n")
        h.write("// frame index = emotion * FACE_MOUTHS + mouth (closed ah oh ee oo fv blink); bytes are [col][row], row 0 = top, index into face_palette\n")
        h.write("// faces.bin: FACE_EMOTIONS*FACE_MOUTHS frames of FACE_NCOLS*FACE_ROWS bytes. base_back.bin: 200*72 hair cylinder.\n")
        h.write("static const uint8_t face_palette[%d][3] = {\n" % len(pal) + ",\n".join("  {%d,%d,%d}" % p for p in pal) + "\n};\n")
    # previews: unwrapped and viewer's view for a few emotions
    tiles = []
    for e in (0, 1, 2, 3, 10):
        pv = preview(frames[(e, 0)]); tiles.append(pv)
    sheet_img = Image.new("RGB", (sum(t.width + 8 for t in tiles), tiles[0].height), (30, 30, 30))
    x = 0
    for t in tiles:
        sheet_img.paste(t, (x, 0)); x += t.width + 8
    sheet_img.save(os.path.join(out, f"preview_viewer_{int(theta)}.png"))
    unw = np.zeros((ROWS * 3, COLS * 3 + 0, 3), np.uint8)
    img = frames[(2, 0)]
    for c in range(COLS):
        for r in range(ROWS):
            if img[c, r, 3] > 0:
                unw[r * 3:(r + 1) * 3, c * 3:(c + 1) * 3] = img[c, r, :3]
    Image.fromarray(unw).save(os.path.join(out, f"preview_unwrapped_{int(theta)}.png"))
    print("face cols", f0, "to", f1, "->", f1 - f0 + 1, "columns;", "faces.bin", (f1 - f0 + 1) * ROWS * 84, "bytes")


if __name__ == "__main__":
    main()
