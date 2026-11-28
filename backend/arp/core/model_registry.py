"""Model registry: pinned Hugging Face revisions, allow-list and provenance."""
import functools
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "models" / "registry.json"
ALLOWED_PATH = Path(__file__).resolve().parents[1] / "models" / "allowed.txt"
DEFAULT_EMBED_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_EMBED_DIM = 384


class RegistryEntry(BaseModel):
    key: str
    capability: Literal["embed", "rerank", "classify", "spans", "tag"]
    hf_id: str
    revision: str
    labels: list[str] | None = None
    dim: int | None = None  # embed models: vector length


@functools.cache
def _load(path: Path) -> dict[str, RegistryEntry]:
    entries = (RegistryEntry(**d) for d in json.loads(path.read_text()))
    return {e.key: e for e in entries}


def entry(key: str) -> RegistryEntry:
    e = _load(REGISTRY_PATH).get(key)
    if e is None:
        raise KeyError(key)
    allowed = ALLOWED_PATH.read_text().split()
    if e.hf_id not in allowed:
        raise ValueError(f"model {e.hf_id!r} is not in the allow-list")
    return e


def entries(capability: str) -> list[RegistryEntry]:
    """Every allowed registry entry of `capability`, in registry order."""
    return [entry(k) for k, e in _load(REGISTRY_PATH).items() if e.capability == capability]


def provenance(e: RegistryEntry, where: Literal["cloud", "local"]) -> dict:
    return {"model": e.key, "revision": e.revision, "where": where}


def model_header(e: RegistryEntry) -> str:
    return f"{e.hf_id}@{e.revision}"
