# ISCE3 HPC opportunity plans

Ordered implementation plans for [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md). Tackle **one at a time**.

| Order | File | Focus |
|-------|------|--------|
| 0 | [00_job_resources_foundation.md](./00_job_resources_foundation.md) | **Done:** `JOB_SUBMIT` + `queues.cfg`; CSLC dolphin burst-aware worker flags |
| 1 | [01_cslc_launcher.md](./01_cslc_launcher.md) | Multi-node LAUNCHER for SAFE `create_cslc` |
| 2 | [02_dolphin_stage_split.md](./02_dolphin_stage_split.md) | Split dolphin into sequential SLURM stages; memory-aware unwrap `n_parallel_jobs` |
| 3 | [03_unwrap_scaleout.md](./03_unwrap_scaleout.md) | Fat-node and/or LAUNCHER per-ifg unwrap |
| 4 | [04_gpu_path.md](./04_gpu_path.md) | CUDA for COMPASS / dolphin linking |
| 5 | [05_opera_disp_style.md](./05_opera_disp_style.md) | Spike: OPERA-DISP-style temporal ministacks |
