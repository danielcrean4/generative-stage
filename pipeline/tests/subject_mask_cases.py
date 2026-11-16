"""Cases for pipeline/subject_mask.py with ground-truth images; run under the tools interpreter
(numpy, scipy, Pillow) by tests/test_subject_mask.py, which prints SUBJECT_MASK.

Run: python -I tests/subject_mask_cases.py TOOLS_DIR FIXTURES_DIR
Prints one JSON object: {"cases": [{"label", "ok", "error"}...], "reports": {name: numbers}}.
"""
import glob
import json
import sys
import tempfile
import traceback
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

TOOLS, FIXTURES = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(TOOLS))
import background_spec  # noqa: E402
import icon_batch  # noqa: E402
import machine  # noqa: E402
import subject_mask  # noqa: E402

SIZE = 96
MAGENTA = (255, 0, 255)
SEED = 7
# Settings mirroring icon_batch's thresholds (see docs/normalisers.md "Matching the icon routine").
ICON_LIKE = {"method": "chroma_key", "color": list(MAGENTA), "tolerance": 75, "feather": 35, "luma_weight": 0.25,
             "holes": True, "despill": 0}
KEYED = {**ICON_LIKE, "holes": False}
SUPERSAMPLE = 4
NOISE_SIGMA = 5
MAX_MISMATCH = 0.002   # share of pixels a noisy image may get wrong
RAW_LIMIT = 5          # real raw icon images reported at most (read-only)
ICON_SHARE_LIMIT = 0.02
ICON_MEAN_LIMIT = 0.01
EDGE_IOU = 0.97
CASES, REPORTS = [], {}


def case(function):
    CASES.append(function)
    return function


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def key_image(color=MAGENTA, size=SIZE):
    return np.full((size, size, 3), color, np.uint8)


def disc(cx, cy, r, size=SIZE, scale=1):
    """Coverage 0..1 of a disc, by supersampling."""
    n = size * scale
    ys, xs = (np.mgrid[0:n, 0:n] + 0.5) / scale
    return ((xs - cx) ** 2 + (ys - cy) ** 2 <= r * r).astype(float)


def coverage(cx, cy, r, size=SIZE):
    fine = disc(cx, cy, r, size, SUPERSAMPLE)
    return fine.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE).mean(axis=(1, 3))


def paint(base, mask, color):
    out = base.copy()
    out[mask] = color
    return out


def image_of(array):
    return Image.fromarray(array.astype(np.uint8), "RGB")


def mismatch(a, b):
    return float((a != b).mean())


def sep(array, settings=KEYED):
    return subject_mask.separate(image_of(array), settings)


def agree(result):
    """Mask and alpha come from one computation: they agree everywhere."""
    check(np.array_equal(result.subject, result.alpha > 0), "mask differs from alpha > 0")


@case
def solid_key_hard_edges_match_truth():
    truth = disc(48, 48, 30) > 0
    for colour in ((40, 120, 200), (240, 240, 240), (10, 10, 10), (220, 140, 40)):
        result = sep(paint(key_image(), truth, colour))
        check(np.array_equal(result.subject, truth), f"subject {colour} differs from truth")
        check(set(np.unique(result.alpha)) == {0.0, 1.0}, "solid edges should give alpha of 0 or 1 only")
        agree(result)


@case
def noise_and_hue_drift_do_not_break_the_key():
    rng = np.random.default_rng(SEED)
    truth = disc(48, 48, 28) > 0
    ramp = np.linspace(0, 1, SIZE)[None, :, None]
    drift = (np.array(MAGENTA) * (1 - ramp) + np.array((238, 16, 232)) * ramp) * np.ones((SIZE, 1, 1))
    picture = np.where(truth[..., None], np.array((220, 140, 40)), drift)
    noisy = np.clip(picture + rng.normal(0, NOISE_SIGMA, picture.shape), 0, 255)
    result = sep(noisy)
    wrong = mismatch(result.subject, truth)
    check(wrong <= MAX_MISMATCH, f"{wrong:.4f} of pixels wrong with noise and drift")
    REPORTS["noise_and_drift"] = {"mismatch_share": round(wrong, 5)}


@case
def subjects_that_share_a_channel_with_the_key_are_kept():
    truth = disc(48, 48, 28) > 0
    for name, colour in (("red", (255, 0, 0)), ("blue", (0, 0, 255)), ("green", (0, 255, 0)),
                         ("white", (255, 255, 255)), ("black", (0, 0, 0)), ("orange", (255, 128, 0))):
        result = sep(paint(key_image(), truth, colour))
        check(np.array_equal(result.subject, truth), f"{name} subject differs from truth")
        check(result.alpha[truth].min() == 1.0, f"{name} subject is not fully opaque")


@case
def a_subject_near_the_key_colour_is_lost_and_that_is_stated():
    truth = disc(48, 48, 28) > 0
    result = sep(paint(key_image(), truth, (200, 0, 200)))
    check(result.subject.sum() == 0, "a subject within the tolerance of the key should read as key (documented limit)")


def holed(size=SIZE):
    """A disc with a square hole through it (shows the key); returns (picture, truth with hole, truth without)."""
    solid = disc(48, 48, 36) > 0
    hole = np.zeros((size, size), bool)
    hole[40:56, 40:56] = True
    return paint(paint(key_image(), solid, (40, 120, 200)), hole, MAGENTA), solid & ~hole, solid


@case
def an_enclosed_hole_follows_the_holes_setting():
    picture, with_hole, filled = holed()
    kept = sep(picture, {**KEYED, "holes": False})
    check(np.array_equal(kept.subject, filled), "holes false should fill the enclosed hole")
    check(kept.alpha[44:52, 44:52].min() == 1.0, "a filled hole should be opaque")
    opened = sep(picture, {**KEYED, "holes": True})
    check(np.array_equal(opened.subject, with_hole), "holes true should leave the hole as background")
    check(opened.alpha[44:52, 44:52].max() == 0.0, "an opened hole should be transparent")
    agree(kept), agree(opened)


@case
def a_notch_open_to_the_border_is_background_either_way():
    solid = disc(48, 48, 36) > 0
    notch = np.zeros_like(solid)
    notch[44:52, 48:] = True  # a slot from the middle out through the right edge of the disc
    picture = paint(paint(key_image(), solid, (40, 120, 200)), notch, MAGENTA)
    for holes in (False, True):
        result = sep(picture, {**KEYED, "holes": holes})
        check(np.array_equal(result.subject, solid & ~notch), f"notch should be background with holes={holes}")


@case
def anti_aliased_edges_get_a_soft_alpha_and_the_mask_agrees_with_it():
    cover = coverage(48, 48, 30)
    colour = np.array((40, 120, 200), float)
    picture = cover[..., None] * colour + (1 - cover[..., None]) * np.array(MAGENTA, float)
    result = sep(np.rint(picture))
    truth = cover >= 0.5
    inter = (result.subject & truth).sum()
    iou = inter / (result.subject | truth).sum()
    check(iou >= EDGE_IOU, f"IoU {iou:.3f} with the half-coverage truth")
    check(result.subject[cover >= 1].all(), "fully covered pixels must be subject")
    check(not result.subject[cover <= 0].any(), "uncovered pixels must be background")
    soft = (result.alpha > 0) & (result.alpha < 1)
    check(soft.sum() > 0, "an anti-aliased edge should give some partial alpha")
    check(result.alpha[cover >= 1].min() == 1.0, "interior alpha must be 1")
    agree(result)
    REPORTS["anti_aliased"] = {"iou_vs_half_coverage": round(float(iou), 4), "soft_pixels": int(soft.sum())}


@case
def a_subject_touching_the_border_stays_whole():
    truth = disc(8, 48, 30) > 0  # cut off by the left edge
    result = sep(paint(key_image(), truth, (40, 120, 200)))
    check(np.array_equal(result.subject, truth), "border-touching subject differs from truth")
    check(result.subject[:, 0].any(), "the subject should reach the image edge")


@case
def despill_pulls_edge_pixels_away_from_the_key_and_leaves_the_rest():
    cover = coverage(48, 48, 30)
    picture = np.rint(cover[..., None] * np.array((40, 120, 200), float) + (1 - cover[..., None]) * np.array(MAGENTA, float))
    spill = lambda r: float((np.minimum(r.rgb[..., 0], r.rgb[..., 2]).astype(int) - r.rgb[..., 1])[(r.alpha > 0) & (r.alpha < 1)].mean())
    none, half, full = (sep(picture, {**KEYED, "despill": amount}) for amount in (0, 0.5, 1))
    check(np.array_equal(none.rgb, picture.astype(np.uint8)), "despill 0 must leave the colours alone")
    check(spill(none) > spill(half) > spill(full), "more despill should mean less key colour on the edge")
    inside = full.alpha == 1
    check(np.array_equal(full.rgb[inside], picture.astype(np.uint8)[inside]), "opaque pixels must not change")
    check(np.array_equal(none.subject, full.subject), "despill must not move the mask")


@case
def real_alpha_wins_over_the_method():
    rgba = np.zeros((SIZE, SIZE, 4), np.uint8)
    rgba[..., :3] = MAGENTA
    rgba[20:60, 20:60, 3] = 255
    result = subject_mask.separate(Image.fromarray(rgba, "RGBA"), KEYED)
    check(np.array_equal(result.subject, rgba[..., 3] > 127), "an image with real alpha should use it")


def reference_subject(image, tolerance):
    """Frozen copy of the pre-chroma subject_mask (origin/main 5ef923a): the oracle for 'unchanged, bit for bit'."""
    from scipy import ndimage
    if image.mode == "RGBA":
        alpha = np.asarray(image)[:, :, 3]
        if alpha.min() < 250:
            return alpha > 127
    rgb = np.asarray(image.convert("RGB"))
    labels, _ = ndimage.label((rgb >= tolerance).all(axis=2))
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    return ~np.isin(labels, border[border != 0])


@case
def near_white_is_unchanged_bit_for_bit_on_the_gate_fixtures():
    rng = np.random.default_rng(SEED)
    images = {path.name: Image.open(path) for path in sorted(FIXTURES.glob("*.png"))}
    images["noise"] = Image.fromarray(rng.integers(180, 256, (64, 64, 3), dtype=np.uint8), "RGB")
    rgba = np.dstack([np.asarray(images["noise"]), rng.integers(0, 256, (64, 64), dtype=np.uint8)])
    images["real-alpha"] = Image.fromarray(rgba, "RGBA")
    check(len(images) >= 5, "expected the gate fixtures")
    compared = 0
    for name, image in images.items():
        for tolerance in (0, 128, 200, 236, 250, 255):
            old = reference_subject(image, tolerance)
            new = subject_mask.subject_from_image(image, {"method": "near_white", "tolerance": tolerance})
            check(np.array_equal(old, new), f"{name} at tolerance {tolerance} differs from the old mask")
            via_flood = subject_mask.border_flood_subject(np.asarray(image.convert("RGB")), tolerance)
            if image.mode == "RGB":
                check(np.array_equal(old, via_flood), f"{name} border_flood_subject differs at {tolerance}")
            compared += 1
    REPORTS["near_white_bit_for_bit"] = {"images": len(images), "comparisons": compared}


@case
def near_white_ignores_color_and_words():
    image = Image.open(next(iter(sorted(FIXTURES.glob("*.png")))))
    plain = subject_mask.separate(image, {"method": "near_white", "tolerance": 236})
    labelled = subject_mask.separate(image, {"method": "near_white", "tolerance": 236, "color": [255, 255, 255], "words": "plain white"})
    check(np.array_equal(plain.subject, labelled.subject), "color and words must not affect near_white")


CONFIG_ERRORS = [
    ("not an object", [], "must be an object"),
    ("no method", {"tolerance": 5}, "method is required (one of: 'near_white', 'chroma_key')"),
    ("bad method", {"method": "green"}, "method must be one of: 'near_white', 'chroma_key'"),
    ("near_white no tolerance", {"method": "near_white"}, "tolerance is required for method 'near_white'"),
    ("near_white bad tolerance", {"method": "near_white", "tolerance": 300}, "tolerance must be a whole number from 0 to 255"),
    ("near_white chroma key", {"method": "near_white", "tolerance": 5, "feather": 3},
     "feather is not a key of method 'near_white' (allowed: method, color, tolerance, words)"),
    ("chroma no color", {k: v for k, v in KEYED.items() if k != "color"}, "color is required for method 'chroma_key'"),
    ("chroma no feather", {k: v for k, v in KEYED.items() if k != "feather"}, "feather is required for method 'chroma_key'"),
    ("chroma no holes", {k: v for k, v in KEYED.items() if k != "holes"}, "holes is required for method 'chroma_key'"),
    ("chroma no despill", {k: v for k, v in KEYED.items() if k != "despill"}, "despill is required for method 'chroma_key'"),
    ("chroma no luma_weight", {k: v for k, v in KEYED.items() if k != "luma_weight"}, "luma_weight is required for method 'chroma_key'"),
    ("chroma bad color", {**KEYED, "color": [1, 2]}, "color must be a list of three channel values [r, g, b]"),
    ("chroma bad tolerance", {**KEYED, "tolerance": 500}, "tolerance must be a number from 0 to 360"),
    ("chroma bad feather", {**KEYED, "feather": 0}, "feather must be a number from 0.5 to 360"),
    ("chroma bad luma", {**KEYED, "luma_weight": 2}, "luma_weight must be a number from 0 to 1"),
    ("chroma bad holes", {**KEYED, "holes": "yes"}, "holes must be true or false"),
    ("chroma bad despill", {**KEYED, "despill": -1}, "despill must be a number from 0 to 1"),
    ("chroma bad words", {**KEYED, "words": " "}, "words must be a non-empty string"),
    ("chroma unknown key", {**KEYED, "gloss": 1},
     "gloss is not a key of method 'chroma_key' (allowed: method, color, tolerance, feather, luma_weight, holes, despill, words)"),
]


@case
def configuration_errors_have_exact_messages():
    for label, raw, message in CONFIG_ERRORS:
        try:
            background_spec.parse(raw)
        except background_spec.BackgroundError as exc:
            check(str(exc) == message, f"{label}: got {str(exc)!r}, wanted {message!r}")
        else:
            raise AssertionError(f"{label}: no error")
        try:
            subject_mask.separate(Image.new("RGB", (4, 4)), raw)
        except background_spec.BackgroundError:
            pass
        else:
            raise AssertionError(f"{label}: separate accepted it")
    REPORTS["config_errors"] = {"count": len(CONFIG_ERRORS)}


def white_object(size=SIZE):
    """A white, softly shaded object with no outline: bright top left, light grey bottom right. Returns (rgb, truth)."""
    truth = disc(48, 48, 34) > 0
    ys, xs = np.mgrid[0:size, 0:size]
    shade = 255 - np.clip((xs + ys - 40) * 0.5, 0, 60)   # 255 at the top left down to 195
    rgb = np.repeat(shade[..., None], 3, axis=2)
    return rgb, truth


@case
def white_on_white_loses_mask_area_but_on_a_key_colour_it_does_not():
    rgb, truth = white_object()
    on_white = np.where(truth[..., None], rgb, 255).astype(np.uint8)
    on_key = np.where(truth[..., None], rgb, np.array(MAGENTA)).astype(np.uint8)
    near = subject_mask.subject_from_image(image_of(on_white), {"method": "near_white", "tolerance": 236})
    keyed = subject_mask.subject_from_image(image_of(on_key), KEYED)
    recall = lambda mask: float((mask & truth).sum() / truth.sum())
    iou = lambda mask: float((mask & truth).sum() / (mask | truth).sum())
    check(recall(near) < 0.85, f"near_white on white kept {recall(near):.3f}; the example should lose area")
    check(np.array_equal(keyed, truth), "chroma_key on the key colour should keep the whole silhouette")
    REPORTS["white_on_white"] = {"near_white_on_white": {"kept_share_of_truth": round(recall(near), 4), "iou": round(iou(near), 4)},
                                 "chroma_key_on_key": {"kept_share_of_truth": round(recall(keyed), 4), "iou": round(iou(keyed), 4)},
                                 "truth_pixels": int(truth.sum())}


class _Stop(Exception):
    pass


def icon_alpha(raw_path):
    """The alpha icon_batch.prepare's keying produces for RAW_PATH, taken from prepare itself (it is not copied).

    prepare keys the pixels, then calls getbbox on the keyed image; the spy keeps that image and stops there.
    """
    seen = {}

    def spy(self, *args, **kwargs):
        seen["image"] = self.copy()
        raise _Stop
    with mock.patch.object(Image.Image, "getbbox", spy), tempfile.TemporaryDirectory() as folder:
        try:
            icon_batch.prepare(raw_path, Path(folder) / "icon.png")
        except _Stop:
            pass
    return np.asarray(seen["image"])[:, :, 3].astype(float) / 255


def compare_with_icon(raw_path):
    old = icon_alpha(raw_path)
    new = subject_mask.separate(Image.open(raw_path).convert("RGB"), ICON_LIKE).alpha.astype(float)
    diff = np.abs(old - new)
    far = diff > 0.1
    partial = ((old > 0) & (old < 1)) | ((new > 0) & (new < 1))
    return {"mean_abs_alpha_diff": round(float(diff.mean()), 5), "max_abs_alpha_diff": round(float(diff.max()), 4),
            "share_differing_over_0.1": round(float(far.mean()), 5),
            "share_of_those_on_an_edge": round(float(partial[far].mean()), 4) if far.any() else None}


def synthetic_icons(folder):
    """Magenta-background pictures with the things icons have: flat colours, pastel pinks, soft edges, noise, a gradient."""
    rng = np.random.default_rng(SEED)
    paths = []
    for index, colours in enumerate((((40, 120, 200), (230, 190, 60)), ((255, 200, 230), (250, 250, 250)),
                                     ((120, 70, 40), (30, 140, 60)))):
        cover_a, cover_b = coverage(34, 48, 24), coverage(64, 50, 20)
        background = np.array(MAGENTA, float) * np.ones((SIZE, SIZE, 1))
        if index == 2:   # slightly drifting backdrop, like a real generation
            background = background + np.linspace(0, -18, SIZE)[None, :, None] * np.array((1, -1, 1))
        picture = background
        for cover, colour in ((cover_a, colours[0]), (cover_b, colours[1])):
            picture = cover[..., None] * np.array(colour, float) + (1 - cover[..., None]) * picture
        picture = np.clip(picture + rng.normal(0, 3 * index, picture.shape), 0, 255)
        path = Path(folder) / f"synthetic-{index}.png"
        image_of(np.rint(picture)).save(path)
        paths.append(path)
    return paths


def pink_differences(folder):
    """Alpha of strong pinks (near the magenta key) under the icon routine and under the new key: both make them
    partly see-through, by different amounts. Reported, not asserted."""
    found = {}
    for colour in ((255, 170, 220), (240, 150, 200), (255, 120, 200)):
        flat = np.full((8, 8, 3), colour, np.uint8)
        flat[:, :2] = MAGENTA
        path = Path(folder) / "pink.png"
        image_of(flat).save(path)
        found[str(colour)] = {"icon_alpha": round(float(icon_alpha(path)[4, 5]), 3),
                              "new_alpha": round(float(subject_mask.separate(image_of(flat), ICON_LIKE).alpha[4, 5]), 3)}
    return found


@case
def the_chroma_key_tracks_the_icon_routine_on_synthetic_and_real_magenta_images():
    with tempfile.TemporaryDirectory() as folder:
        synthetic = {path.name: compare_with_icon(path) for path in synthetic_icons(folder)}
        pinks = pink_differences(folder)
    # Real generations are reported, not asserted: the folder grows and a pink-heavy icon would move the numbers.
    try:
        icon_dir = machine.path("icon_dir")  # machine setting: where icon_batch.py keeps its working folders
    except machine.MachineError:
        icon_dir = None
    real_paths = sorted(glob.glob(str(icon_dir / "*/raw.png")))[:RAW_LIMIT] if icon_dir else []
    real = {Path(p).parent.name: compare_with_icon(p) for p in real_paths}
    for name, numbers in synthetic.items():
        check(numbers["share_differing_over_0.1"] <= ICON_SHARE_LIMIT, f"{name}: {numbers}")
        check(numbers["mean_abs_alpha_diff"] <= ICON_MEAN_LIMIT, f"{name}: {numbers}")
    REPORTS["icon_equivalence"] = {"settings": {k: ICON_LIKE[k] for k in ("tolerance", "feather", "luma_weight", "holes")},
                                   "synthetic": synthetic, "pinks_near_the_key": pinks, "real": real if real else "no raw icon images on disk"}


def main():
    results = []
    for function in CASES:
        try:
            function()
            results.append({"label": function.__name__, "ok": True, "error": ""})
        except Exception:
            results.append({"label": function.__name__, "ok": False, "error": traceback.format_exc()})
    json.dump({"cases": results, "reports": REPORTS}, sys.stdout)


if __name__ == "__main__":
    main()
