"""Set the number of looks in a MinSAR template (command-line options of minsarApp.bash and create_template.py).

The stack prefix follows asf.platform: alos2Stack for ALOS-2, else topsStack
(stripmapStack when the template has stripmapStack keys and no topsStack keys).
"""

import re

from minsar.utils.sar_platform import normalize_sar_platform_token

RANGE_OPTIONS = ("--rangeLooks", "--range-looks", "--topsStack.rangeLooks", "--alos2Stack.rangeLooks")
AZIMUTH_OPTIONS = ("--azimuthLooks", "--azimuth-looks", "--topsStack.azimuthLooks", "--alos2Stack.azimuthLooks")
ALOS2_SCANSAR_DEFAULT = {"rangeLooks": 5, "azimuthLooks": 28}   # ISCE default, looks 1 (1 x 14) x looks 2 (5 x 2)
ALOS2_AZIMUTH_LOOKS1 = 14


def add_looks_arguments(parser):
    """Add --rangeLooks / --azimuthLooks with all accepted spellings (dest range_looks, azimuth_looks)."""
    parser.add_argument(*RANGE_OPTIONS, dest="range_looks", type=int, default=None, metavar="N",
                        help="number of range looks (topsStack.rangeLooks or alos2Stack.rangeLooks)")
    parser.add_argument(*AZIMUTH_OPTIONS, dest="azimuth_looks", type=int, default=None, metavar="N",
                        help="number of azimuth looks (topsStack.azimuthLooks or alos2Stack.azimuthLooks; ALOS-2 ScanSAR: multiple of 14)")


def _active_value(text, key):
    """Value on the last uncommented 'key = value' line, or None."""
    matches = re.findall(rf"(?m)^\s*{re.escape(key)}\s*=\s*([^\s#]+)", text)
    return matches[-1] if matches else None


def stack_prefix(text):
    """Return alos2Stack, topsStack or stripmapStack for this template text."""
    platform = _active_value(text, "asf.platform")
    if platform and normalize_sar_platform_token(platform) == "ALOS2":
        return "alos2Stack"
    if re.search(r"(?m)^\s*stripmapStack\.", text) and not re.search(r"(?m)^\s*topsStack\.", text):
        return "stripmapStack"
    return "topsStack"


def check_option_spellings(argv, prefix):
    """Raise ValueError when a sensor-specific looks option does not match the template's stack."""
    for token in argv:
        name = token.split("=", 1)[0]
        if name in RANGE_OPTIONS + AZIMUTH_OPTIONS and "." in name and not name.startswith(f"--{prefix}."):
            raise ValueError(f"{name} does not apply: this template uses {prefix}")


def _set_assignment(text, key, value):
    """Replace the value on the last uncommented 'key = value' line and keep its comment. Append when missing."""
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)([^\s#]+)", re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        if text and not text.endswith("\n"):
            text += "\n"
        return text + f"{key} = {value}\n"
    last = matches[-1]
    return text[:last.start()] + last.group(1) + str(value) + text[last.end():]


def set_looks_in_template_text(text, range_looks=None, azimuth_looks=None):
    """Return (new text, {key: value} that was set). None leaves a value unchanged."""
    prefix = stack_prefix(text)
    looks = {"rangeLooks": range_looks, "azimuthLooks": azimuth_looks}
    for name, value in looks.items():
        if value is not None and int(value) < 1:
            raise ValueError(f"{prefix}.{name} must be 1 or larger, got {value}")
    if prefix == "alos2Stack" and any(value is not None for value in looks.values()):
        # stack_run._alos2_look_properties needs both numbers
        for name in looks:
            if looks[name] is None and str(_active_value(text, f"{prefix}.{name}")).lower() in ("auto", "none"):
                looks[name] = ALOS2_SCANSAR_DEFAULT[name]
        azimuth = looks["azimuthLooks"] if looks["azimuthLooks"] is not None else int(_active_value(text, f"{prefix}.azimuthLooks"))
        if int(azimuth) % ALOS2_AZIMUTH_LOOKS1:
            raise ValueError(f"alos2Stack.azimuthLooks must be a multiple of {ALOS2_AZIMUTH_LOOKS1} (ScanSAR), got {azimuth}")
    changed = {}
    for name, value in looks.items():
        if value is not None:
            key = f"{prefix}.{name}"
            text = _set_assignment(text, key, int(value))
            changed[key] = int(value)
    return text, changed
