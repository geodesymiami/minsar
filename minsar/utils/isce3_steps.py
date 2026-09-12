"""ISCE3 workflow step names, aliases, and generation range resolution."""

from __future__ import annotations

import re
from typing import Iterable

DOLPHIN_SCIENCE_STAGES = frozenset({
    "dolphin",
    "dolphin_wrapped",
    "dolphin_unwrap",
    "dolphin_timeseries",
    "disp_s1_process",
})

DOWNLOAD_STAGES = frozenset({
    "download_safe",
    "download_cslc",
    "download_disp",
    "create_cslc",
})

POST_PRODUCT_STAGES = frozenset({
    "dolphin_2_hdfeos5",
    "ingest_insarmaps",
})

STEP_ALIASES = {
    "download_create_cslc": "download",
    "hdfeos5": "dolphin_2_hdfeos5",
    "dolphin2hdfeos5": "dolphin_2_hdfeos5",
    "ingest": "ingest_insarmaps",
}


def normalize_step(step: str) -> str:
    """Normalize a workflow step name (run file stem, alias, or numeric index string)."""
    value = str(step).strip()
    if not value:
        return value
    if value.endswith(".job"):
        value = value[: -len(".job")]
    match = re.match(r"^run_\d{2}_(.+)$", value)
    if match:
        value = match.group(1)
    value = value.replace("-", "_")
    return STEP_ALIASES.get(value, value)


def workflow_stage_names(
    workflow: str,
    dolphin_mode: str = "single-run",
    *,
    split_dolphin: bool = True,
) -> tuple[str, ...]:
    """Ordered stage names for a workflow (matches create_isce3_runfiles._build_stage_specs)."""
    mode = (dolphin_mode or "single-run").strip().lower().replace("_", "-")
    if workflow == "safe":
        if mode == "opera":
            return (
                "download_safe",
                "create_cslc",
                "disp_s1_process",
                "reformat_disp",
                "dolphin_2_hdfeos5",
                "ingest_insarmaps",
            )
        dolphin = (
            ("dolphin_wrapped", "dolphin_unwrap", "dolphin_timeseries")
            if split_dolphin
            else ("dolphin",)
        )
        return (
            "download_safe",
            "create_cslc",
            *dolphin,
            "dolphin_2_hdfeos5",
            "ingest_insarmaps",
        )
    if workflow == "cslc":
        if mode == "opera":
            return (
                "download_cslc",
                "disp_s1_process",
                "reformat_disp",
                "dolphin_2_hdfeos5",
                "ingest_insarmaps",
            )
        dolphin = (
            ("dolphin_wrapped", "dolphin_unwrap", "dolphin_timeseries")
            if split_dolphin
            else ("dolphin",)
        )
        return (
            "download_cslc",
            *dolphin,
            "dolphin_2_hdfeos5",
            "ingest_insarmaps",
        )
    return (
        "download_disp",
        "reformat_disp",
        "dolphin_2_hdfeos5",
        "ingest_insarmaps",
    )


def _first_existing(name: str, available: tuple[str, ...]) -> str | None:
    if name in available:
        return name
    return None


def expand_step_alias(step: str, which: str, available: tuple[str, ...]) -> str:
    """Expand coarse aliases the same way run_isce3_workflow.bash does."""
    value = normalize_step(step)
    if value == "download":
        if which == "end":
            if "download_disp" in available:
                return (
                    _first_existing("reformat_disp", available)
                    or _first_existing("download_disp", available)
                    or value
                )
            return (
                _first_existing("create_cslc", available)
                or _first_existing("download_safe", available)
                or _first_existing("download_cslc", available)
                or value
            )
        return (
            _first_existing("download_safe", available)
            or _first_existing("download_cslc", available)
            or _first_existing("download_disp", available)
            or value
        )
    if value == "dolphin":
        if which == "end":
            for candidate in (
                "dolphin_timeseries",
                "reformat_disp",
                "disp_s1_process",
                "dolphin",
                "dolphin_unwrap",
                "dolphin_wrapped",
            ):
                hit = _first_existing(candidate, available)
                if hit:
                    return hit
            return value
        for candidate in ("dolphin_wrapped", "disp_s1_process", "dolphin"):
            hit = _first_existing(candidate, available)
            if hit:
                return hit
        return value
    return value


def _resolve_index(step: str, available: tuple[str, ...]) -> int:
    value = expand_step_alias(step, "start", available)
    normalized = normalize_step(value)
    if normalized.isdigit():
        index = int(normalized)
        if 0 <= index < len(available):
            return index
        raise ValueError(f"unknown step index: {step}")
    for index, name in enumerate(available):
        if normalized == name:
            return index
    raise ValueError(f"unknown step: {step}")


def resolve_stage_range(
    available: tuple[str, ...],
    *,
    dostep: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> tuple[int, int]:
    """Return inclusive start/end indices into available for the requested range."""
    if dostep and (start or end):
        raise ValueError("--dostep cannot be combined with --start or --end")
    if dostep:
        token = normalize_step(dostep)
        if token in {"download", "dolphin"}:
            start = _resolve_index(expand_step_alias(token, "start", available), available)
            end = _resolve_index(expand_step_alias(token, "end", available), available)
            return start, end
        index = _resolve_index(token, available)
        return index, index
    start_index = 0
    end_index = len(available) - 1
    if start:
        start_index = _resolve_index(start, available)
    if end:
        end_index = _resolve_index(end, available)
    if start_index > end_index:
        raise ValueError("--start follows --end")
    return start_index, end_index


def selected_stage_names(
    workflow: str,
    dolphin_mode: str = "single-run",
    *,
    split_dolphin: bool = True,
    dostep: str | None = None,
    start: str | None = None,
    end: str | None = None,
    phase: str | None = None,
) -> frozenset[str]:
    """Stages whose run files should be written."""
    available = workflow_stage_names(workflow, dolphin_mode, split_dolphin=split_dolphin)
    if dostep or start or end:
        start_index, end_index = resolve_stage_range(
            available,
            dostep=dostep,
            start=start,
            end=end,
        )
        return frozenset(available[start_index : end_index + 1])
    token = (phase or "all").strip().lower().replace("-", "_")
    if token in {"download_create_cslc", "download"}:
        return frozenset(name for name in available if name in _download_stages(workflow))
    if token == "post":
        return frozenset(_post_stage_names(workflow, dolphin_mode))
    if token == "dolphin":
        download = _download_stages(workflow)
        return frozenset(name for name in available if name not in download)
    return frozenset(available)


def _download_stages(workflow: str) -> frozenset[str]:
    if workflow == "safe":
        return frozenset({"download_safe", "create_cslc"})
    if workflow == "cslc":
        return frozenset({"download_cslc"})
    return frozenset({"download_disp", "reformat_disp"})


def _post_stage_names(workflow: str, dolphin_mode: str) -> tuple[str, ...]:
    mode = (dolphin_mode or "single-run").strip().lower().replace("_", "-")
    if workflow in {"cslc", "safe"} and mode == "opera":
        return ("reformat_disp", "dolphin_2_hdfeos5", "ingest_insarmaps")
    return ("dolphin_2_hdfeos5", "ingest_insarmaps")


def needs_slc(stages: Iterable[str]) -> bool:
    """True when generation touches Dolphin YAML from on-disk SLCs/GSLCs."""
    return bool(frozenset(stages) & DOLPHIN_SCIENCE_STAGES)


def needs_sweets_config(stages: Iterable[str], workflow: str) -> bool:
    """True when sweets_config.yaml must be written."""
    if workflow not in {"safe", "cslc"}:
        return False
    selected = frozenset(stages)
    return bool(selected & _download_stages(workflow))


def post_only_selection(stages: Iterable[str], workflow: str, dolphin_mode: str) -> bool:
    """True when every selected stage is he5/ingest (and opera reformat_disp)."""
    selected = frozenset(stages)
    if not selected:
        return False
    allowed = frozenset(_post_stage_names(workflow, dolphin_mode))
    return selected.issubset(allowed)


def download_only_selection(stages: Iterable[str], workflow: str) -> bool:
    selected = frozenset(stages)
    if not selected:
        return False
    return selected.issubset(_download_stages(workflow))


def generation_needs_dolphin_science(stages: Iterable[str]) -> bool:
    return bool(frozenset(stages) & DOLPHIN_SCIENCE_STAGES)


def generation_needs_reformat_disp(stages: Iterable[str]) -> bool:
    return "reformat_disp" in frozenset(stages)


_DOLPHIN_SCIENCE_ARGV = frozenset({
    "--half-window",
    "--half-window-preset",
    "--stride",
    "--unwrap-method",
    "--ministack-size",
    "--dolphin-dir",
    "--from-dolphin-dir",
    "--no-dolphin-split",
})

_DATASET_ARGV = frozenset({
    "--data-type",
    "--safe",
    "--cslc",
    "--disp-S1",
    "--dolphin-mode",
})


def _workflow_key(data_type: str) -> str:
    token = data_type.strip().lower().replace("_", "-")
    if token in {"disp", "disp-s1"}:
        return "disp"
    return token or "safe"


def _argv_consumed(token: str) -> int:
    if token in {"--half-window", "--stride"}:
        return 3
    if token in {
        "--data-type",
        "--dolphin-mode",
        "--dolphin-dir",
        "--from-dolphin-dir",
        "--unwrap-method",
        "--ministack-size",
        "--half-window-preset",
        "--reference-method",
    }:
        return 2
    if token.startswith("--") and "." in token:
        return 2
    return 1


def _skip_argv_flag(token: str) -> bool:
    if token in _DOLPHIN_SCIENCE_ARGV:
        return True
    return token.startswith("--") and "." in token


def filter_generator_argv(
    argv: list[str],
    *,
    data_type: str,
    dolphin_mode: str = "single-run",
    split_dolphin: bool = True,
    dostep: str | None = None,
    start: str | None = None,
    end: str | None = None,
    explicit_data_type: bool = False,
    explicit_dolphin_mode: bool = False,
) -> list[str]:
    """Drop generator flags that do not apply to the requested step range."""
    workflow = _workflow_key(data_type)
    selected = selected_stage_names(
        workflow,
        dolphin_mode,
        split_dolphin=split_dolphin,
        dostep=normalize_step(dostep) if dostep else None,
        start=normalize_step(start) if start else None,
        end=normalize_step(end) if end else None,
        phase=None if (dostep or start or end) else "all",
    )
    need_science = generation_needs_dolphin_science(selected)
    need_reformat = generation_needs_reformat_disp(selected)
    out: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        advance = _argv_consumed(token)
        if token == "--data-type" and not explicit_data_type:
            index += advance
            continue
        if token in {"--safe", "--cslc", "--disp-S1"} and not explicit_data_type:
            index += advance
            continue
        if token == "--dolphin-mode" and not explicit_dolphin_mode:
            index += advance
            continue
        if token == "--reference-method" and not need_reformat:
            index += advance
            continue
        if not need_science and _skip_argv_flag(token):
            index += advance
            continue
        out.extend(argv[index : index + advance])
        index += advance
    return out
