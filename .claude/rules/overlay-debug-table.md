---
paths:
  - "minsar/html/overlay.html"
  - "minsar/html/debug_table_overlay/**"
---

# Overlay debug table

Never edit the debug table code in `minsar/html/overlay.html` by hand. Edit the fragments in `minsar/html/debug_table_overlay/` and run the script; see the `README.md` there for layout and deploy notes.

```bash
python3 minsar/html/debug_table_overlay/apply_debug_table.py append minsar/html/overlay.html
python3 minsar/html/debug_table_overlay/apply_debug_table.py remove minsar/html/overlay.html
python3 minsar/html/debug_table_overlay/apply_debug_table.py sync minsar/html/overlay.html
```

- "Append debug table to overlay" means run `append`, confirm with `status`, and remind the user to hard-refresh after deploy.
- "Remove debug table from overlay" means run `remove`.
- After editing fragment files, run `sync`.
