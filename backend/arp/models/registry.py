"""Compatibility re-export; canonical home is `arp.core.model_registry`."""

from arp.core.model_registry import (
    ALLOWED_PATH,
    DEFAULT_EMBED_DIM,
    DEFAULT_EMBED_MODEL_NAME,
    REGISTRY_PATH,
    RegistryEntry,
    entries,
    entry,
    model_header,
    provenance,
)

__all__ = [
    "ALLOWED_PATH",
    "DEFAULT_EMBED_DIM",
    "DEFAULT_EMBED_MODEL_NAME",
    "REGISTRY_PATH",
    "RegistryEntry",
    "entries",
    "entry",
    "model_header",
    "provenance",
]
