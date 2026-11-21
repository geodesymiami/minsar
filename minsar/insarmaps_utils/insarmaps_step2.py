#!/usr/bin/env python3
"""Step 2 of an Insarmaps ingest, for the Python uploaders (sarvey2insarmaps.py and others): rsync the JSON folder that
step 1 wrote to the Insarmaps host, under /data/scratch, run json_mbtiles2insarmaps.py there over ssh against the
host's database (--host 127.0.0.1), then delete the remote copy. ingest_insarmaps.bash does the same in bash
(ingest_step2_rsync_and_remote_ingest)."""
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(command, cwd=None):
    """Run a command (a list of arguments) once, after printing it with paths under cwd made relative, and add it to
    ./ingest_commands.log."""
    cmd_parts = shlex.split(command) if isinstance(command, str) else list(command)
    command_line = " ".join(convert_to_relative_path(cmd_parts, cwd=cwd or os.getcwd()))
    _append_ingest_command_log(command_line)
    print(
        "##########################\n"
        "Running (displaying relative paths)....\n"
        f"{command_line}\n"
        "##########################\n"
    )
    subprocess.run(cmd_parts, check=True, cwd=str(cwd) if cwd else None)


def convert_to_relative_path(cmd_list, cwd=None):
    """
    Return a list where any element that lives under cwd is replaced by its relative path.
    """
    #make sure cwd is a string
    cwd = str(cwd or os.getcwd())
    rel = []
    for token in cmd_list:
        #only rewrite absolute paths under cwd
        if os.path.isabs(token) and token.startswith(cwd + os.sep):
            rel.append(os.path.relpath(token, cwd))
        else:
            rel.append(token)
    return rel


def insarmaps_host_list(host_arg):
    """Split a comma-separated Insarmaps host list; drop empty tokens."""
    if host_arg is None or not str(host_arg).strip():
        raise RuntimeError("no InsarMaps host set (use --insarmaps-host or INSARMAPSHOST_OLDDATA)")
    hosts = [host.strip() for host in str(host_arg).split(",") if host.strip()]
    if not hosts:
        raise RuntimeError("no InsarMaps host set (use --insarmaps-host or INSARMAPSHOST_OLDDATA)")
    return hosts


def ingest_step2_rsh():
    """Remote shell for step-2 rsync/ssh. INSARMAPS_SSH_JUMP becomes `ssh <jump> ssh`."""
    rsh = os.environ.get("INSARMAPS_RSH", "").strip()
    if rsh:
        return rsh
    jump = os.environ.get("INSARMAPS_SSH_JUMP", "").strip()
    if jump:
        return f"ssh {jump} ssh"
    return "ssh"


def ingest_remote_paths_for_scratch(data_dir):
    """Map a directory under $SCRATCHDIR to /data/scratch/<relpath> and /data/scratch/<project>."""
    scratch = os.environ.get("SCRATCHDIR", "").strip()
    if not scratch:
        raise RuntimeError("SCRATCHDIR must be set for remote JSON upload (path under /data/scratch/)")
    scratch_abs = Path(scratch).resolve()
    data_abs = Path(data_dir).resolve()
    try:
        rel = data_abs.relative_to(scratch_abs)
    except ValueError as exc:
        raise RuntimeError(f"data dir is not under $SCRATCHDIR ({scratch_abs}): {data_abs}") from exc
    rel_posix = rel.as_posix()
    if not rel_posix or rel_posix == ".":
        raise RuntimeError(f"cannot derive path under $SCRATCHDIR for: {data_abs}")
    project_rel = rel_posix.split("/", 1)[0]
    if project_rel in ("", ".", ".."):
        raise RuntimeError(f"invalid project name under $SCRATCHDIR for: {data_abs}")
    remote_data_dir = f"/data/scratch/{rel_posix}"
    remote_project_dir = f"/data/scratch/{project_rel}"
    if remote_project_dir == "/data/scratch" or not remote_project_dir.startswith("/data/scratch/"):
        raise RuntimeError(f"refusing unsafe remote project path: {remote_project_dir}")
    return remote_data_dir, remote_project_dir


def _append_command_log(message):
    """Append a timestamped command line to ./log (same record ingest_insarmaps.bash writes)."""
    line = f"{datetime.now().strftime('%Y%m%d:%H-%M')} * {message}"
    print(line)
    with open("log", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _reset_ingest_command_log():
    """Start a fresh command list for this run (shown later in outputs/pic/index.html)."""
    Path("ingest_commands.log").write_text("", encoding="utf-8")


def _append_ingest_command_log(command_line):
    """Append one displayed command to ./ingest_commands.log."""
    with open("ingest_commands.log", "a", encoding="utf-8") as handle:
        handle.write(command_line + "\n")


def ingest_step2_rsync_and_remote_ingest(insarmaps_host, local_json_dir, local_mbtiles=None, data_dir=None):
    """Rsync JSON/ to the Insarmaps host, ingest via ssh against 127.0.0.1, then delete the remote scratch tree.
    json_mbtiles2insarmaps.py builds the dataset's recolor store there, from which the map draws it; no .mbtiles is
    sent or installed. local_mbtiles is ignored: it stays in the signature for jobfiles written before."""
    insarmaps_host = str(insarmaps_host).strip()
    local_json_dir = Path(local_json_dir)
    if data_dir is None:
        raise ValueError("data_dir is required (the folder under $SCRATCHDIR that holds JSON/)")
    if not local_json_dir.is_dir():
        raise FileNotFoundError(f"JSON directory missing: {local_json_dir}")

    remote_user = (os.environ.get("REMOTEUSER") or "exouser").strip() or "exouser"
    remote_pass_file = "/data/insarmaps2/postgres_dir/.insaradmin_db_password"
    remote_minsar_home = os.environ.get("INSARMAPS_REMOTE_MINSAR_HOME") or "/data/insarmaps2/code/minsar"
    workers = os.environ.get("MBTILES_NUM_WORKERS") or "6"
    rsh = ingest_step2_rsh()
    rsh_parts = shlex.split(rsh)
    target = f"{remote_user}@{insarmaps_host}"

    remote_data_dir, remote_project_dir = ingest_remote_paths_for_scratch(data_dir)
    remote_json_dir = f"{remote_data_dir}/{local_json_dir.name}"

    print("####################################")
    print(f"Uploading JSON dir to {target}:{remote_json_dir}/ (rsh: {rsh})")
    run_command(rsh_parts + [target, f"mkdir -p {shlex.quote(remote_json_dir)}"])
    run_command([
        "rsync", "-avzh", "--progress", "--exclude=*.mbtiles",
        "-e", rsh,
        f"{local_json_dir}/",
        f"{target}:{remote_json_dir}/",
    ])

    print("####################################")
    print(f"Reading DB password from {target}:{remote_pass_file}")
    password_cmd = f"sudo -n cat {shlex.quote(remote_pass_file)} | tr -d '[:space:]'"
    password_display = f"{rsh} {target} {password_cmd}"
    print(f"Running.... {password_display}")
    _append_ingest_command_log(password_display)
    _append_command_log(password_display)
    try:
        pg_pass = subprocess.check_output(rsh_parts + [target, password_cmd], text=True).strip()
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"failed to read DB password from {target}:{remote_pass_file} (exit {exc.returncode})"
        ) from exc
    if not pg_pass:
        raise RuntimeError(f"empty password from {target}:{remote_pass_file}")

    ingest_cmd = (
        f"json_mbtiles2insarmaps.py --num-workers {workers} -u insaradmin -p {pg_pass} "
        f"--host 127.0.0.1 --json_folder {remote_json_dir}"
    )
    print("####################################")
    print(f"Running.... {rsh} {target} {ingest_cmd}")
    _append_ingest_command_log(f"{rsh} {target} {ingest_cmd}")
    _append_command_log(f"{rsh} {target} {ingest_cmd}")

    # Source remote minsar env so PROJ_LIB is set.
    remote_body = (
        "set -euo pipefail; "
        f"export MINSAR_HOME={shlex.quote(remote_minsar_home)}; "
        'source "$MINSAR_HOME/setup/environment.bash" >/dev/null; '
        f"json_mbtiles2insarmaps.py --num-workers {shlex.quote(str(workers))} -u insaradmin "
        f"-p {shlex.quote(pg_pass)} --host 127.0.0.1 --json_folder {shlex.quote(remote_json_dir)}"
    )
    remote_status = subprocess.run(rsh_parts + [target, "bash -lc " + shlex.quote(remote_body)]).returncode
    if remote_status != 0:
        print(
            f"{rsh} {target} json_mbtiles2insarmaps.py exited with a non-zero exit code "
            f"(exit code: {remote_status}). Exiting."
        )
        sys.exit(1)

    print("####################################")
    print(f"Removing remote project folder {target}:{remote_project_dir}")
    run_command(rsh_parts + [target, f"rm -rf {shlex.quote(remote_project_dir)}"])
