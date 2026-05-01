#!/usr/bin/env python3
"""AOI bridge for `minsarApp.bash`: run `create_template`, then re-exec minsar on the primary template.

User-facing: ``minsarApp.bash <AOI> <NAME> [ create_template options ... ] [ minsar options ... ]``

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

Because argv is split with ``create_parser().parse_known_args()``, any *minsarApp-only*
option (e.g. ``--start``) and everything *after* the first such token is forwarded to
``minsarApp.bash`` unchanged. For predictable splitting, list all ``create_template`` options
before the first ``minsarApp`` option.

``MINSAR_APP_BASH`` must be set to the path of ``minsarApp.bash`` (set by the shell before
``exec``). ``TEMPLATES`` (or ``TE``) is the output directory (same as for template-first runs).
"""

from __future__ import annotations

import os
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


def run() -> None:
    _ensure_path()
    from minsar.utils.bbox_cli_argv import (
        CREATE_TEMPLATE_ARGV_KW,
        fix_argv_for_negative_bbox_sn_we,
    )
    from minsar.scripts.create_template import create_parser, main

    argv = sys.argv[1:]
    fixed = fix_argv_for_negative_bbox_sn_we(
        list(argv),
        **CREATE_TEMPLATE_ARGV_KW,
        multiple_initial_positionals=True,
    )
    if len(fixed) < 2:
        print(
            "minsarapp_aoi_entry: need at least AOI and project name as the first two "
            "arguments.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Log original AOI invocation into $TEMPLATES/log using minsarApp-style format.
    # Keep the exact user-entered argv tokens (AOI + NAME form), only changing log location.
    tdir = _templates_dir()
    log_path = tdir / "log"
    timestamp = datetime.now().strftime("%Y%m%d:%H-%M")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("#############################################################################################\n")
        f.write(f"{timestamp} * minsarApp.bash {' '.join(argv)}\n")

    mapp = os.environ.get("MINSAR_APP_BASH")
    if not mapp or not Path(mapp).is_file():
        print(
            "minsarapp_aoi_entry: MINSAR_APP_BASH must be set to the path of minsarApp.bash",
            file=sys.stderr,
        )
        sys.exit(1)
    mapp = str(Path(mapp).resolve())
    try:
        parser = create_parser(add_help=False)
        _ns, rest = parser.parse_known_args(fixed)
    except SystemExit as e:
        code = e.code
        if code is None:
            code = 0
        if isinstance(code, int):
            sys.exit(code)
        sys.exit(1)
    n_rest = len(rest)
    if n_rest:
        ct_list = fixed[: len(fixed) - n_rest]
    else:
        ct_list = list(fixed)
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
