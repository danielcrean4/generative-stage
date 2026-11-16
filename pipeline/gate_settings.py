"""Defaults and validation for the subject matte and the mesh shape gate (plain Python, no numpy).

Shared by the job runner, pipeline/matte.py and pipeline/mesh_gates.py so the names and numbers live in
one place. Thresholds are provisional and meant to be overridden per job.
"""
MATTE_DEFAULTS = {
    "tolerance": 236,          # channel value at or above which a border-connected pixel is background
    "min_largest_share": 0.95,  # largest subject component, as a share of all subject pixels
    "min_coverage": 0.05,       # subject share of the frame, lower bound
    "max_coverage": 0.90,       # subject share of the frame, upper bound
    "allow_border": False,      # a subject touching the image edge fails unless this is true
}
MESH_CHECK_DEFAULTS = {
    "min_largest_piece_share": 0.98,  # surface area of the largest connected piece
    "max_thin_sheet_share": 0.20,     # area on opposed, nearly coincident planes (a card through the subject)
    "max_silhouette_excess": 0.12,    # mesh silhouette box fill minus image subject box fill
    "min_silhouette_iou": 0.60,       # best-view overlap of mesh silhouette and image subject
    "require_watertight": False,      # watertight is reported; it gates only when this is true
}
_UNIT_KEYS = {"min_largest_share", "min_coverage", "max_coverage", "min_largest_piece_share",
              "max_thin_sheet_share", "max_silhouette_excess", "min_silhouette_iou"}
_BOOL_KEYS = {"allow_border", "require_watertight"}
MAX_CHANNEL = 255


def _merged(defaults, overrides, what):
    if not isinstance(overrides, dict) or set(overrides) - set(defaults):
        raise ValueError(f"{what} must be an object with only: {', '.join(sorted(defaults))}")
    merged = {**defaults, **overrides}
    for key, value in merged.items():
        if key in _BOOL_KEYS:
            ok = type(value) is bool
        elif key in _UNIT_KEYS:
            ok = type(value) in (int, float) and 0 <= value <= 1
        else:
            ok = type(value) is int and 0 <= value <= MAX_CHANNEL
        if not ok:
            raise ValueError(f"invalid {what} value for {key}")
    return merged


def matte_settings(overrides=None):
    """Return the matte settings with defaults filled in; ValueError if anything is invalid."""
    merged = _merged(MATTE_DEFAULTS, overrides or {}, "matte settings")
    if merged["min_coverage"] > merged["max_coverage"]:
        raise ValueError("matte min_coverage must not exceed max_coverage")
    return merged


def mesh_checks(overrides=None):
    """Return the mesh gate thresholds with defaults filled in; ValueError if invalid."""
    return _merged(MESH_CHECK_DEFAULTS, overrides or {}, "mesh_checks")
