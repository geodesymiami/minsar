# ISCE3 OPERA-disp-style local produce (opportunity 5)

Background: [ISCE3_HPC_opportunities.md](../ISCE3_HPC_opportunities.md) type **E**. Spike before large implementation.

## Goal

Decide whether MinSAR should offer a **local produce** path modeled on OPERA DISP sequential processing: temporal **ministacks** in series (compressed CSLCs carried forward) → many moving-reference products → `opera-utils disp-s1-reformat` / rebase → continuous timeseries—instead of (or beside) one monolithic `dolphin run`.

## Clarifications

- MinSAR `--disp-S1` today is a **consumer** (download published `OPERA*.nc` → reformat → he5). This opportunity is about **producing** locally.
- OPERA “sequential” = **temporal ministacks**, not MiaplPy spatial patches. Burst parallelism (`n_parallel_bursts`) applies **inside** a ministack.
- This does **not** by itself enable 16-node unwrap LAUNCHER.

## Tradeoffs to evaluate

| Benefit | Cost |
|---------|------|
| Resume at ministack boundary | More jobs / bookkeeping |
| OPERA-compatible intermediates | Different from current SAFE/CSLC dolphin layout |
| Bounded memory / forward updates | Walltime ≈ sum of ministacks (serialized in time) |

## Scope

- Read-only / spike / design decision. Implementation only after go decision.

## Out of scope

- Changing the DISP consumer download path unless the spike requires it.
- Spatial-patch mosaicking as a substitute for StBAS.

## Steps

1. Map `tools/disp-s1` + `disp_s1_process.py` and reformat APIs to MinSAR stages.
2. Small-AOI prototype or detailed design (commands, dirs, restart).
3. Go/no-go write-up linked from the Architecture doc.
