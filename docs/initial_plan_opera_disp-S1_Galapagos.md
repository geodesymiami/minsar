# Initial plan: local OPERA-style DISP-S1 for Galapagos

Scope: Isabela, Fernandina, and Santiago only. Do **not** process Santa Cruz or San Cristóbal.

NASA OPERA does not publish DISP-S1 over Galapagos (`is_north_america: false`). This plan is **local operational processing** using the same DISP-S1 frame IDs, CCSLC chaining, and directory layout as OPERA production.

Related: `docs/dolphin_mode_chaining.md`.

---

## 1. AOI and tracks

| Island | Role | Notes |
|--------|------|--------|
| Fernandina | West, often split across IW1/IW2 on track 128 | Two **subswaths**, still one OPERA frame (all IWs are grouped) |
| Isabela | Main landmass (Sierra Negra, Wolf, Ecuador, etc.) | Covered by the same west-track frames |
| Santiago | North-central | Same frames as Fernandina/Isabela on D128 and A106 |
| Santa Cruz | Out of scope | Appears on tracks **A33** and **D55** — do not run those frames |

Recommended tracks (no Santa Cruz in the frame footprints below):

| Track | Pass | OPERA frames | Start with |
|-------|------|--------------|------------|
| **128** | Descending | **F34233**, **F34234** | **F34234** (Sierra Negra + Fernandina) |
| **106** | Ascending | **F28459**, **F28460** | **F28459** (asc pair) |

Do not use for this AOI:

- A33 `F08859`, `F08860` — intersect Santa Cruz
- D55 `F14634` — intersects Santa Cruz (`F14635` is Isabela-only and incomplete for the three-island set)

F34235 (D128, south of the islands, `is_land=0`) is not needed.

Vertex Path 128 / Frame **590** is an **ESA SLC scene**, not an OPERA `F#####`. Fernandina on two IWs does **not** add a second OPERA frame.

---

## 2. How OPERA frame IDs are defined

OPERA DISP frames are **not** ESA/ASF SLC frames. They come from the ADT burst/frame database ([`opera-adt/burst_db`](https://github.com/opera-adt/burst_db); [OPERA DISP-S1 ATBD](https://earthdata.nasa.gov/s3fs-public/2026-03/OPERA_DISP-S1_ATBD_D-108765_Rev_A_v1.0.0_Final.pdf)).

### Building blocks

1. **ESA burst ID map** — each IW burst has a stable ID `t{track}_{burstIndex}_{iw}` (e.g. `t128_…_iw1`). The same burst ID repeats every cycle over the same ground.
2. **Group into DISP frames** (ATBD):
   - Nominally **27 bursts**: **9 along-track** burst rows × **IW1+IW2+IW3** always together.
   - Adjacent frames **overlap by one burst row** along-track (so unwrapped products can be stitched).
   - Frame footprint is a **UTM** rectangle; zone from the geographic center of the frame (~5 km margin in the JSON metadata).
3. **Integer `frame_id`** — keys in `frame-to-burst.json` (`"1"`, `"2"`, …). IDs are assigned when the database is built: walk the global burst map (by track, then along-track) and increment. **F34234 is not computed from lat/lon**; it is the catalog ID of that 27-burst group. Consecutive IDs on one track (F34233, F34234, F34235) are neighbors along that orbit.

A burst on the overlap belongs to **two** frames (`burst-to-frame` is many-to-many). CCSLC **filenames** still include **one** frame id (`…_F34234_T128-…`); do not share one CCSLC file across two `F#####` directories.

### Where to look them up (not Vertex SLC search)

| Tool | What you see |
|------|----------------|
| ASF Vertex SLC | ESA **Path / Frame** (e.g. 128 / 590) |
| ASF Displacement Portal | OPERA `F#####` — **North America only** |
| `opera_utils.get_intersecting_frames(Bbox(...))` | OPERA frames for any bbox (including Galapagos) |
| `opera_utils.get_burst_ids_for_frame(34234)` | The 27 burst IDs |
| QGIS: `opera-s1-disp.gpkg` layer `frames` | Draw footprints |

Example:

```bash
pixi run --as-is --manifest-path "$MINSAR_HOME/tools/sweets/pyproject.toml" -- python3 -c "import opera_utils, json; print(json.dumps(opera_utils.get_intersecting_frames(opera_utils.Bbox(-91.8,-1.15,-90.5,0.25))))"
```

---

## 3. Processing unit and directories

One **OPERA frame** = one job, one CCSLC store. Do not mix frames or mix Galapagos with Ecuador.

```text
$OPS/galapagos/
  F34234/                         # D128 — start here
    input_groups/input_cslcs/     # real OPERA L2 CSLCs (or local COMPASS)
    input_groups/input_ccslc/     # compressed SLCs for this frame only
    output_dir/
    scratch_path/
    Runconfig.yaml
  F34233/                         # D128 north (Fernandina / Santiago)
  F28459/                         # A106
  F28460/                         # A106 neighbor
```

Compressed SLC names (operational convention):

```text
OPERA_L2_COMPRESSED-CSLC-S1_F34234_<BURST>_<ref>Z_<start>Z_<end>Z_<prod>Z_VV_v1.0.h5
```

Flat under `F34234/input_groups/input_ccslc/`. No burst subfolders. No shared `comp_slcs/` across frames.

MinSAR `--dolphin-mode opera` today writes `disp_s1_produce/comp_slcs/` **without** `F#####` in the filename. For Galapagos ops, use the **per-frame** layout above (same as `disp-s1/scripts/stage_runconfig.py`: `{output}/F{frame_id}/`).

---

## 4. Workflow (per frame)

1. Historical ministacks (`ministack_size` 15) of real CSLCs for the frame’s 27 bursts.
2. After each full historical batch, save CCSLCs into that frame’s `input_ccslc/`.
3. Forward mode: download/read latest CCSLCs for the frame + new real CSLCs; do not write new CCSLCs until the next compression cadence (OPERA: every 15 forward dates in `run_disp.py`).
4. Reformat per-date `.nc` → frame stack; optional HE5.

NASA ASF will **not** supply CCSLCs for these frames. Produce and archive them locally under `F#####/input_groups/input_ccslc/`.

---

## 5. Suggested rollout

1. **F34234** (desc 128) — Sierra Negra, Fernandina, west/central Isabela.
2. **F28459** (asc 106) — ascending pair for 2D/3D later.
3. Add **F34233** and **F28460** if northern Fernandina / Santiago are incomplete in (1)–(2).
4. Leave A33/D55 off until Santa Cruz is in scope.

CSLCs: OPERA L2 if ASF has Galapagos CSLC-S1; otherwise SAFE → COMPASS into the same burst IDs, then the DISP-S1 produce path.

---

## 6. Counts (track 128)

| Question | Answer |
|----------|--------|
| ESA Vertex frames for the archipelago | Several SLC scenes (~590, …) along Path 128 |
| OPERA frames for Isabela + Fernandina + Santiago on track 128 | **2**: F34233, F34234 |
| Extra frames because Fernandina is IW1+IW2 | **0** — each OPERA frame already has IW1–IW3 |

---

## 7. References

- OPERA DISP-S1 ATBD §2.9 — 27 bursts, 9 along-track, 1-burst overlap
- `opera-adt/burst_db` — frame-to-burst JSON, `opera-s1-disp.gpkg`
- `tools/disp-s1/docs/disp-s1-operations.md` — CCSLC filenames and S3 layout
- `tools/disp-s1/scripts/stage_runconfig.py` — local `F{frame_id}/input_groups/input_ccslc/`
- `docs/dolphin_mode_chaining.md` — historical vs forward, ministacks
