#!/usr/bin/env python3
"""Step 2 of an Insarmaps ingest, for the Python uploaders (sarvey2insarmaps.py and others): rsync the JSON folder that
step 1 wrote to the Insarmaps host, under /data/scratch, run json_mbtiles2insarmaps.py there over ssh against the
host's database (--host 127.0.0.1), then delete the remote copy. On the Insarmaps host itself (insarmaps_host_is_local)
it runs json_mbtiles2insarmaps.py on the JSON folder where it is instead: no copy, no ssh, no $SCRATCHDIR.
ingest_insarmaps.bash does the same in bash (ingest_step2_rsync_and_remote_ingest)."""
import os
import shlex
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# the insarmaps database password, readable with sudo on the Insarmaps host
INSARMAPS_DB_PASSWORD_FILE = "/data/insarmaps2/postgres_dir/.insaradmin_db_password"


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
    # an argument list without a shell, built by the uploaders (mkdir, rsync and rm of the staging folder over ssh)
    subprocess.run(cmd_parts, check=True, cwd=str(cwd) if cwd else None)  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit


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


def insarmaps_host_is_local(host):
    """True when the Insarmaps host is the machine this runs on: localhost, 127.0.0.1 or ::1, this machine's name
    (short or full), or a host named in INSARMAPS_LOCAL_HOSTS (comma-separated). The variable is for an address the
    machine can't recognise as its own, such as a cloud floating IP: on insarmaps2, 149.165.153.50."""
    host = str(host or "").strip().lower()
    if not host:
        return False
    names = {"localhost", "127.0.0.1", "::1"}
    name = socket.gethostname().lower()
    names.update({name, name.split(".")[0], socket.getfqdn().lower()})
    names.update(h.strip().lower() for h in os.environ.get("INSARMAPS_LOCAL_HOSTS", "").split(",") if h.strip())
    return host in names


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


def ingest_step2_local(local_json_dir):
    """Step 2 on the Insarmaps host itself: json_mbtiles2insarmaps.py loads JSON/ where it is into this machine's
    database (--host 127.0.0.1) and builds the dataset's recolor store. No copy, no ssh, no $SCRATCHDIR. The password
    comes from INSARMAPS_DB_PASSWORD_FILE through sudo, as on the remote path, and is not written to the logs."""
    workers = os.environ.get("MBTILES_NUM_WORKERS") or "6"
    print("####################################")
    print(f"Step 2 on this machine (the Insarmaps host): uploading {local_json_dir} where it is")
    password_cmd = ["sudo", "-n", "cat", INSARMAPS_DB_PASSWORD_FILE]
    print(f"Running.... {' '.join(password_cmd)}")
    _append_ingest_command_log(" ".join(password_cmd))
    _append_command_log(" ".join(password_cmd))
    try:
        pg_pass = "".join(subprocess.check_output(password_cmd, text=True).split())
    except (subprocess.CalledProcessError, OSError) as exc:
        raise RuntimeError(f"failed to read the DB password from {INSARMAPS_DB_PASSWORD_FILE}: {exc}") from exc
    if not pg_pass:
        raise RuntimeError(f"empty password from {INSARMAPS_DB_PASSWORD_FILE}")

    ingest_args = ["--num-workers", str(workers), "-u", "insaradmin", "-p", pg_pass, "--host", "127.0.0.1",
                   "--json_folder", str(local_json_dir)]
    shown = (f"json_mbtiles2insarmaps.py --num-workers {workers} -u insaradmin -p *** --host 127.0.0.1 "
             f"--json_folder {local_json_dir}")
    print("####################################")
    print(f"Running.... {shown}")
    _append_ingest_command_log(shown)
    _append_command_log(shown)
    # a fixed program with an argument list, no shell; the values are the JSON folder and the password file's content
    status = subprocess.run(["json_mbtiles2insarmaps.py"] + ingest_args).returncode  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    if status != 0:
        print(f"json_mbtiles2insarmaps.py exited with a non-zero exit code (exit code: {status}). Exiting.")
        sys.exit(1)


def ingest_step2_rsync_and_remote_ingest(insarmaps_host, local_json_dir, local_mbtiles=None, data_dir=None):
    """Rsync JSON/ to the Insarmaps host, ingest via ssh against 127.0.0.1, then delete the remote scratch tree; on the
    Insarmaps host itself (insarmaps_host_is_local), ingest_step2_local instead, which needs no data_dir.
    json_mbtiles2insarmaps.py builds the dataset's recolor store there, from which the map draws it; no .mbtiles is
    sent or installed. local_mbtiles is ignored: it stays in the signature for jobfiles written before."""
    insarmaps_host = str(insarmaps_host).strip()
    local_json_dir = Path(local_json_dir)
    if not local_json_dir.is_dir():
        raise FileNotFoundError(f"JSON directory missing: {local_json_dir}")
    if insarmaps_host_is_local(insarmaps_host):
        ingest_step2_local(local_json_dir.resolve())
        return
    if data_dir is None:
        raise ValueError("data_dir is required (the folder under $SCRATCHDIR that holds JSON/)")

    remote_user = (os.environ.get("REMOTEUSER") or "exouser").strip() or "exouser"
    remote_pass_file = INSARMAPS_DB_PASSWORD_FILE
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
    # --delete: the staging folder holds exactly this JSON/, also when an earlier attempt failed and left one behind
    run_command([
        "rsync", "-avzh", "--progress", "--delete", "--exclude=*.mbtiles",
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
        # ssh from the operator's own settings (INSARMAPS_RSH, INSARMAPS_SSH_JUMP, REMOTEUSER); the remote command's
        # only value, the password file's path, is a constant passed through shlex.quote
        pg_pass = subprocess.check_output(rsh_parts + [target, password_cmd], text=True).strip()  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit, python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
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
    # ssh as above; every value in remote_body went through shlex.quote, and the whole through shlex.quote again
    remote_status = subprocess.run(rsh_parts + [target, "bash -lc " + shlex.quote(remote_body)]).returncode  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit, python.lang.security.audit.dangerous-subprocess-use-tainted-env-args
    if remote_status != 0:
        print(
            f"{rsh} {target} json_mbtiles2insarmaps.py exited with a non-zero exit code "
            f"(exit code: {remote_status}). Exiting."
        )
        sys.exit(1)

    print("####################################")
    print(f"Removing remote project folder {target}:{remote_project_dir}")
    run_command(rsh_parts + [target, f"rm -rf {shlex.quote(remote_project_dir)}"])
