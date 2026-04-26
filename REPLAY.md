# REPLAY

How to replay a saved raw snapshot locally without hitting the network.

**TODO:** write this once `scrape.py` exists (build order step 2). The flow
will be:

1. Pick a file from `raw_snapshots/YYYYMMDD_HHMMSS.json.gz`.
2. `DRY_RUN=1 SNAPSHOT=<path> python scrape.py | python reconcile.py` against a
   scratch SQLite copy.
3. Inspect the resulting events and what `notify.py` would have fired.
