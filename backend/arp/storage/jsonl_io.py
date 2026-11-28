"""Compatibility re-export; canonical home is `arp.core.jsonl_io`."""

from arp.core.jsonl_io import (
    _WARNED,
    append_jsonl,
    complete_rows,
    read_jsonl,
    read_jsonl_numbered,
)

__all__ = [
    "_WARNED",
    "append_jsonl",
    "complete_rows",
    "read_jsonl",
    "read_jsonl_numbered",
]
