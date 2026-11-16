"""The `background` settings object: how a subject is separated from its background (plain Python, no numpy).

One owner of the shape and of its validation. It is the same object as `capture.background` in a
pipeline file (pipeline/pipeline_file.py checks its values with `check_for`), the `background` key of a
normalize_image config, `capture.background` in a mesh_finish or gate v2 config, and what
pipeline/subject_mask.py is handed. The mask itself is subject_mask's job; the key lists and value rules
are here. There are no defaults: every key a method needs is required.

  near_white  tolerance (0..255, a channel level; border-connected pixels with every channel at or
              above it are background). color is optional (prompt side, the mask ignores it).
  chroma_key  color [r, g, b] (the flat key), tolerance (a distance up to which a pixel is key),
              feather (distance over which alpha ramps from 0 to 1 past the tolerance), luma_weight
              (0..1, how much brightness counts in the distance), holes (true: key-colour regions
              enclosed by the subject are background too), despill (0..1, how far edge pixels are
              moved toward the colour they would have without the key behind them).

`words` is allowed in both (the prompt wording beside the values); it is not mask data and `parse` drops it.
"""
import normaliser_common as common

NEAR_WHITE = "near_white"
CHROMA_KEY = "chroma_key"
MAX_DISTANCE = 360  # the largest chroma_key distance is about 255 * sqrt(2); anything above never matches
MIN_FEATHER = 0.5   # a feather under half a unit is a hard edge; the alpha ramp divides by it

# method -> ordered {key: (check, needed by the mask)}; `words` is added by allowed_keys
FIELDS = {
    NEAR_WHITE: {"color": (common.rgb, False), "tolerance": (common.channel, True)},
    CHROMA_KEY: {"color": (common.rgb, True), "tolerance": (common.number_between(0, MAX_DISTANCE), True),
                 "feather": (common.number_between(MIN_FEATHER, MAX_DISTANCE), True),
                 "luma_weight": (common.number_between(0, 1), True), "holes": (common.boolean, True),
                 "despill": (common.number_between(0, 1), True)},
}
METHODS = tuple(FIELDS)
PROMPT_KEY = "words"


class BackgroundError(ValueError):
    """A bad background object; `key` is the offending key (None for the object), `message` what is wrong."""

    def __init__(self, key, message):
        self.key, self.message = key, message
        super().__init__(f"{key} {message}" if key else message)


def allowed_keys(method):
    """Every key an object of METHOD may carry, in documentation order: method, the method's keys, words."""
    return ("method", *FIELDS[method], PROMPT_KEY)


def check_for(method, key):
    """The value check for KEY under METHOD (words included); ValueError when the key is not allowed."""
    if key == PROMPT_KEY:
        return common.text
    if key == "method":
        return common.one_of(*METHODS)
    return FIELDS[method][key][0]


def parse(raw):
    """Validate a background object and return its mask settings (method and the method's keys, no words)."""
    if not isinstance(raw, dict):
        raise BackgroundError(None, "must be an object")
    if "method" not in raw:
        raise BackgroundError("method", "is required (one of: " + ", ".join(map(repr, METHODS)) + ")")
    method = raw["method"]
    try:
        common.one_of(*METHODS)(method)
    except (ValueError, TypeError) as exc:
        raise BackgroundError("method", str(exc))
    for key, (_, needed) in FIELDS[method].items():
        if needed and key not in raw:
            raise BackgroundError(key, f"is required for method '{method}'")
    for key in raw:
        if key not in allowed_keys(method):
            raise BackgroundError(key, f"is not a key of method '{method}' (allowed: {', '.join(allowed_keys(method))})")
    for key in raw:
        try:
            check_for(method, key)(raw[key])
        except ValueError as exc:
            raise BackgroundError(key, str(exc))
    return {key: raw[key] for key in ("method", *FIELDS[method]) if key in raw}


def near_white(tolerance):
    """The near_white settings for a bare tolerance (the `--tolerance` flags and the older config keys)."""
    return parse({"method": NEAR_WHITE, "tolerance": tolerance})
