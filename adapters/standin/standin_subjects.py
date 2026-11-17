"""The subjects the stand-in painter can draw. The brief's words choose one family; the seed and the prompt vary its
proportions and palette. Everything is drawn from shapes in standin_paint.py: no model, no pictures, no downloads.
"""
import math
import re

import standin_paint as p
from standin_paint import circle, ellipse, flat, mix, noise, polygon, ring, rounded_box, scale, segment, smooth_union

# The keyword table: a family, and the words in a brief that point to it. The family with the most words in the brief
# wins; a tie goes to the one listed first. Anything else is drawn as a cut gem.
FAMILIES = (
    ("instrument", ("lute", "fiddle", "violin", "viola", "cello", "guitar", "mandolin", "banjo", "lyre", "harp",
                    "bouzouki", "ukulele", "zither", "instrument", "string", "strings", "music", "musical")),
    ("lantern", ("lantern", "lamp", "lit", "torch", "beacon", "candle", "lighthouse", "glass")),
    ("book", ("book", "notebook", "journal", "diary", "ledger", "tome", "grimoire", "manual", "atlas", "log",
              "logbook", "almanac", "pages", "bound")),
    ("figure", ("character", "person", "figure", "man", "woman", "girl", "boy", "keeper", "sailor", "captain",
                "fisher", "fisherman", "child", "villager", "hero", "knight", "merchant", "pose")),
    ("vessel", ("vase", "jar", "pot", "bottle", "jug", "urn", "flask", "cup", "pitcher", "amphora")),
)
DEFAULT_FAMILY = "gem"
HEAD = 1  # the figure's head, in the same units as everything else


def family_for(prompt):
    """The family the prompt's words point to ('gem' when none do)."""
    words = re.findall(r"[a-z]+", prompt.lower())
    words += [w.rstrip("s") for w in words if len(w) > 3 and w.endswith("s")]
    best, best_hits = DEFAULT_FAMILY, 0
    for name, keywords in FAMILIES:
        hits = sum(1 for w in words if w in keywords)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def draw(canvas, family, rng):
    """Paint FAMILY on CANVAS with proportions and colours drawn from RNG (a deterministic random source)."""
    PAINTERS[family](canvas, rng)


def vary(rng, low, high):
    return low + (high - low) * rng.random()


# ---- wood, metal and cloth ---------------------------------------------------------------------------------------

def wood(light, dark, stretch=(0.06, 0.012), salt=1):
    """A grained wood: stripes along y, a little ring wobble."""
    def albedo(x, y, u):
        g = noise(x * stretch[0], y * stretch[1], salt) * 0.6 + 0.4 * math.sin(x * 0.11 + noise(x * 0.02, y * 0.01, salt + 1) * 5) * 0.5 + 0.2
        return mix(dark, light, p.clamp(g))
    return albedo


def metal(light, dark, salt=4):
    def albedo(x, y, u):
        return mix(dark, light, p.clamp(0.55 + (noise(x * 0.05, y * 0.05, salt) - 0.5) * 0.35 + 0.3 * u))
    return albedo


# ---- the stringed instrument -------------------------------------------------------------------------------------

WOODS = (((238, 168, 78), (160, 84, 32)), ((206, 104, 62), (120, 50, 32)), ((240, 196, 118), (176, 122, 62)),
         ((176, 118, 82), (98, 58, 40)))
PEGS = ((236, 214, 160), (96, 54, 40), (40, 34, 36), (176, 68, 52))


def stringed_instrument(cv, rng):
    light, dark = WOODS[int(rng.random() * len(WOODS))]
    peg_colour = PEGS[int(rng.random() * len(PEGS))]
    lute = rng.random() < 0.5  # a rounded lute (one big bowl, a rosette) or a waisted fiddle (f-holes)
    courses = 3 if lute else 2  # pegs on each side of the pegbox
    wide = vary(rng, 0.92, 1.1)
    waist = vary(rng, 0.2, 0.55) if not lute else vary(rng, 0.0, 0.12)
    tilt = math.radians(vary(rng, 7, 13) * (1 if rng.random() < 0.5 else -1))
    body_hw = 100 * wide
    cv.frame_about(tilt, (0, -70))

    def stained(top=True):
        return wood(light, dark, salt=2 if top else 3)

    lower = ellipse(0, 52, body_hw, 100)
    upper = ellipse(0, -52, body_hw * (0.86 - waist * 0.3), 72)
    body = smooth_union(lower, upper, 40 + 40 * (1 - waist))
    if not lute:  # the C-bouts: a bite out of each side at the waist
        cut = 46 + 30 * waist
        for side in (-1, 1):
            c_bout = circle(side * (body_hw * 0.6 + cut), 2, cut)
            body = p.smooth_subtract(body, c_bout, 26)
    neck_hw = 15
    # neck behind the body: a rounded stick, darker wood
    cv.layer(rounded_box(0, -140, neck_hw, 100, 8), (-20, -250, 20, -30), wood(dark, scale(dark, 0.6), salt=5), bulge=15,
             spec=0.18)
    # pegbox and the scroll above it
    cv.layer(rounded_box(0, -238, 21, 36, 10), (-26, -278, 26, -196), wood(dark, scale(dark, 0.62), salt=6), bulge=21,
             spec=0.2, shadow=0.6)
    cv.layer(circle(2, -280, 25), (-30, -312, 32, -246), wood(light, dark, salt=7), bulge=25, spec=0.3, shadow=0.5)
    cv.layer(ring(2, -280, 12, 2.5), (-16, -296, 20, -264), flat(scale(dark, 0.45)), bulge=3, spec=0)
    cv.layer(circle(2, -280, 4.5), (-8, -286, 12, -272), flat(scale(dark, 0.45)), bulge=4, spec=0)
    # pegs: rods through the box with a round knob at each end
    for side in (-1, 1):
        for i in range(courses):
            y = -258 + i * 24 + (6 if side > 0 else 0)
            tip = side * 40
            cv.layer(segment(side * 14, y, tip, y, 4.5), (min(0, tip) - 6, y - 7, max(0, tip) + 6, y + 7),
                     flat(peg_colour), bulge=5, spec=0.35, shadow=0.7)
            cv.layer(ellipse(side * 45, y, 8, 11), (side * 45 - 10, y - 13, side * 45 + 10, y + 13),
                     flat(peg_colour), bulge=9, spec=0.45, shadow=0.7)
    # the body: ribs as a darker band round the edge, a top plate inside, a pale line of inlay between
    def top_plate(x, y, u):
        base = wood(light, dark, salt=2)(x, y, u)
        if u < 0.055:
            return scale(dark, 0.78)
        inlay = p.smoothstep(0.055, 0.06, u) * (1 - p.smoothstep(0.075, 0.08, u))
        return mix(base, (240, 224, 176), inlay * 0.9)
    cv.layer(body, (-body_hw - 40, -140, body_hw + 40, 160), top_plate, bulge=body_hw * 0.95, spec=0.32, gloss=34,
             rim=0.22, shadow=1.0)
    # the sound hole: a rosette ring round a dark hole (lute), or a pair of f-holes (fiddle)
    hole = (34, 22, 20)
    if lute:
        cv.layer(ring(0, 4, 36, 4), (-42, -38, 42, 46), flat(scale(dark, 0.5)), bulge=4, spec=0.1)
        cv.layer(ring(0, 4, 26, 1.8), (-30, -28, 30, 36), flat((236, 214, 160)), bulge=2, spec=0)
        cv.layer(circle(0, 4, 22), (-26, -24, 26, 32), flat(hole), bulge=-14, spec=0, rim=0.0)
    else:
        for side in (-1, 1):
            cv.layer(segment(side * 38, -16, side * 46, 46, 4.2, 3.4), (side * 38 - 10, -26, side * 38 + 18, 56),
                     flat(hole), bulge=-4, spec=0, rim=0.0)
            cv.layer(circle(side * 38, -18, 6.5), (side * 38 - 8, -26, side * 38 + 8, -10), flat(hole), bulge=-4,
                     spec=0, rim=0.0)
            cv.layer(circle(side * 46, 48, 6.5), (side * 46 - 8, 40, side * 46 + 8, 56), flat(hole), bulge=-4,
                     spec=0, rim=0.0)
    # tailpiece and bridge
    cv.layer(polygon([(-17, 76), (17, 76), (11, 148), (-11, 148)]), (-20, 72, 20, 152), flat(scale(dark, 0.4)),
             bulge=11, spec=0.35, shadow=0.9)
    cv.layer(circle(0, 148, 6), (-8, 140, 8, 156), flat(scale(dark, 0.4)), bulge=6, spec=0.3, shadow=0.5)
    cv.layer(rounded_box(0, 56, 34, 6, 3), (-38, 48, 38, 64), flat((226, 196, 144)), bulge=6, spec=0.4, shadow=0.9)
    # the fingerboard, over the neck and a little onto the body, with frets
    board = rounded_box(0, -112, 12, 112, 5)
    cv.layer(board, (-16, -230, 16, 4), flat((46, 34, 32)), bulge=12, spec=0.42, gloss=18, shadow=0.8)
    for i in range(1, 8):
        y = -210 + i * 26 + i * i * 0.6
        cv.layer(rounded_box(0, y, 12, 1.1, 1), (-14, y - 3, 14, y + 3), flat((200, 176, 120)), bulge=2, spec=0.5)
    cv.layer(rounded_box(0, -226, 12.5, 2.6, 1), (-14, -231, 14, -221), flat((240, 226, 190)), bulge=3, spec=0.3)
    # strings, from the nut down to the tailpiece
    count = courses * 2
    for i in range(count):
        f = (i - (count - 1) / 2) / max(1, count - 1)
        top, bottom = f * 20, f * 56
        cv.layer(segment(top, -224, bottom, 140, 0.9), (min(top, bottom) - 3, -228, max(top, bottom) + 3, 146),
                 flat((226, 218, 190)), bulge=1.5, spec=0.5, gloss=12, rim=0)


# ---- the lantern -----------------------------------------------------------------------------------------------

METALS = (((226, 176, 78), (122, 78, 30)), ((206, 128, 84), (104, 56, 36)), ((142, 150, 164), (62, 68, 82)),
          ((222, 190, 110), (118, 86, 40)))


def lantern(cv, rng):
    light, dark = METALS[int(rng.random() * len(METALS))]
    metal_albedo = metal(light, dark)
    width = vary(rng, 70, 86)
    top_y, bottom_y = -92, 112
    # the carry ring on top
    cv.layer(ring(0, -150, 46, 6), (-54, -202, 54, -100), metal_albedo, bulge=6, spec=0.5, shadow=0.7)
    # the glass chimney: a glowing barrel, light in the middle, amber at the rim, a flame inside
    def glass(x, y, u):
        centre = math.hypot(x / (width * 0.9), (y - 10) / 80)
        warm = p.clamp(1.15 - centre)
        return mix((214, 124, 38), (255, 240, 170), warm ** 1.4)
    barrel = rounded_box(0, 10, width * 0.86, 92, 34)
    cv.layer(barrel, (-width - 8, -90, width + 8, 110), glass, bulge=width * 0.9, spec=0.0, rim=0.0, glow=1, shadow=0.6)
    cv.layer(ellipse(0, 22, 15, 38), (-20, -20, 20, 66), flat((255, 246, 200)), bulge=15, spec=0, glow=1)
    cv.layer(ellipse(-width * 0.42, -4, 6, 52), (-width * 0.5, -60, -width * 0.34, 56), flat((255, 252, 230)),
             bulge=6, spec=0, glow=1)
    # brass bars over the glass
    for fx in (-0.68, 0, 0.68):
        x = fx * width
        cv.layer(segment(x * 0.9, -88, x, 108, 4.2), (x - 8, -92, x + 8, 112), metal_albedo, bulge=4.2, spec=0.5)
    # the cap and the base
    cv.layer(polygon([(-width * 0.6, -92), (width * 0.6, -92), (width * 1.0, -62), (-width * 1.0, -62)]),
             (-width - 4, -98, width + 4, -58), metal_albedo, bulge=18, spec=0.55, shadow=0.8)
    cv.layer(ellipse(0, -112, width * 0.5, 22), (-width * 0.55, -138, width * 0.55, -88), metal_albedo, bulge=22,
             spec=0.6, shadow=0.8)
    cv.layer(circle(0, -138, 8), (-10, -148, 10, -128), metal_albedo, bulge=8, spec=0.6)
    cv.layer(rounded_box(0, 110, width * 1.04, 12, 8), (-width * 1.1, 96, width * 1.1, 126), metal_albedo, bulge=14,
             spec=0.5, shadow=0.8)
    cv.layer(rounded_box(0, 134, width * 0.8, 12, 9), (-width * 0.9, 120, width * 0.9, 148), metal_albedo, bulge=12,
             spec=0.5, shadow=0.8)


# ---- the book --------------------------------------------------------------------------------------------------

COVERS = ((150, 62, 54), (50, 104, 134), (62, 128, 88), (170, 118, 52), (104, 70, 138))


def book(cv, rng):
    cover = COVERS[int(rng.random() * len(COVERS))]
    cover = tuple(c * vary(rng, 0.9, 1.15) for c in cover)
    w, h = vary(rng, 118, 134), vary(rng, 160, 176)
    cv.frame_about(math.radians(vary(rng, -5, 5)), (0, 0))
    leather = lambda x, y, u: mix(scale(cover, 0.86), scale(cover, 1.08), p.clamp(noise(x * 0.4, y * 0.4, 8) * 0.8 + noise(x * 0.05, y * 0.05, 9) * 0.4))
    paper = lambda x, y, u: mix((228, 212, 168), (196, 172, 124), 0.5 + 0.5 * math.sin(u * 150))
    # the page block shows below and to the right of the cover
    cv.layer(rounded_box(12, 12, w - 2, h - 2, 4), (-w - 4, -h - 4, w + 24, h + 24), paper, bulge=14, spec=0.1, shadow=1.0)
    cv.layer(rounded_box(0, 0, w, h, 10), (-w - 4, -h - 4, w + 4, h + 4), leather, bulge=44, spec=0.22, gloss=14, rim=0.4,
             shadow=1.0)
    cv.layer(ring_box(0, 0, w - 30, h - 30), (-w, -h, w, h), flat(scale(cover, 0.6)), bulge=1.5, spec=0.2, rim=0)
    # the spine with raised bands
    cv.layer(rounded_box(-w + 22, 0, 22, h, 6), (-w - 4, -h - 4, -w + 48, h + 4), lambda x, y, u: scale(cover, 0.7),
             bulge=30, spec=0.2, rim=0.3)
    for fy in (-0.6, -0.2, 0.2, 0.6):
        y = fy * h
        cv.layer(rounded_box(-w + 22, y, 22, 4, 2), (-w - 2, y - 7, -w + 46, y + 7), metal((214, 176, 92), (140, 100, 44)),
                 bulge=4, spec=0.5)
    # corner caps, a title plate and a ribbon marker
    gold = metal((226, 190, 100), (150, 106, 48))
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * (w - 16), sy * (h - 16)
            cv.layer(rounded_box(x, y, 16, 16, 6), (x - 18, y - 18, x + 18, y + 18), gold, bulge=10, spec=0.5, shadow=0.6)
    cv.layer(rounded_box(18, -34, w * 0.52, 34, 6), (-w, -74, w, 6), lambda x, y, u: (226, 206, 150), bulge=10, spec=0.15,
             shadow=0.8)
    for i, (hw, y) in enumerate(((w * 0.38, -50), (w * 0.28, -34), (w * 0.34, -18))):
        cv.layer(rounded_box(18, y, hw, 2.2, 1), (18 - hw - 3, y - 4, 18 + hw + 3, y + 4), flat(scale(cover, 0.55)),
                 bulge=2, spec=0)
    cv.layer(polygon([(w * 0.5, h - 4), (w * 0.5 + 20, h - 4), (w * 0.5 + 20, h + 54), (w * 0.5 + 10, h + 44),
                      (w * 0.5, h + 54)]), (w * 0.5 - 4, h - 8, w * 0.5 + 24, h + 58), flat((176, 40, 44)), bulge=8,
             spec=0.3, shadow=0.8)
    cv.layer(rounded_box(w - 6, 36, 26, 12, 4), (w - 36, 20, w + 24, 52), gold, bulge=12, spec=0.55, shadow=0.8)


# ---- a standing figure -----------------------------------------------------------------------------------------

JACKETS = ((226, 178, 44), (180, 70, 56), (64, 106, 148), (80, 128, 92))
SKIN = ((236, 190, 150), (206, 150, 112), (160, 104, 72), (112, 72, 52))
HAIR = ((156, 156, 162), (70, 48, 36), (200, 150, 70), (40, 34, 38))


def ring_box(cx, cy, hw, hh):
    """A thin rounded frame, for the tooled border of a cover."""
    return lambda x, y: abs(rounded_box(cx, cy, hw, hh, 8)(x, y)) - 1.6


def figure(cv, rng):
    jacket = JACKETS[int(rng.random() * len(JACKETS))]
    skin = SKIN[int(rng.random() * len(SKIN))]
    hair = HAIR[int(rng.random() * len(HAIR))]
    trousers = mix((54, 66, 88), (84, 72, 60), rng.random())
    boots = (40, 36, 34)
    s = vary(rng, 0.95, 1.05)
    cloth = lambda base: (lambda x, y, u: mix(scale(base, 0.88), base, p.clamp(noise(x * 0.07, y * 0.07, 11) * 1.5)))

    def limb(x0, y0, x1, y1, r0, r1, base, bulge, shadow=0.7):
        cv.layer(segment(x0, y0, x1, y1, r0, r1), (min(x0, x1) - r0 - 4, min(y0, y1) - r0 - 4, max(x0, x1) + r0 + 4,
                                                   max(y0, y1) + r0 + 4), cloth(base) if isinstance(base, tuple) else base,
                 bulge=bulge, spec=0.12, gloss=12, shadow=shadow)

    cv.frame_about(0.0, (0, 0))
    # legs and boots (a stride a little apart), then arms held out from the body in an A, then torso and head
    for sx in (-1, 1):
        limb(sx * 24 * s, 28, sx * 40 * s, 150, 26, 19, trousers, 22)
        cv.layer(ellipse(sx * 46 * s, 176, 28, 14), (sx * 46 * s - 32, 160, sx * 46 * s + 32, 192), flat(boots), bulge=14,
                 spec=0.3, shadow=0.7)
        limb(sx * 44 * s, 150, sx * 46 * s, 168, 20, 19, boots, 18)
    for sx in (-1, 1):
        limb(sx * 54 * s, -70, sx * 104 * s, 40, 20, 15, jacket, 18)
        cv.layer(circle(sx * 108 * s, 56, 13), (sx * 108 * s - 16, 40, sx * 108 * s + 16, 72), flat(skin), bulge=13,
                 spec=0.2, shadow=0.6)
    torso = smooth_union(ellipse(0, -48, 60 * s, 40), rounded_box(0, 12, 46 * s, 54, 26), 40)
    cv.layer(torso, (-64 * s, -86, 64 * s, 72), cloth(jacket), bulge=32, spec=0.14, gloss=14, shadow=1.0)
    cv.layer(segment(0, -78, 0, 8, 2.2), (-6, -84, 6, 14), flat(scale(jacket, 0.62)), bulge=3, spec=0.2)
    cv.layer(rounded_box(0, -96, 15, 12, 6), (-18, -110, 18, -82), flat(skin), bulge=14, spec=0.15, shadow=0.7)
    cv.layer(ellipse(0, -136, 31 * s, 36), (-36, -176, 36, -98), flat(skin), bulge=32, spec=0.28, gloss=22, shadow=0.8)
    cv.layer(subtract_cap(0, -140, 33 * s, 38), (-40, -182, 40, -112), flat(hair), bulge=22, spec=0.3, shadow=0.0)
    for sx in (-1, 1):
        cv.layer(circle(sx * 12, -132, 2.6), (sx * 12 - 4, -137, sx * 12 + 4, -127), flat((44, 36, 34)), bulge=2, spec=0)
    cv.layer(rounded_box(0, -118, 6, 1.8, 1), (-9, -122, 9, -114), flat(scale(skin, 0.6)), bulge=2, spec=0)


def subtract_cap(cx, cy, rx, ry):
    """Hair: the top of a head-sized ellipse, cut off by a slanted fringe."""
    head = ellipse(cx, cy, rx, ry)
    return lambda x, y: max(head(x, y), (y - (cy - ry * 0.28 + x * 0.12)) * 0.9)


# ---- a vessel and the default cut gem -----------------------------------------------------------------------------

GLAZES = (((96, 190, 214), (30, 84, 130)), ((236, 120, 118), (130, 34, 66)), ((120, 206, 140), (30, 110, 92)),
          ((236, 196, 96), (164, 90, 40)))


def vessel(cv, rng):
    light, dark = GLAZES[int(rng.random() * len(GLAZES))]
    belly, neck = vary(rng, 84, 104), vary(rng, 26, 40)
    body = smooth_union(ellipse(0, 24, belly, 98), rounded_box(0, 136, belly * 0.5, 16, 8), 26)

    def glaze(x, y, u):
        band = 0.5 + 0.5 * math.sin(y * 0.05 + 1.2)
        return mix(mix(dark, light, p.clamp(0.4 + noise(x * 0.04, y * 0.04, 9) * 0.5)), scale(light, 1.08), band * 0.4)
    cv.layer(rounded_box(0, -112, neck, 46, 9), (-neck - 6, -170, neck + 6, -50), glaze, bulge=neck, spec=0.5, gloss=30,
             shadow=0.5)
    cv.layer(rounded_box(0, -154, neck * 1.22, 9, 6), (-neck * 1.3, -168, neck * 1.3, -138), flat(scale(dark, 0.8)),
             bulge=9, spec=0.4)
    cv.layer(body, (-belly - 8, -96, belly + 8, 162), glaze, bulge=belly, spec=0.55, gloss=40, rim=0.3, shadow=0.9)
    cv.layer(rounded_box(0, -88, neck * 1.15, 6, 4), (-neck * 1.3, -98, neck * 1.3, -78), flat(scale(dark, 0.8)),
             bulge=6, spec=0.4, shadow=0.5)


def gem(cv, rng):
    light, dark = GLAZES[int(rng.random() * len(GLAZES))]
    stretch = vary(rng, 0.9, 1.15)
    w, top, mid, bottom = 130 * stretch, -100, -50, 150
    outline = [(-w * 0.55, top), (w * 0.55, top), (w, mid), (0, bottom), (-w, mid)]
    cv.layer(polygon(outline), (-w - 6, top - 6, w + 6, bottom + 6), flat(dark), bulge=0.1, spec=0, rim=0, shadow=1.0)
    facets = [([(-w * 0.55, top), (w * 0.55, top), (w * 0.3, mid), (-w * 0.3, mid)], 1.18),
              ([(-w * 0.55, top), (-w * 0.3, mid), (-w, mid)], 0.98),
              ([(w * 0.55, top), (w, mid), (w * 0.3, mid)], 0.72),
              ([(-w, mid), (-w * 0.3, mid), (0, bottom)], 0.86),
              ([(-w * 0.3, mid), (w * 0.3, mid), (0, bottom)], 1.06),
              ([(w * 0.3, mid), (w, mid), (0, bottom)], 0.62)]
    for points, tone in facets:
        centre = (sum(q[0] for q in points) / len(points), sum(q[1] for q in points) / len(points))
        cv.layer(polygon(points), (-w - 6, top - 6, w + 6, bottom + 6),
                 (lambda t: (lambda x, y, u: mix(scale(light, t), scale(dark, t), p.clamp((y - top) / 250))))(tone),
                 bulge=1.0, spec=0.0, rim=0.0)
    cv.layer(polygon([(-w * 0.35, top + 14), (-w * 0.12, top + 14), (-w * 0.2, mid - 6)]),
             (-w, top, 0, mid), flat((226, 232, 232)), bulge=6, spec=0, glow=1)


PAINTERS = {"instrument": stringed_instrument, "lantern": lantern, "book": book, "figure": figure, "vessel": vessel,
            "gem": gem}
