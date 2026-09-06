#!/usr/bin/env python3
"""Dolphin experiment directory naming, YAML names, and layer-aware input staging."""

from __future__ import annotations

import re
from pathlib import Path

DOLPHIN_DIR_SIDECAR = ".isce3_dolphin_dir"
RUN_SLICE_SIDECAR = ".isce3_run_slice"
DEFAULT_DOLPHIN_DIR = "dolphin"
DEFAULT_FROM_DIR = "dolphin"
UNWRAP_TOKEN_ORDER = ("whirlwind", "goldstein", "interp")

WORKER_KEY_PARTS = (
    "n-parallel-jobs",
    "n_parallel_jobs",
    "threads-per-worker",
    "threads_per_worker",
    "n-parallel-bursts",
    "n_parallel_bursts",
    "num-parallel-blocks",
    "num_parallel_blocks",
    "block-shape",
    "block_shape",
)

TOKEN_BOOL_ON = {
    "unwrap-options.run-interpolation": "interp",
    "unwrap-options.run-goldstein": "goldstein",
}
TOKEN_TEMPLATES = {
    "unwrap-options.unwrap-method": "{value}",
    "phase-linking.ministack-size": "ms{value}",
    "timeseries-options.correlation-threshold": "corr{value}",
    "ps-options.amp-dispersion-threshold": "ampdisp{value}",
    "preset": "{value}",
}
TOKEN_BOOL_OFF = {
    "timeseries-options.apply-mask-to-timeseries": "nomaskts",
}

LAYER_ORDER = ("wrapped", "unwrap", "timeseries")


def config_yaml_name(dolphin_dir: str) -> str:
    """Return project-root YAML name for a Dolphin work directory."""
    stem = str(dolphin_dir).strip().strip("/")
    if not stem or "/" in stem or stem in {".", ".."}:
        raise ValueError(f"invalid --dolphin-dir {dolphin_dir!r}; use a single directory name")
    if stem == DEFAULT_DOLPHIN_DIR:
        return "dolphin_config.yaml"
    return f"{stem}_config.yaml"


def write_dolphin_dir_sidecar(work_dir: Path, dolphin_dir: str) -> None:
    """Record the active Dolphin directory for validation and later app runs."""
    path = Path(work_dir) / DOLPHIN_DIR_SIDECAR
    path.write_text(str(dolphin_dir).strip() + "\n", encoding="utf-8")


def write_run_slice_sidecar(
    work_dir: Path,
    *,
    dolphin_dir: str,
    layer: str,
    phase: str,
    yaml_name: str,
    dolphin_mode: str = "standard",
) -> None:
    """Record resolved DIR/layer so minsarIsce3App.bash can choose workflow --start."""
    path = Path(work_dir) / RUN_SLICE_SIDECAR
    path.write_text(
        f"dolphin_dir={dolphin_dir}\nlayer={layer}\nphase={phase}\nyaml={yaml_name}\ndolphin_mode={dolphin_mode}\n",
        encoding="utf-8",
    )


def read_run_slice_sidecar(work_dir: Path) -> dict[str, str]:
    """Return key=value pairs from .isce3_run_slice, or empty."""
    path = Path(work_dir) / RUN_SLICE_SIDECAR
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def read_dolphin_dir_sidecar(work_dir: Path) -> str:
    """Return the active Dolphin directory, or dolphin if unset."""
    path = Path(work_dir) / DOLPHIN_DIR_SIDECAR
    if not path.is_file():
        return DEFAULT_DOLPHIN_DIR
    text = path.read_text(encoding="utf-8").strip()
    return text or DEFAULT_DOLPHIN_DIR


def _norm_key(flag: str) -> str:
    token = flag.lstrip("-").replace("_", "-")
    if token.startswith("no-"):
        token = token[3:]
    return token.lower()


def _is_worker_key(key: str) -> bool:
    return any(part in key for part in WORKER_KEY_PARTS)


def parse_passthrough_pairs(tokens: list[str]) -> list[tuple[str, str | None]]:
    """Turn leftover argv into (dotted-key, value-or-None) pairs."""
    pairs: list[tuple[str, str | None]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--work-directory", "--work-dir"} or token.startswith("--work-directory="):
            raise ValueError("use --dolphin-dir, not --work-directory")
        if not token.startswith("--"):
            raise ValueError(f"unexpected dolphin config argument: {token}")
        if "=" in token:
            flag, value = token.split("=", 1)
            pairs.append((_norm_key(flag), value))
            index += 1
            continue
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if nxt is None or nxt.startswith("--"):
            pairs.append((_norm_key(token), None))
            index += 1
            continue
        pairs.append((_norm_key(token), nxt))
        index += 2
    return pairs


def _compact_value(value: str) -> str:
    text = str(value).strip().replace(".", "p")
    return re.sub(r"[^A-Za-z0-9]+", "", text)


def _token_for_pair(key: str, value: str | None) -> str | None:
    if _is_worker_key(key):
        return None
    val = None if value is None else str(value).strip().lower()
    if key in TOKEN_BOOL_ON and val in {None, "true", "1", "yes"}:
        return TOKEN_BOOL_ON[key]
    if key in TOKEN_BOOL_OFF and val in {"false", "0", "no"}:
        return TOKEN_BOOL_OFF[key]
    if key in TOKEN_TEMPLATES:
        if val in {None, ""}:
            return None
        rendered = TOKEN_TEMPLATES[key].format(value=_compact_value(value or ""))
        return rendered
    last = key.split(".")[-1]
    if val in {None, "true", "1", "yes"}:
        return last.replace("-", "")
    if val in {"false", "0", "no"}:
        return "no" + last.replace("-", "")
    return last.replace("-", "") + _compact_value(value or "")


def layer_for_key(key: str) -> str | None:
    """Return wrapped, unwrap, or timeseries for a science key; None if worker/ignored."""
    if _is_worker_key(key):
        return None
    if key in {"mask-file", "sy", "sx"} or key.startswith("output-options.strides"):
        return "wrapped"
    if key.startswith("phase-linking") or key.startswith("ps-options") or key.startswith("interferogram-network"):
        return "wrapped"
    if key.startswith("unwrap-options"):
        return "unwrap"
    if key.startswith("timeseries-options"):
        return "timeseries"
    if key.startswith("output-options"):
        return "wrapped"
    return "wrapped"


def earliest_layer(pairs: list[tuple[str, str | None]]) -> str:
    """Earliest pipeline layer among science overrides (default wrapped)."""
    layers = [layer_for_key(key) for key, _ in pairs]
    present = [layer for layer in layers if layer]
    for layer in LAYER_ORDER:
        if layer in present:
            return layer
    return "wrapped"


def auto_dolphin_dir(pairs: list[tuple[str, str | None]]) -> str | None:
    """Directory name from science diffs, or None when there is no naming signal."""
    tokens: list[str] = []
    seen: set[str] = set()
    ordered: list[tuple[str, str, str | None]] = []
    for key, value in pairs:
        layer = layer_for_key(key)
        if layer is None:
            continue
        token = _token_for_pair(key, value)
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append((layer, token, value))
    rank = {name: index for index, name in enumerate(LAYER_ORDER)}
    unwrap_rank = {name: index for index, name in enumerate(UNWRAP_TOKEN_ORDER)}
    ordered.sort(key=lambda item: (rank.get(item[0], 9), unwrap_rank.get(item[1], 99), item[1]))
    tokens = [item[1] for item in ordered]
    if not tokens:
        return None
    return DEFAULT_DOLPHIN_DIR + "_" + "_".join(tokens)


def _yaml_lookup(data: object, key: str) -> object:
    node: object = data
    for part in key.replace("-", "_").split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _values_equal(left: object, right: str | None) -> bool:
    if right is None:
        return bool(left) is True or left in {True, "true", "True"}
    if isinstance(left, bool):
        return str(left).lower() == right.strip().lower()
    if left is None:
        return right.strip().lower() in {"none", "null", ""}
    return str(left).strip().lower() == right.strip().lower()


def differing_pairs(pairs: list[tuple[str, str | None]], source_yaml: Path | None) -> list[tuple[str, str | None]]:
    """Pairs that differ from source YAML (all pairs if YAML is missing)."""
    if source_yaml is None or not Path(source_yaml).is_file():
        return [(key, value) for key, value in pairs if layer_for_key(key)]
    try:
        import yaml
    except ImportError:
        return [(key, value) for key, value in pairs if layer_for_key(key)]
    data = yaml.safe_load(Path(source_yaml).read_text(encoding="utf-8")) or {}
    out: list[tuple[str, str | None]] = []
    for key, value in pairs:
        if layer_for_key(key) is None:
            continue
        current = _yaml_lookup(data, key)
        if not _values_equal(current, value):
            out.append((key, value))
    return out


def resolve_dolphin_dir(
    *,
    explicit_dir: str | None,
    passthrough: list[str],
    from_dir: str,
    work_dir: Path,
    extra_pairs: list[tuple[str, str | None]] | None = None,
) -> tuple[str, list[tuple[str, str | None]], str]:
    """Return (dir, science pairs, layer). explicit_dir wins over auto-name."""
    pairs = list(extra_pairs or [])
    pairs.extend(parse_passthrough_pairs(passthrough))
    source = str(from_dir or DEFAULT_FROM_DIR).strip().strip("/") or DEFAULT_FROM_DIR
    source_yaml = Path(work_dir) / config_yaml_name(source)
    diffs = differing_pairs(pairs, source_yaml)
    layer = earliest_layer(diffs) if diffs else "wrapped"
    if explicit_dir:
        return str(explicit_dir).strip().strip("/"), diffs, layer
    if not diffs:
        return source, diffs, layer
    auto = auto_dolphin_dir(diffs)
    return auto or DEFAULT_DOLPHIN_DIR, diffs, layer


def stage_dolphin_inputs(
    work_dir: Path,
    *,
    src_dir: str,
    dst_dir: str,
    layer: str,
    copy: bool = False,
) -> None:
    """Symlink (or copy) interferograms/unwrapped from src into dst for unwrap/timeseries reruns."""
    if src_dir == dst_dir or layer == "wrapped":
        return
    names = ["interferograms"]
    if layer == "timeseries":
        names.append("unwrapped")
    src_root = Path(work_dir) / src_dir
    dst_root = Path(work_dir) / dst_dir
    dst_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = src_root / name
        dst = dst_root / name
        if not src.exists():
            raise FileNotFoundError(
                f"missing {src} (run wrapped/unwrap in {src_dir} first, or pass --from-dolphin-dir)"
            )
        if dst.exists() or dst.is_symlink():
            continue
        if copy:
            import shutil

            shutil.copytree(src, dst, symlinks=True)
        else:
            dst.symlink_to(src.resolve(), target_is_directory=src.is_dir())


def has_cslc_or_gslc(work_dir: Path, workflow: str) -> bool:
    """True when Dolphin inputs exist for --phase dolphin."""
    root = Path(work_dir)
    if workflow == "safe":
        return any(path.name.startswith("t") and path.suffix == ".h5" for path in root.glob("gslcs/**/*.h5"))
    if workflow == "cslc":
        return any(root.glob("data/*CSLC*.h5")) or any(root.glob("data/OPERA_L2_CSLC-S1_*.h5"))
    return True


def passthrough_cli_flags(tokens: list[str]) -> str:
    """Shell-quoted leftover dolphin config flags."""
    import shlex

    out: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if (
            nxt is not None
            and not nxt.startswith("--")
            and _norm_key(token) in TOKEN_BOOL_ON
            and nxt.strip().lower() in {"true", "1", "yes"}
        ):
            out.append(token)
            index += 2
            continue
        out.append(token)
        index += 1
    return " ".join(shlex.quote(token) for token in out)
