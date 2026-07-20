# Plan: save_explorer.py HDFEOS5 support

## Summary

**Implemented.** MinSAR-patched `save_explorer` accepts geocoded HDFEOS `.he5`, prefers matching `geo/geo_velocity.h5`, else MintPy poly-1 estimate.

## Velocity resolution (implemented)

1. Explicit `-v`
2. Matching `geo/geo_velocity.h5` or `geo_velocity.h5`
3. Else estimate with MintPy `time_func` polynomial=1
4. Classic sibling `velocity.h5` for timeseries when present

Mask: matching geo/sibling mask only if grid matches; else HDFEOS `quality/mask`.

## Files

- `additions/mintpy/save_explorer.py`
- `additions/mintpy/cli/save_explorer.py`
- Symlinks in `tools/MintPy/src/mintpy/` (+ `install_minsar.bash`)
- `additions/mintpy/tests/test_save_explorer.py`
- `architecture_docs/GEocode_HE5.md`
