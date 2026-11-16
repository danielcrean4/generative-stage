"""Subject masks from images: the one owner of background separation. Needs numpy, scipy and Pillow
(run under the tools interpreter).

How the subject is told from the background is a `background` settings object (pipeline/background_spec.py
owns its shape; it is `capture.background` in a pipeline file):

  near_white  border-connected pixels with every channel at or above `tolerance` are background.
  chroma_key  the background is a flat key colour. Each pixel gets a distance from the key in a chroma
              space (BT.601 Y, Cb, Cr) with the luminance difference scaled by `luma_weight`:

                  d = sqrt((luma_weight * dY)^2 + dCb^2 + dCr^2)

              Why this measure: the generator's backgrounds drift slightly in brightness and carry
              JPEG-like noise, which mostly moves Y, so Y is down-weighted while the hue and
              saturation (Cb, Cr) decide. Unlike a per-channel rule such as `min(r, b) - g` (right
              for magenta only), it works for any key colour, and a subject that shares one channel
              with the key (red on magenta) still lands far away because Cb and Cr mix all three
              channels. A subject whose hue is within `tolerance` of the key is lost; that is a
              property of the key, so pick a key colour the subject does not use.

              alpha = clip((d - tolerance) / feather, 0, 1). A pixel with alpha 0 is key-like.
              Key-like pixels connected to the image border are background; key-like pixels enclosed
              by the subject are background only when `holes` is true, otherwise they are subject
              (alpha 1). The hard subject mask is `alpha > 0` of that same result, so mask and alpha
              cannot disagree. Edge pixels (0 < alpha < 1) are despilled: a pixel at distance d from the
              key is pushed along the line away from the key to distance tolerance + feather (where
              alpha reaches 1), by `despill` of the way (0 leaves it alone). That removes the key's
              share without needing the true coverage, and cannot overshoot past an opaque pixel's
              nearest possible distance. The mask therefore includes the whole feather band; keep `feather` small to tighten it.

An image with a real alpha channel (some alpha below ALPHA_OPAQUE_MIN) uses that alpha whatever the method.
"""
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

import background_spec

ALPHA_OPAQUE_MIN = 250  # an image whose lowest alpha is below this has a real matte
ALPHA_THRESHOLD = 127   # alpha above this counts as subject
MAX_CHANNEL = 255
# BT.601 full-range RGB -> (Y, Cb, Cr), without the +128 offset (only differences are used).
YCC = np.array([[0.299, 0.587, 0.114],
                [-0.168736, -0.331264, 0.5],
                [0.5, -0.418688, -0.081312]], dtype=np.float32)


@dataclass(frozen=True)
class Separation:
    """subject: bool mask. alpha: float32 0..1, nonzero exactly where subject is True. rgb: uint8, despilled at the edge."""
    subject: np.ndarray
    alpha: np.ndarray
    rgb: np.ndarray


def border_connected(region):
    """True where a pixel of REGION (bool) belongs to a connected piece that touches the image border."""
    labels, _ = ndimage.label(region)
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    return np.isin(labels, border[border != 0])


def border_flood_subject(rgb, tolerance):
    """True where a pixel is not near-white background connected to the image border."""
    return ~border_connected((rgb >= tolerance).all(axis=2))


def erode_subject(subject):
    """Drop one pixel of fringe; the image edge itself does not erode a subject touching it."""
    return ndimage.binary_erosion(subject, iterations=1, border_value=1)


def key_distance(rgb, background):
    """Distance of every pixel of RGB (uint8, h x w x 3) from the chroma key colour, as float32."""
    ycc = rgb.astype(np.float32) @ YCC.T
    delta = ycc - np.array(background["color"], dtype=np.float32) @ YCC.T
    delta[..., 0] *= background["luma_weight"]
    return np.sqrt((delta * delta).sum(axis=2))


def chroma_separate(rgb, background):
    """Separation of RGB (uint8) by the chroma_key settings in BACKGROUND (see the module doc)."""
    distance = key_distance(rgb, background)
    alpha = np.clip((distance - background["tolerance"]) / background["feather"], 0.0, 1.0)
    keylike = alpha <= 0
    if not background["holes"]:
        alpha = np.where(keylike & ~border_connected(keylike), 1.0, alpha)
    alpha = alpha.astype(np.float32)
    edge = (alpha > 0) & (alpha < 1)
    out = rgb.copy()
    if edge.any() and background["despill"] > 0:
        key = np.array(background["color"], dtype=np.float32)
        pixel = rgb[edge].astype(np.float32)
        push = (background["tolerance"] + background["feather"]) / distance[edge][:, None]  # > 1 inside the ramp
        pushed = np.clip(key + (pixel - key) * (1 + background["despill"] * (push - 1)), 0, MAX_CHANNEL)
        out[edge] = np.rint(pushed).astype(np.uint8)
    return Separation(alpha > 0, alpha, out)


def separate(image, background):
    """Separation for the PIL image; BACKGROUND is a settings object (validated here, extra `words` allowed).

    Real alpha wins when the image has it; otherwise the method decides. near_white gives a hard
    0/1 alpha and leaves the colours alone.
    """
    background = background_spec.parse(background)
    if image.mode == "RGBA":
        raw = np.asarray(image)
        if raw[:, :, 3].min() < ALPHA_OPAQUE_MIN:
            subject = raw[:, :, 3] > ALPHA_THRESHOLD
            return Separation(subject, subject.astype(np.float32), np.ascontiguousarray(raw[:, :, :3]))
    rgb = np.asarray(image.convert("RGB"))
    if background["method"] == background_spec.CHROMA_KEY:
        return chroma_separate(rgb, background)
    subject = border_flood_subject(rgb, background["tolerance"])
    return Separation(subject, subject.astype(np.float32), rgb)


def subject_from_image(image, background):
    """Subject mask: real alpha when the PIL image has it, otherwise from BACKGROUND (see separate)."""
    return separate(image, background).subject


def load_subject(path, background):
    """Subject mask for the image file at PATH (see subject_from_image)."""
    return subject_from_image(Image.open(path), background)
