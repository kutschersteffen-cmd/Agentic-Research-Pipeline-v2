"""Compatibility re-export; canonical home is `arp.core.atomic_io`."""

from arp.core.atomic_io import (
    _atomic_write,
    atomic_write_bytes,
    atomic_write_text,
    read_text_utf8,
    write_text_exclusive,
)

__all__ = [
    "_atomic_write",
    "atomic_write_bytes",
    "atomic_write_text",
    "read_text_utf8",
    "write_text_exclusive",
]
