"""Shared plumbing for the normalisers: one config validator, the report writer, loud exits (plain Python).

Every normaliser declares a SCHEMA, {key: check}, and calls load_config. There are no defaults here or
in the scripts: a look value is data, so a missing key is an error that names the
key and the config file. The report records the config's sha256 so a later reader can tell which
values made an output.
"""
import hashlib
import json
import sys
from pathlib import Path

EXIT_BAD_INPUT = 2


class NormaliserError(Exception):
    """Bad input or bad config; main() prints it and exits EXIT_BAD_INPUT."""


def positive_int(value):
    if type(value) is not int or value <= 0:
        raise ValueError("must be a whole number above 0")


def non_negative_int(value):
    if type(value) is not int or value < 0:
        raise ValueError("must be a whole number, 0 or more")


def channel(value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("must be a whole number from 0 to 255")


def positive_number(value):
    if type(value) not in (int, float) or not value > 0:
        raise ValueError("must be a number above 0")


def share(value):
    """A fraction from 0 up to, but not including, 1."""
    if type(value) not in (int, float) or not 0 <= value < 1:
        raise ValueError("must be a number from 0 up to (not including) 1")


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a non-empty string")


def number_between(low, high):
    def check(value):
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError(f"must be a number from {low} to {high}")
    return check


def boolean(value):
    if type(value) is not bool:
        raise ValueError("must be true or false")


def rgb(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("must be a list of three channel values [r, g, b]")
    for item in value:
        channel(item)


def one_of(*choices):
    def check(value):
        if value not in choices:
            raise ValueError("must be one of: " + ", ".join(map(repr, choices)))
    return check


def load_config(path, schema, tool, either=()):
    """Read PATH and return (config, sha256 of the file); NormaliserError names the file and key.

    EITHER lists groups of schema keys of which exactly one must be present (a group replaces the
    "every key is required" rule for its own keys), such as the two ways to say how the background goes.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NormaliserError(f"{tool}: cannot read config {path}: {exc.strerror or exc}")
    try:
        config = json.loads(raw)
    except ValueError as exc:
        raise NormaliserError(f"{tool}: config {path} is not valid JSON: {exc}")
    if not isinstance(config, dict):
        raise NormaliserError(f"{tool}: config {path} must be a JSON object")
    grouped = {key for group in either for key in group}
    for key in schema:
        if key not in config and key not in grouped:
            raise NormaliserError(f"{tool}: config {path} is missing required key '{key}'")
    for group in either:
        if sum(key in config for key in group) != 1:
            raise NormaliserError(f"{tool}: config {path} needs exactly one of " + " or ".join(f"'{key}'" for key in group))
    for key in config:
        if key not in schema:
            raise NormaliserError(f"{tool}: config {path} has unknown key '{key}' (allowed: {', '.join(schema)})")
    for key, check in schema.items():
        if key not in config:
            continue
        try:
            check(config[key])
        except ValueError as exc:
            raise NormaliserError(f"{tool}: config {path} key '{key}' {exc}")
    return config, hashlib.sha256(raw).hexdigest()


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def require_file(path, tool, what):
    if not Path(path).is_file():
        raise NormaliserError(f"{tool}: {what} {path} does not exist or is not a file")


def run(tool, main):
    """Call main(); turn NormaliserError into a message on stderr and a non-zero exit."""
    try:
        return main()
    except NormaliserError as exc:
        print(exc, file=sys.stderr)
        return EXIT_BAD_INPUT
