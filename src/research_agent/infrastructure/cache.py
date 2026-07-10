"""Persistent cache placeholder."""

from pathlib import Path

import diskcache


def build_cache(cache_dir: Path) -> diskcache.Cache:
    """Create a disk-backed cache."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    return diskcache.Cache(cache_dir)
