# Plan: changequeuepvc directory + --jobfiles

## Summary
Extend `changequeuepvc` so a directory argument selects `.job` files via glob patterns. Patterns come from `--jobfiles` (default when a dir is given: `run_06*.job run_07*.job run_08*.job run_09*.job`). Existing explicit `.job` file args and `--walltime` keep working.

## Status
Implemented.

## Examples (help)
```
changequeuepvc run_09*.job
changequeuepvc --walltime 2:00:00 run_09*.job
changequeuepvc run_files/
changequeuepvc run_files/ --jobfiles run_08*.job run_09*.job
changequeuepvc --walltime 2:00:00 run_files/
```
