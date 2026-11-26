#!/usr/bin/env python3
"""Write KEY VALUE pairs into a template file after checking that every key is a known template option."""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import re
import sys
from pathlib import Path

FAMILIES = ("mintpy", "miaplpy", "minsar", "topsStack", "stripmapStack", "alos2Stack")
_DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "defaults"
_MINSAR_KEY_FILES = ("minsar_template.cfg", "minsar_template_defaults.cfg", "processing_Sentinel1.template", "processing_Alos2.template")
_PACKAGE_KEY_FILES = {"mintpy": "smallbaselineApp.cfg", "miaplpy": "miaplpyApp.cfg"}
# Commented lines count: the default files document optional keys that way.
_KEY_LINE = re.compile(r"^\s*#?\s*([A-Za-z]\w*(?:\.\w+)+)\s*=")

_EXAMPLES = """Examples:
  set_template_options.py $TE/GalapagosSenD128.template mintpy.troposphericDelay.method no
  set_template_options.py $TE/GalapagosSenD128.template topsStack.subswath '1 2' miaplpy.interferograms.networkType delaunay
  set_template_options.py --check mintpy.networkInversion.minTempCoh topsStack.azimuthLooks
"""


def family_of(key: str) -> str:
    """Prefix before the first dot (mintpy, topsStack, ...)."""
    return key.split(".", 1)[0]


def _keys_in(path: Path, family: str) -> set[str]:
    keys = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _KEY_LINE.match(line)
        if match and family_of(match.group(1)) == family:
            keys.add(match.group(1))
    return keys


def _package_defaults(package: str) -> Path | None:
    """Defaults cfg of the installed MintPy or MiaplPy, or None when the package is not installed."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.origin:
        return None
    path = Path(spec.origin).parent / "defaults" / _PACKAGE_KEY_FILES[package]
    return path if path.is_file() else None


def valid_keys(family: str) -> set[str] | None:
    """Known keys of a family. None when the list is not available (MintPy or MiaplPy not installed)."""
    keys: set[str] = set()
    if family in _PACKAGE_KEY_FILES:
        path = _package_defaults(family)
        if path is None:
            return None
        keys |= _keys_in(path, family)
    for name in _MINSAR_KEY_FILES:
        keys |= _keys_in(_DEFAULTS_DIR / name, family)
    return keys


def check_keys(keys) -> None:
    """Raise ValueError for the first key that is not a known template option."""
    cache: dict[str, set[str] | None] = {}
    for key in keys:
        family = family_of(key)
        if family not in FAMILIES:
            raise ValueError(f"unknown template option {key} (prefixes: {', '.join(FAMILIES)})")
        if family not in cache:
            cache[family] = valid_keys(family)
        known = cache[family]
        if known is None or key in known:
            continue
        close = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.6)
        hint = f" (closest: {close[0]})" if close else ""
        raise ValueError(f"unknown template option {key}{hint}")


def set_option(text: str, key: str, value: str) -> str:
    """Replace the value on the last uncommented 'key = value' line and keep its comment. Append when missing."""
    pattern = re.compile(rf"^([ \t]*{re.escape(key)}[ \t]*=[ \t]*)([^#\n]*?)([ \t]*(?:#.*)?)$", re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + f"{key} = {value}\n"
    last = matches[-1]
    return text[:last.start()] + last.group(1) + value + last.group(3) + text[last.end():]


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write template options into a template file. Keys must be known mintpy, miaplpy, minsar, topsStack, stripmapStack or alos2Stack options.", epilog=_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("template", metavar="TEMPLATE", nargs="?", help="template file to edit (omit with --check)")
    parser.add_argument("pairs", metavar="KEY VALUE", nargs="*", help="template key followed by its value (with --check: keys only)")
    parser.add_argument("--check", action="store_true", help="only check the key names; nothing is written")
    return parser


def main(iargs=None) -> int:
    args = create_parser().parse_args(iargs)
    try:
        if args.check:
            check_keys([token for token in [args.template, *args.pairs] if token])
            return 0
        if not args.template or not args.pairs or len(args.pairs) % 2:
            raise ValueError("expected TEMPLATE followed by KEY VALUE pairs")
        pairs = list(zip(args.pairs[0::2], args.pairs[1::2]))
        check_keys([key for key, _ in pairs])
        path = Path(args.template)
        text = path.read_text(encoding="utf-8")
        for key, value in pairs:
            text = set_option(text, key, value)
        path.write_text(text, encoding="utf-8")
    except (ValueError, OSError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
