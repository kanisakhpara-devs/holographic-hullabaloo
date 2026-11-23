"""Build Hullabaloo's face sprite sheet from his pixel-art front view.

    python make_face.py [front.png] [out_dir]

front.png is the 72x78 front view sampled from his turnaround (Smug_Moustache_Pixel_Art_Turnaround.png).
SMUG is his drawing, untouched. Every other emotion changes only:
  - eyes + lids (rows 35-41): repainted with his colours (lid black, eye white, pupil, skin),
  - brows (rows 24-34) and mustache (rows 46-58): each column shifted up or down a pixel or two, so
    they keep his drawn shapes but tilt (raised, frowning, smiling),
  - cheeks: blush or flush mixed into his skin,
  - mouth (rows 57-60, under the mustache): 6 mouth shapes for lip sync.
Output: face_sheet.png (12 emotions x 7 columns: closed ah oh ee oo fv blink, each 72x78) + face_sheet.json.
Edit front.png in any pixel editor (keep it 72x78) and run this again to rebuild every frame.
"""
import json, os, sys
import numpy as np
from PIL import Image

EMOS = ["neutral", "happy", "smug", "angry", "surprised", "sad", "confused", "sleepy", "bored", "suspicious",
        "laughing", "eyeroll"]
MOUTHS = ["closed", "ah", "oh", "ee", "oo", "fv"]
COLS = MOUTHS + ["blink"]
W, H = 72, 78

# his palette (sampled from the art)
LID = (5, 3, 2)
WHITE = (248, 243, 240)
WHITE2 = (227, 220, 219)
PUPIL = (2, 2, 2)
SKIN = (236, 166, 116)
SKIN_SH = (210, 120, 80)
UNDER = (164, 79, 53)          # the darker line under the eyes
MOUTH = (60, 18, 10)
TONGUE = (178, 64, 58)
TEETH = (245, 238, 228)
BLUSH = (232, 104, 96)

# eye boxes: (x0, x1) of each eye's opening, lids at rows 37-38, eye rows 39-40 in his drawing
EYES = {"L": (16, 27), "R": (34, 47)}
PUPIL_X = {"L": 22, "R": 41}       # where his pupils sit (looking slightly to his left)


def load(path):
    im = Image.open(path).convert("RGBA")
    a = np.array(im).astype(np.int32)
    # Background = near-black pixels CONNECTED TO THE EDGE of the picture. Black inside the head (outlines,
    # pupils, mustache shadow) stays black. (v1 made every near-black pixel transparent: the face looked split up.)
    from collections import deque
    dark = a[:, :, :3].sum(2) < 40
    bg = np.zeros(dark.shape, bool)
    q = deque([(y, x) for y in range(H) for x in (0, W - 1) if dark[y, x]] +
              [(y, x) for x in range(W) for y in (0, H - 1) if dark[y, x]])
    for y, x in q:
        bg[y, x] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and dark[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                q.append((ny, nx))
    a[bg, 3] = 0
    # keep only the head: the crop also caught a sliver of the next turnaround view at the edge
    seen = np.zeros(bg.shape, bool)
    q = deque([(39, 36)]); seen[39, 36] = True
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and not seen[ny, nx] and a[ny, nx, 3] > 0:
                seen[ny, nx] = True
                q.append((ny, nx))
    a[~seen, 3] = 0
    return a


def put(a, x, y, c, alpha=1.0):
    if 0 <= x < W and 0 <= y < H:
        if alpha >= 1:
            a[y, x, :3] = c
        else:
            a[y, x, :3] = (np.array(c) * alpha + a[y, x, :3] * (1 - alpha)).astype(np.int32)


def shift_cols(a, x0, x1, y0, y1, dy_of_x):
    """Move rows y0..y1 of each column x by dy (negative = up), pulling from the original."""
    src = a.copy()
    for x in range(x0, x1 + 1):
        dy = int(round(dy_of_x(x)))
        if not dy:
            continue
        for y in range(y0, y1 + 1):
            sy = min(y1, max(y0, y - dy))
            a[y, x] = src[sy, x]


def skin_fill(a, src, side, rows):
    """Paint the eye opening with skin, taken column by column from just above the lids (row 36)."""
    x0, x1 = EYES[side]
    for x in range(x0, x1 + 1):
        for y in rows:
            a[y, x, :3] = src[36, x, :3]


def eye(a, src, side, emo, blink=False):
    """Repaint one eye for this emotion, in his style: thick black lid, 1-4 rows of white, black pupil."""
    x0, x1 = EYES[side]
    inner = x1 if side == "L" else x0              # end of the eye nearest the nose
    skin_fill(a, src, side, range(35, 42))
    for x in range(x0, x1 + 1):                    # keep his under-eye line
        a[41, x, :3] = src[41, x, :3]

    def lid(row_of_x, thick=2):
        for x in range(x0, x1 + 1):
            r = row_of_x(x)
            for t in range(thick):
                put(a, x, r + t, LID)

    def opening(top_of_x, bottom, px, prow=None, wide=2):
        for x in range(x0 + 1, x1):
            for y in range(top_of_x(x), bottom + 1):
                put(a, x, y, WHITE if abs(x - px) > 3 else WHITE2)
        for x in range(px - wide // 2, px - wide // 2 + wide):
            for y in (prow if prow is not None else range(top_of_x(px), bottom + 1)):
                put(a, x, y, PUPIL)

    flat = lambda r: (lambda x: r)
    slope = lambda r_inner, r_outer: (lambda x: int(round(r_inner + (r_outer - r_inner) * (abs(x - inner) / (x1 - x0)))))
    px = PUPIL_X[side]
    mid = (x0 + x1) // 2

    if blink or emo == "sleepy":
        lid(flat(39), 1)                            # closed: one dark line, a lash at the outer end
        put(a, x0 if side == "L" else x1, 40, LID)
        return
    if emo in ("happy", "laughing"):               # smiling eyes: thick upside-down U, cheeks push up
        for x in range(x0 + 1, x1):
            d = abs(x - mid)
            r = 37 + (1 if d >= 3 else 0) + (1 if d >= 5 else 0)
            put(a, x, r, LID); put(a, x, r + 1, LID)
        for x in range(x0 + 2, x1 - 1):
            put(a, x, 41, SKIN_SH)
        return
    if emo == "surprised":                          # lids up, tall white, small centred pupil
        lid(flat(35), 1)
        for x in range(x0 + 1, x1):
            for y in range(36, 41):
                put(a, x, y, WHITE)
        put(a, x0 + 1, 36, src[36, x0 + 1, :3]); put(a, x1 - 1, 36, src[36, x1 - 1, :3])
        for x in (mid - 1, mid):
            for y in (37, 38, 39):
                put(a, x, y, PUPIL)
        return
    if emo == "angry":                              # lids slanting down toward the nose
        lid(slope(39, 37))
        opening(lambda x: slope(39, 37)(x) + 2, 40, mid)
        return
    if emo == "sad":                                # lids slanting down to the outside
        lid(slope(37, 38))
        opening(lambda x: slope(37, 38)(x) + 2, 40, mid)
        for x in range(x0 + 2, x1 - 1):            # watery lower lid
            put(a, x, 41, (120, 150, 190), 0.35)
        return
    if emo == "suspicious":                         # narrow slit, pupils to the side
        lid(flat(38), 2)
        opening(flat(40), 40, px - 2 if side == "L" else px - 2)
        return
    if emo == "bored":                              # half closed, pupils low and centred
        lid(flat(38), 2)
        opening(flat(40), 40, mid)
        return
    if emo == "eyeroll":                            # pupils up under the lid, white below
        lid(flat(37), 1)
        opening(flat(38), 40, mid, prow=range(38, 39), wide=3)
        return
    if emo == "confused":                           # one eye wider than the other
        if side == "L":
            lid(flat(36), 1)
            opening(flat(37), 40, mid, prow=range(38, 40))
        else:
            lid(flat(38), 2)
            opening(flat(40), 40, mid)
        return
    # neutral: his lids, a bit more open, pupils centred
    lid(flat(37), 1)
    opening(flat(38), 40, mid, prow=range(38, 41))


BROW = {   # dy at the inner end and at the outer end of each brow (negative = up)
    "neutral": (-1, -1), "happy": (-1, -2), "angry": (2, -1), "surprised": (-3, -2), "sad": (-3, 0),
    "confused": None, "sleepy": (1, 1), "bored": (1, 0), "suspicious": (1, 1), "laughing": (-2, -2), "eyeroll": (-1, -1)}
STACHE = {  # dy of the mustache tips (negative = up), middle stays put
    "neutral": 0, "happy": -2, "smug": 0, "angry": 1, "surprised": 0, "sad": 2, "confused": 1, "sleepy": 1,
    "bored": 1, "suspicious": 0, "laughing": -3, "eyeroll": 0}
CHEEK = {"happy": (BLUSH, 0.35), "laughing": (BLUSH, 0.5), "angry": ((220, 60, 40), 0.35),
         "surprised": (BLUSH, 0.2), "sad": ((150, 160, 190), 0.12)}
CHEEKS = [(16, 23, 42, 46), (41, 48, 42, 46)]      # x0, x1, y0, y1 on each side


def brows(a, emo):
    b = BROW.get(emo)
    if emo == "confused":                           # left up, right down
        shift_cols(a, 14, 29, 24, 34, lambda x: -2)
        shift_cols(a, 30, 48, 24, 34, lambda x: 1)
        return
    if not b:
        return
    din, dout = b
    shift_cols(a, 14, 30, 24, 34, lambda x: din + (dout - din) * (30 - x) / 16)   # left brow: inner end at x 30
    shift_cols(a, 31, 48, 24, 34, lambda x: din + (dout - din) * (x - 31) / 17)   # right brow: inner end at x 31


def mustache(a, emo):
    d = STACHE.get(emo, 0)
    if d:
        shift_cols(a, 12, 54, 46, 59, lambda x: d * min(1.0, max(0.0, (abs(x - 32) - 4) / 14.0)))


def cheeks(a, emo):
    c = CHEEK.get(emo)
    if not c:
        return
    col, al = c
    for x0, x1, y0, y1 in CHEEKS:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                d = ((x - cx) / ((x1 - x0) / 2 + .5)) ** 2 + ((y - cy) / ((y1 - y0) / 2 + .5)) ** 2
                if d <= 1 and a[y, x, 3] > 0:
                    put(a, x, y, col, al * (1.0 if d < .5 else .6))


def mouth(a, m, emo):
    """Mouth shapes under the mustache, centred at x 31-32, rows 57-60."""
    cx = 32
    def box(x0, x1, y0, y1, c):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                put(a, x, y, c)
    if m == "closed":
        if emo in ("happy", "laughing", "smug"):
            return                                  # the mustache hides a closed smile
        if emo in ("sad", "angry"):
            box(cx - 3, cx + 2, 58, 58, MOUTH)      # flat pressed line
            put(a, cx - 4, 59, MOUTH); put(a, cx + 3, 59, MOUTH)
        return
    if m == "ah":
        box(cx - 3, cx + 2, 57, 60, MOUTH); box(cx - 2, cx + 1, 60, 60, TONGUE)
    elif m == "oh":
        box(cx - 2, cx + 1, 57, 60, MOUTH); box(cx - 1, cx, 59, 60, TONGUE)
    elif m == "ee":
        box(cx - 4, cx + 3, 57, 59, MOUTH); box(cx - 3, cx + 2, 57, 57, TEETH)
    elif m == "oo":
        box(cx - 1, cx, 57, 59, MOUTH)
    elif m == "fv":
        box(cx - 3, cx + 2, 57, 58, MOUTH); box(cx - 3, cx + 2, 57, 57, TEETH)
    if emo == "laughing" and m != "fv":
        box(cx - 4, cx + 3, 57, 57, TEETH)


def frame(base, emo, m, blink=False):
    a = base.copy()
    if emo != "smug" or blink:
        brows(a, emo)
        src = a.copy()
        for side in ("L", "R"):
            eye(a, src, side, emo, blink=blink)
    mustache(a, emo)
    cheeks(a, emo)
    mouth(a, "closed" if blink else m, emo)
    return a


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "front.png")
    out = sys.argv[2] if len(sys.argv) > 2 else here
    base = load(src)
    assert base.shape[:2] == (H, W), "front.png must be 72x78"
    sheet = np.zeros((H * len(EMOS), W * len(COLS), 4), np.int32)
    for r, e in enumerate(EMOS):
        for c, m in enumerate(COLS):
            f = frame(base, e, "closed" if m == "blink" else m, blink=(m == "blink"))
            sheet[r * H:(r + 1) * H, c * W:(c + 1) * W] = f
    Image.fromarray(np.clip(sheet, 0, 255).astype(np.uint8), "RGBA").save(os.path.join(out, "face_sheet.png"))
    with open(os.path.join(out, "face_sheet.json"), "w") as f:
        json.dump({"w": W, "h": H, "emotions": EMOS, "columns": COLS}, f, indent=1)
    print("wrote face_sheet.png", sheet.shape[1], "x", sheet.shape[0])


if __name__ == "__main__":
    main()
