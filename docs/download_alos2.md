# Downloading ALOS-2 ScanSAR data: login node or SLURM job?

**Recommendation: download on the login node** (`--download-method slc-unpack-login`,
the default for ALOS-2 in `minsarApp.bash`).
On Stampede3 a login node downloads about three times faster than a compute node,
and there is no queue wait and no walltime limit.

This is based on the timing files (`SLC_ORIG/download_timing.csv` / `.txt`) of seven
Tambora ALOS-2 descending-track-26 runs on 24 November 2026: 79 granules, about 4.4 TB,
all from ASF (CloudFront), all with `--parallel=6`. Every granule succeeded on the first attempt.

## What was measured

Rates are in MiB/s. A WBD granule is about 57 GiB (60.9 GB) zipped.

| Run | Where | Granules | Per-stream rate (median) | Total rate with 6 streams | Download time | Download + unpack |
|-----|-------|---------:|-------------------------:|--------------------------:|--------------:|------------------:|
| q16 | login3 | 6 | 55 | 310 | 28 min | 38 min |
| q18 | login3 | 16 | 54 | 320 | 73 min | 87 min |
| q20 | login3 | 18 | 58 | not recorded | not recorded | not recorded |
| q25 | login3 | 3 | 53 | not recorded | not recorded | not recorded |
| q15 | job, c454-011 | 8 | 18.5 | 111 | 74 min | 89 min |
| q17 | job, c454-014 | 10 (3 half-size) | 20.5 | 124 | 79 min | 84 min |
| q19 | two jobs, c455-002 and c454-041 | 18 | 21 and 30 | 113 and 144 | 165 min | 197 min |

q20 and q25 only have the `.txt` format, which has no start and end times, so the
total rate and elapsed time cannot be derived for them.

## Findings

1. **A compute node is capped at about 110–125 MiB/s in total, which is about 1 Gbit/s.**
   The streams share that cap: six streams get 18–21 MiB/s each, and when only two are
   left they get 52 MiB/s each (q15: 6 streams 111 MiB/s total, 2 streams 104 MiB/s total).
   More than two parallel streams buys nothing on a compute node.

2. **The login node has no such cap up to six streams.** Each stream runs at
   about 53 MiB/s regardless of how many run together (q18: 1 stream 52, 6 streams
   320 MiB/s total). The limit is per stream, on the ASF side. Whether more than six
   streams would scale further was not tested.

3. **Per granule, the login node takes about 17 minutes and a compute node 45–52 minutes**
   when six run together.

4. **Unpacking is no faster on a compute node.** Median unpack time per granule was
   8–12 minutes on the login node and 6–16 minutes on compute nodes. The longest
   unpacks (three at 41 minutes in q19) were on a compute node.

5. **The 2-hour `skx-dev` walltime is too short for a full year in a job.**
   At the capped rate a job downloads about 12 granules in 2 hours. The first q19 job
   ran out of time with six granules partly downloaded; a second job resumed them
   (HTTP 206) and finished. The resume worked correctly, but the run took 3.4 hours
   plus two queue waits for 18 granules. On the login node, 16 granules took 87 minutes.

6. **About one stream in forty is slow, on either kind of node.** One granule in q19 (job)
   and one in q20 (login) ran at 9 MiB/s for the whole file, about 105 minutes instead
   of 17. This comes from the server side and adds a tail to the run wherever it runs.

## How to download

- Use `minsarApp.bash <template>`; for ALOS-2 it downloads on the login node by default
  (same as `--download-method slc-unpack-login`). Keep `--parallel=6`.
- Run it inside `screen` or `tmux` (or with `nohup`) so that a dropped connection does
  not stop it. If it is interrupted, rerun the same command: finished granules are
  skipped and partial ones are resumed.
- Expect about 5.5 minutes per granule overall for download plus unpack: about 1.5 hours
  for a year of 16–18 granules.
- The six parallel unpack processes are the only real load on the shared login node.
  If that becomes a problem, lower `--parallel` to 3 or 4; the download rate drops in
  proportion, to about 160–215 MiB/s, which is still above what a compute node reaches.

## If it has to run as a job

- Use `--download-method slc-unpack`, but not in `skx-dev` for more than about
  10 granules. Use a queue with a longer walltime, or split the date range.
- Plan for 110 MiB/s in total: about 9 minutes per granule, 2.5–3 hours for 18 granules.
- A failed or timed-out job can simply be resubmitted; it resumes where it stopped.
