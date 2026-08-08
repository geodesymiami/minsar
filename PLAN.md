# Plan: Retire MintPy overlay for subset.py; keep HDFEOS helper as minsar util

## Status: DONE

- Moved `additions/mintpy/subset.py` → `minsar/utils/subset_hdfeos5.py`
- Removed `ln -sf …/subset.py …/mintpy/cli` from `setup/install_minsar.bash`
- `update_symlinks.py --dry-run`: no subset overlay; "All sym links are in place"
