"""Create multinode SLURM jobfiles for ISCE3 task-list stages via job_submission."""

from __future__ import annotations

import argparse
import glob
import os
import re
from pathlib import Path

CREATE_CSLC_QUEUE_META = ".isce3_create_cslc_queue"
DEFERRED_TASK_LIST_STAGES = frozenset({"create_cslc"})


def _require_job_env() -> None:
    missing = [
        name
        for name in ("JOBSHEDULER_PROJECTNAME", "JOBSCHEDULER", "PLATFORM_NAME", "MINSAR_HOME")
        if not os.getenv(name)
    ]
    if missing:
        raise RuntimeError(
            "MinSAR job environment incomplete (missing "
            + ", ".join(missing)
            + "); source setup/environment.bash before creating job files"
        )
    if not os.getenv("ISCE_STACK"):
        os.environ["ISCE_STACK"] = str(Path(os.environ["MINSAR_HOME"]) / "tools" / "isce2" / "contrib" / "stack")


def _find_template(work_dir: Path) -> str:
    """Return a *.template path in the project dir or its parent."""
    for pattern in (str(work_dir / "*.template"), str(work_dir.parent / "*.template")):
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"No *.template found in {work_dir} or {work_dir.parent}")


def read_create_cslc_queue(work_dir: Path) -> str | None:
    """Queue for create_cslc from run_files metadata or QUEUENAME."""
    meta = work_dir / "run_files" / CREATE_CSLC_QUEUE_META
    if meta.is_file():
        value = meta.read_text().strip()
        if value:
            return value
    env_queue = os.getenv("QUEUENAME")
    return env_queue.strip() if env_queue else None


def is_deferred_batch_job(path: Path, deferred_names: set[str] | None = None) -> bool:
    """True when path is run_NN_<stage>_N.job for a deferred task-list stage."""
    if path.suffix != ".job":
        return False
    names = deferred_names if deferred_names is not None else DEFERRED_TASK_LIST_STAGES
    match = re.match(r"run_\d{2}_(.+)_\d+$", path.stem)
    return bool(match and match.group(1) in names)


def write_create_cslc_batch_job(
    work_dir: Path,
    batch_file: Path,
    queue: str | None = None,
) -> list[str]:
    """Write run_*_create_cslc_N.job using JOB_SUBMISSION_SCHEME and the task list."""
    _require_job_env()
    from minsar.job_submission import JOB_SUBMIT

    resolved_queue = queue or read_create_cslc_queue(work_dir)
    if not resolved_queue:
        raise RuntimeError("No queue: set QUEUENAME or run create_isce3_runfiles with --queue")

    run_dir = work_dir / "run_files"
    batch_file = batch_file.resolve()
    if not batch_file.is_file():
        raise FileNotFoundError(f"create_cslc task list not found: {batch_file}")
    tasks = [line for line in batch_file.read_text().splitlines() if line.strip()]
    if not tasks:
        raise RuntimeError(f"create_cslc task list is empty: {batch_file}")

    legacy_job = batch_file.with_suffix(".job")
    if legacy_job.is_file():
        legacy_job.unlink()

    inps = argparse.Namespace(
        queue=resolved_queue,
        work_dir=str(work_dir.resolve()),
        out_dir=str(run_dir.resolve()),
        num_data=1,
        custom_template_file=_find_template(work_dir),
    )
    job = JOB_SUBMIT(inps)
    job.write_batch_jobs(batch_file=str(batch_file))
    print(f"Created: {', '.join(os.path.basename(path) for path in job.job_files)}")
    return job.job_files
