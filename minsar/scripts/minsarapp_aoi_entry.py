#!/usr/bin/env python3
"""AOI bridge for `minsarApp.bash`: run `create_template`, then re-exec minsar on the primary template.

User-facing: ``minsarApp.bash <AOI> <NAME> [ create_template options ... ] [ minsar options ... ]``

Because argv is split with ``create_parser().parse_known_args()``, any *minsarApp-only*
option (e.g. ``--start``) and everything *after* the first such token is forwarded to
``minsarApp.bash`` unchanged. For predictable splitting, list all ``create_template`` options
before the first ``minsarApp`` option.

``MINSAR_APP_BASH`` must be set to the path of ``minsarApp.bash`` (set by the shell before
``exec``). ``TEMPLATES`` (or ``TE``) is the output directory (same as for template-first runs).
"""

from __future__ import annotations

import os
import sys
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
    tdir = _templates_dir()
    try:
        os.chdir(tdir)
    except OSError as exc:
        print(
            f"minsarapp_aoi_entry: cannot chdir to {tdir}: {exc}", file=sys.stderr
        )
        sys.exit(1)
    code, primary = main(iargs=ct_list)
    if code != 0 or primary is None:
        sys.exit(int(code) if code else 1)
    primary_s = str(Path(primary).resolve())
    if not rest:
        os.execv("/bin/bash", ["/bin/bash", mapp, primary_s])
    args = ["/bin/bash", mapp, primary_s, *rest]
    os.execv("/bin/bash", args)


if __name__ == "__main__":
    run()
