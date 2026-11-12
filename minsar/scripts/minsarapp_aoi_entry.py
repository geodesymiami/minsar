#!/usr/bin/env python3
"""AOI bridge for `minsarApp.bash`: run `create_template`, then re-exec minsar on the primary template.

User-facing: ``minsarApp.bash <AOI> <NAME> [ create_template and minsarApp options in any order ]``

When ``create_template`` ends in dual-pass mode (``asc,desc`` default; also ``desc,asc``,
legacy ``both``, or comma-separated values with spaces), the re-exec appends ``--opposite-orbit``
to ``minsarApp`` so the complementary pass runs after the primary pass (unless the remainder
already has ``--opposite-orbit`` or ``--no-opposite-orbit``). If the AOI has coverage for only
ascending or only descending, ``create_template`` falls back to a single template (see its Note on
stderr) and the bridge uses effective ``asc`` / ``desc`` so ``--opposite-orbit`` is not appended.

For a **single** direction (``asc`` or ``desc``) together with ``--opposite-orbit`` in
the minsarApp tail, template creation is expanded to ``asc,desc`` or ``desc,asc`` so
both templates exist before the nested run (equivalent to listing both directions in
``--flight-dir``).

``create_template`` and ``minsarApp`` options may be mixed after ``NAME``. Each option is
sent to the command that accepts it. ``--exclude-dates`` and ``--minsar.excludeDates`` are
copied to both. ``create_template.py --help`` lists the template options.

``MINSAR_APP_BASH`` must be set to the path of ``minsarApp.bash`` (set by the shell before
``exec``). ``TEMPLATES`` (or ``TE``) is the output directory (same as for template-first runs).
``--template-dir DIR`` writes the template and the AOI log in DIR instead, and is removed
before ``create_template`` and the minsarApp re-exec.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path


def _repo_root() -> Path:
    m = os.environ.get("MINSAR_HOME")
    if m:
        return Path(m).resolve()
    return Path(__file__).resolve().parent.parent.parent


def _ensure_path() -> None:
    r = str(_repo_root())
    if r not in sys.path:
        sys.path.insert(0, r)


def pop_template_dir(argv: list[str]) -> tuple[list[str], Path | None]:
    """Remove ``--template-dir DIR`` from *argv*. Return the remaining argv and the directory."""
    out: list[str] = []
    dest: Path | None = None
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--template-dir":
            if i + 1 >= len(argv) or str(argv[i + 1]).startswith("-"):
                print(
                    "minsarapp_aoi_entry: --template-dir requires a directory",
                    file=sys.stderr,
                )
                sys.exit(1)
            dest = Path(argv[i + 1]).expanduser()
            i += 2
            continue
        if tok.startswith("--template-dir="):
            val = tok.split("=", 1)[1]
            if not val:
                print(
                    "minsarapp_aoi_entry: --template-dir requires a directory",
                    file=sys.stderr,
                )
                sys.exit(1)
            dest = Path(val).expanduser()
            i += 1
            continue
        out.append(tok)
        i += 1
    return out, dest


def _templates_dir() -> Path:
    t = os.environ.get("TEMPLATES") or os.environ.get("TE")
    if not t:
        print(
            "minsarapp_aoi_entry: TEMPLATES or TE must be set in the environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    return Path(t).resolve()


def expand_flight_dir_for_dual_templates(flight_dir: str, rest: list[str]) -> str:
    """If user asked for one orbit plus ``--opposite-orbit``, return dual-pass flight_dir for create_template."""
    if "--no-opposite-orbit" in rest or "--opposite-orbit" not in rest:
        return flight_dir
    if flight_dir == "asc":
        return "asc,desc"
    if flight_dir == "desc":
        return "desc,asc"
    return flight_dir


def apply_flight_dir_to_ct_list(ct_list: list[str], new_flight_dir: str) -> list[str]:
    """Replace ``--flight-dir`` value in *ct_list* with *new_flight_dir* (two-token or ``=`` form)."""
    out = list(ct_list)
    i = 0
    while i < len(out):
        tok = out[i]
        if tok == "--flight-dir" and i + 1 < len(out):
            out[i + 1] = new_flight_dir
            return out
        if tok.startswith("--flight-dir="):
            out[i] = f"--flight-dir={new_flight_dir}"
            return out
        i += 1
    return out


def minsarapp_args_after_primary(
    primary_s: str, flight_dir: str, rest: list[str]
) -> list[str]:
    """Build ``[ template_path, ...flags ]`` for re-exec of ``minsarApp.bash``.

    When *flight_dir* requests dual-pass output, insert ``--opposite-orbit`` (same effect as
    ``opposite_orbit_flag=1`` in ``minsarApp.bash``) if the user has not set
    ``--opposite-orbit`` or ``--no-opposite-orbit`` in *rest*.
    """
    out: list[str] = [primary_s]
    if (
        flight_dir in ("both", "asc,desc", "desc,asc")
        and "--no-opposite-orbit" not in rest
        and "--opposite-orbit" not in rest
    ):
        out.append("--opposite-orbit")
    out.extend(rest)
    return out


_NUMERIC_TOKEN = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def _option_name(token: str) -> str:
    if token.startswith("--") and "=" in token:
        return token.split("=", 1)[0]
    return token


def _option_kind(name: str, kw: dict[str, tuple[str, ...]]) -> str | None:
    if name in kw.get("flags", ()):
        return "flag"
    if name in kw.get("optional_numeric", ()):
        return "num"
    if name in kw.get("optional_unless_dash", ()):
        return "opt"
    if name in kw.get("consume_two", ()):
        return "two"
    if name in kw.get("consume_one", ()):
        return "one"
    return None


def _take_option_cluster(tokens: list[str], i: int, kind: str) -> tuple[list[str], int]:
    tok = tokens[i]
    if tok.startswith("--") and "=" in tok:
        return [tok], i + 1
    if kind == "flag":
        return [tok], i + 1
    if kind == "one":
        if i + 1 >= len(tokens):
            print(f"minsarapp_aoi_entry: {tok} requires a value", file=sys.stderr)
            sys.exit(1)
        return tokens[i : i + 2], i + 2
    if kind == "two":
        if i + 2 >= len(tokens):
            print(f"minsarapp_aoi_entry: {tok} requires two values", file=sys.stderr)
            sys.exit(1)
        return tokens[i : i + 3], i + 3
    if kind == "opt":
        if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
            return tokens[i : i + 2], i + 2
        return [tok], i + 1
    if kind == "num":
        if i + 1 < len(tokens) and _NUMERIC_TOKEN.match(tokens[i + 1]):
            return tokens[i : i + 2], i + 2
        return [tok], i + 1
    print(f"minsarapp_aoi_entry: cannot read option {tok}", file=sys.stderr)
    sys.exit(1)


def _positionals_and_options(fixed: list[str]) -> tuple[list[str], list[str]]:
    """Return (positionals, option tokens) after negative-bbox argv fixing.

    A leading negative AOI is moved behind ``--`` and still counts as the first positional.
    """
    if "--" not in fixed:
        pos: list[str] = []
        k = 0
        while k < len(fixed) and not str(fixed[k]).startswith("-"):
            pos.append(fixed[k])
            k += 1
        return pos, fixed[k:]
    sep = fixed.index("--")
    before, after = fixed[:sep], fixed[sep + 1 :]
    leading: list[str] = []
    b = 0
    while b < len(before) and not str(before[b]).startswith("-"):
        leading.append(before[b])
        b += 1
    options = before[b:]
    if leading:
        return leading, options + after
    if not after:
        return [], options
    pos = [after[0]]
    k = 1
    while k < len(after) and not str(after[k]).startswith("-"):
        pos.append(after[k])
        k += 1
    return pos, options + after[k:]


def partition_aoi_bridge_argv(
    fixed: list[str],
) -> tuple[list[str], list[str], object]:
    """Split fixed AOI argv into create_template args, minsarApp args, and the template namespace.

    *fixed* is argv after ``fix_argv_for_negative_bbox_sn_we`` with the union of both CLIs.
    """
    from minsar.scripts.create_template import create_parser
    from minsar.utils.bbox_cli_argv import (
        MINSAR_APP_ARGV_KW,
        SHARED_AOI_BRIDGE_OPTIONS,
        fix_argv_for_negative_bbox_sn_we,
        get_create_template_argv_kw,
    )

    pos, options = _positionals_and_options(fixed)
    if len(pos) < 2:
        print(
            "minsarapp_aoi_entry: need at least AOI and project name as the first two "
            "arguments.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(pos) > 2:
        print(
            f"minsarapp_aoi_entry: unexpected argument {pos[2]!r} in AOI mode",
            file=sys.stderr,
        )
        sys.exit(1)

    ct_kw = get_create_template_argv_kw()
    ct_list = list(pos)
    minsar_list: list[str] = []
    i, n = 0, len(options)
    while i < n:
        tok = options[i]
        if tok == "--":
            print(
                "minsarapp_aoi_entry: unexpected '--' in AOI mode",
                file=sys.stderr,
            )
            sys.exit(1)
        if not tok.startswith("-"):
            print(
                f"minsarapp_aoi_entry: unexpected argument {tok!r} in AOI mode",
                file=sys.stderr,
            )
            sys.exit(1)
        name = _option_name(tok)
        ct_kind = _option_kind(name, ct_kw)
        ma_kind = _option_kind(name, MINSAR_APP_ARGV_KW)
        shared = name in SHARED_AOI_BRIDGE_OPTIONS
        if ct_kind and ma_kind and not shared:
            print(
                f"minsarapp_aoi_entry: {name} is both a create_template and minsarApp option",
                file=sys.stderr,
            )
            sys.exit(1)
        if shared:
            kind = ct_kind or ma_kind
        elif ct_kind:
            kind = ct_kind
        elif ma_kind:
            kind = ma_kind
        else:
            print(
                f"minsarapp_aoi_entry: {name} is not a create_template or minsarApp "
                "option in AOI mode",
                file=sys.stderr,
            )
            sys.exit(1)
        if kind is None:
            print(f"minsarapp_aoi_entry: {name} requires a value", file=sys.stderr)
            sys.exit(1)
        cluster, i = _take_option_cluster(options, i, kind)
        if shared or ct_kind:
            ct_list.extend(cluster)
        if shared or ma_kind:
            minsar_list.extend(cluster)

    parser = create_parser(add_help=False)
    safe = fix_argv_for_negative_bbox_sn_we(
        ct_list,
        **ct_kw,
        multiple_initial_positionals=True,
    )
    try:
        ns = parser.parse_args(safe)
    except SystemExit as e:
        code = e.code
        if code is None:
            code = 0
        if isinstance(code, int):
            sys.exit(code)
        sys.exit(1)
    return ct_list, minsar_list, ns


def run() -> None:
    _ensure_path()
    from minsar.utils.bbox_cli_argv import (
        MINSAR_APP_ARGV_KW,
        fix_argv_for_negative_bbox_sn_we,
        get_create_template_argv_kw,
        union_argv_kw,
    )
    from minsar.scripts.create_template import main

    raw = sys.argv[1:]
    argv, template_dir = pop_template_dir(raw)
    fixed = fix_argv_for_negative_bbox_sn_we(
        list(argv),
        **union_argv_kw(get_create_template_argv_kw(), MINSAR_APP_ARGV_KW),
        multiple_initial_positionals=True,
    )
    if len(fixed) < 2:
        print(
            "minsarapp_aoi_entry: need at least AOI and project name as the first two "
            "arguments.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Log the original AOI invocation. --template-dir keeps this log out of $TE.
    if template_dir is not None:
        try:
            template_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(
                f"minsarapp_aoi_entry: cannot create {template_dir}: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)
        tdir = template_dir.resolve()
    else:
        tdir = _templates_dir()
    log_path = tdir / "log"
    timestamp = datetime.now().strftime("%Y%m%d:%H-%M")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("#############################################################################################\n")
        f.write(f"{timestamp} * minsarApp.bash {' '.join(raw)}\n")

    mapp = os.environ.get("MINSAR_APP_BASH")
    if not mapp or not Path(mapp).is_file():
        print(
            "minsarapp_aoi_entry: MINSAR_APP_BASH must be set to the path of minsarApp.bash",
            file=sys.stderr,
        )
        sys.exit(1)
    mapp = str(Path(mapp).resolve())
    ct_list, rest, _ns = partition_aoi_bridge_argv(fixed)
    try:
        os.chdir(tdir)
    except OSError as exc:
        print(
            f"minsarapp_aoi_entry: cannot chdir to {tdir}: {exc}", file=sys.stderr
        )
        sys.exit(1)
    efd = expand_flight_dir_for_dual_templates(_ns.flight_dir, list(rest))
    if efd != _ns.flight_dir:
        ct_list = apply_flight_dir_to_ct_list(ct_list, efd)
    code, primary, _opposite, flight_dir_eff = main(iargs=ct_list)
    if code != 0 or primary is None:
        sys.exit(int(code) if code else 1)
    primary_s = str(Path(primary).resolve())
    # Use effective flight direction (single-pass fallback when dual was requested).
    margs = minsarapp_args_after_primary(
        primary_s, flight_dir_eff, list(rest)
    )
    # After create_template: immutable pair for minsarApp.bash (read once, then unset).
    os.environ["MINSAR_FIRST_ORBIT_TEMPLATE_FILE"] = primary_s
    if _opposite is not None:
        os.environ["MINSAR_OPPOSITE_ORBIT_TEMPLATE"] = str(Path(_opposite).resolve())
    else:
        os.environ.pop("MINSAR_OPPOSITE_ORBIT_TEMPLATE", None)
    # Template-only re-exec; minsarApp reads this for footer (empty when user started with a *.template).
    os.environ["MINSAR_CLI_COMMAND_AOI"] = shlex.join([Path(mapp).name] + fixed)
    os.execv("/bin/bash", ["/bin/bash", mapp, *margs])


if __name__ == "__main__":
    run()
