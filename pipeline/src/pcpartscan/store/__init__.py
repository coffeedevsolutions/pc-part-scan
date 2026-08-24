"""Storage backend selection.

Two interchangeable backends expose the same write API (upsert_lots,
record_bids, upsert_sold, save_manifest, all_manifests, sold_lots,
open_lots_raw, record_components, write_snapshot, update_index):

  pcpartscan.dataset      flat files under data/ (the original format)
  pcpartscan.store.mongo  MongoDB, selected when MONGODB_URI is set

PCPS_STORE=files|mongo overrides the automatic choice.
"""

from __future__ import annotations

import os


def _pick():
    choice = os.environ.get("PCPS_STORE")
    if choice == "files":
        from .. import dataset
        return dataset
    if choice == "mongo" or os.environ.get("MONGODB_URI"):
        from . import mongo
        return mongo
    from .. import dataset
    return dataset


backend = _pick()
