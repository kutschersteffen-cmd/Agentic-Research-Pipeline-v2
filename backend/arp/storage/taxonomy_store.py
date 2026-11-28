from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from arp.db.json_document_repo import JsonDocumentRepo
from arp.errors import NotConfigured
from arp.schemas.common import now_iso
from arp.schemas.taxonomy import DerivationMethod, Taxonomy, TaxonomyStatus
from arp.schemas.thematic import OLD_FORMAT_MESSAGE, ThemeDefinition
from arp.storage.atomic_io import atomic_write_text, read_text_utf8, write_text_exclusive
from arp.storage.locks import KeyedLock
from arp.storage.safe_path import safe_id

# How many times new_version re-reads and re-bumps when the version it
# picked was claimed by another *process* between the read and the write
# (within this process the KeyedLock already serializes them). Bounded so
# a pathological writer can't spin here forever.
_VERSION_BUMP_ATTEMPTS = 5


class TaxonomyVersionConflict(NotConfigured):
    """A version file this store meant to create already existed -- see
    TaxonomyStore.new_version. Surfaces as a 503 via api/main.py's
    RuntimeError handler: the caller's edit was not saved and retrying is
    the right response."""


class TaxonomyStore:
    """Persistence for the taxonomy library: backed by Postgres `app_documents`
    when `dsn` is provided (enforcing version immutability via `put_if_absent` /
    `ON CONFLICT DO NOTHING`), or by local versioned JSON files under
    `taxonomies_dir` otherwise.
    """

    def __init__(self, taxonomies_dir: Path | None = None, *, dsn: str | None = None) -> None:
        if taxonomies_dir is None and not dsn:
            raise ValueError("TaxonomyStore requires either taxonomies_dir or dsn")
        self.taxonomies_dir = taxonomies_dir
        self._versions_repo = JsonDocumentRepo(dsn, "taxonomy_versions") if dsn else None
        self._latest_repo = JsonDocumentRepo(dsn, "taxonomy_latest") if dsn else None
        self._locks = KeyedLock(
            lock_path=(lambda taxonomy_id: self._dir(taxonomy_id) / ".lock") if taxonomies_dir is not None and not dsn else None
        )

    @contextmanager
    def lock(self, taxonomy_id: str) -> Iterator[None]:
        """Serializes a read-modify-write cycle against one taxonomy."""
        with self._locks.acquire(taxonomy_id):
            yield

    @staticmethod
    def _version_key(taxonomy_id: str, version: int) -> str:
        return f"{safe_id(taxonomy_id, label='taxonomy_id')}:v{version}"

    def _dir(self, taxonomy_id: str) -> Path:
        assert self.taxonomies_dir is not None
        d = self.taxonomies_dir / safe_id(taxonomy_id, label="taxonomy_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _version_path(self, taxonomy_id: str, version: int) -> Path:
        return self._dir(taxonomy_id) / f"v{version}.json"

    def _latest_pointer_path(self, taxonomy_id: str) -> Path:
        return self._dir(taxonomy_id) / "latest.json"

    def _write_new_version(self, taxonomy: Taxonomy) -> None:
        """Writes a version record that must not exist yet, then advances
        the pointer. This order matters: a crash between the two leaves a
        complete version record that `get(taxonomy_id, version)` can still
        read and a pointer that merely lags, whereas the reverse order
        would point at a record that isn't there."""
        if self._versions_repo is not None:
            inserted = self._versions_repo.put_if_absent(
                self._version_key(taxonomy.taxonomy_id, taxonomy.version),
                taxonomy.model_dump(mode="json"),
            )
            if not inserted:
                raise FileExistsError(f"Taxonomy version already exists: {taxonomy.taxonomy_id} v{taxonomy.version}")
            self._write_latest_pointer(taxonomy.taxonomy_id, taxonomy.version)
            return
        write_text_exclusive(self._version_path(taxonomy.taxonomy_id, taxonomy.version), taxonomy.model_dump_json(indent=2))
        self._write_latest_pointer(taxonomy.taxonomy_id, taxonomy.version)

    def _write_latest_pointer(self, taxonomy_id: str, version: int) -> None:
        if self._latest_repo is not None:
            self._latest_repo.update(
                safe_id(taxonomy_id, label="taxonomy_id"),
                lambda cur: {"latest_version": max(int((cur or {}).get("latest_version", 0)), version)},
            )
            return
        atomic_write_text(self._latest_pointer_path(taxonomy_id), json.dumps({"latest_version": version}))

    def create(
        self,
        name: str,
        theme: ThemeDefinition,
        derivation_method: DerivationMethod,
        source_notes: str = "",
    ) -> Taxonomy:
        taxonomy = Taxonomy(name=name, version=1, theme=theme, derivation_method=derivation_method, source_notes=source_notes)
        with self.lock(taxonomy.taxonomy_id):
            self._write_new_version(taxonomy)
        return taxonomy

    def new_version(
        self,
        taxonomy_id: str,
        theme: ThemeDefinition,
        derivation_method: DerivationMethod | None,
        source_notes: str = "",
    ) -> Taxonomy:
        """Appends a new version based on whatever is currently latest.
        `derivation_method=None` keeps the latest version's method (read under the same lock).

        The whole read-current-then-write-next cycle is locked, so two
        concurrent edits produce v2 and v3 rather than both writing v2 and
        one edit vanishing. The retry loop covers the cross-process case
        the in-process lock can't: the exclusive create fails, and
        we re-read and bump again instead of clobbering the other writer.
        """
        with self.lock(taxonomy_id):
            for _ in range(_VERSION_BUMP_ATTEMPTS):
                current = self.get(taxonomy_id)
                if current is None:
                    raise ValueError(f"Unknown taxonomy_id: {taxonomy_id}")
                updated = Taxonomy(
                    taxonomy_id=taxonomy_id,
                    name=current.name,
                    version=current.version + 1,
                    theme=theme,
                    derivation_method=derivation_method or current.derivation_method,
                    source_notes=source_notes,
                    based_on_version=current.version,
                )
                try:
                    self._write_new_version(updated)
                except FileExistsError:
                    continue
                return updated
        raise TaxonomyVersionConflict(
            f"Could not claim a new version for taxonomy {taxonomy_id} after {_VERSION_BUMP_ATTEMPTS} attempts -- "
            "another writer is creating versions concurrently. The edit was not saved; retry it."
        )

    def get(self, taxonomy_id: str, version: int | None = None) -> Taxonomy | None:
        if self._versions_repo is not None and self._latest_repo is not None:
            tid = safe_id(taxonomy_id, label="taxonomy_id")
            if version is None:
                pointer = self._latest_repo.get(tid)
                if pointer is None:
                    return None
                version = int(pointer["latest_version"])
            payload = self._versions_repo.get(self._version_key(tid, version))
            return Taxonomy.model_validate(payload) if payload is not None else None
        if version is None:
            pointer_path = self._latest_pointer_path(taxonomy_id)
            if not pointer_path.exists():
                return None
            version = json.loads(read_text_utf8(pointer_path))["latest_version"]
        path = self._version_path(taxonomy_id, version)
        if not path.exists():
            return None
        return Taxonomy.model_validate_json(read_text_utf8(path))

    def list_versions(self, taxonomy_id: str) -> list[Taxonomy]:
        if self._versions_repo is not None:
            prefix = f"{safe_id(taxonomy_id, label='taxonomy_id')}:v"
            versions = []
            for key, payload in self._versions_repo.list_items():
                if not key.startswith(prefix):
                    continue
                try:
                    versions.append(Taxonomy.model_validate(payload))
                except ValueError as exc:
                    if OLD_FORMAT_MESSAGE in str(exc):
                        raise
                    continue
            return sorted(versions, key=lambda t: t.version)
        assert self.taxonomies_dir is not None
        d = self.taxonomies_dir / safe_id(taxonomy_id, label="taxonomy_id")
        if not d.exists():
            return []
        versions = []
        for p in d.glob("v*.json"):
            try:
                versions.append(Taxonomy.model_validate_json(read_text_utf8(p)))
            except (json.JSONDecodeError, ValueError) as exc:
                if OLD_FORMAT_MESSAGE in str(exc):
                    raise
                continue
        return sorted(versions, key=lambda t: t.version)

    def list_all(self) -> list[Taxonomy]:
        """The latest version of every taxonomy in the library."""
        if self._latest_repo is not None:
            latest: list[Taxonomy] = []
            for tid in self._latest_repo.list_keys():
                taxonomy = self.get(tid)
                if taxonomy is not None:
                    latest.append(taxonomy)
            return latest
        assert self.taxonomies_dir is not None
        if not self.taxonomies_dir.exists():
            return []
        latest = []
        for d in sorted(self.taxonomies_dir.iterdir()):
            if not d.is_dir():
                continue
            taxonomy = self.get(d.name)
            if taxonomy is not None:
                latest.append(taxonomy)
        return latest

    def ratify(self, taxonomy_id: str, version: int, ratified_by: str) -> Taxonomy:
        """Marks a specific version as ratified in place -- this is a status
        change on an already-existing, already-immutable version record,
        not a new edit, so it doesn't create a new version.
        """
        with self.lock(taxonomy_id):
            taxonomy = self.get(taxonomy_id, version)
            if taxonomy is None:
                raise ValueError(f"Unknown taxonomy_id/version: {taxonomy_id} v{version}")
            ratified = taxonomy.model_copy(
                update={"status": TaxonomyStatus.RATIFIED, "ratified_by": ratified_by, "ratified_at": now_iso()}
            )
            if self._versions_repo is not None:
                self._versions_repo.put(self._version_key(taxonomy_id, version), ratified.model_dump(mode="json"))
            else:
                # The one write in this store that legitimately replaces an
                # existing version file, so it can't use O_EXCL -- atomically
                # instead, or a crash mid-write would leave the ratified
                # version unparseable (and silently skipped by list_versions).
                atomic_write_text(self._version_path(taxonomy_id, version), ratified.model_dump_json(indent=2))
        return ratified


def ensure_taxonomy_usable_for_run(taxonomy: Taxonomy, require_ratified: bool) -> None:
    """The human curation gate (Step 0d): when require_ratified is set,
    refuses to let a run start from a taxonomy still in DRAFT status.

    Off by default (require_ratified=False) so anyone iterating on a draft
    taxonomy keeps today's workflow; a deployment that wants a hard gate
    turns it on via ARP_REQUIRE_RATIFIED_TAXONOMY. A pure function rather
    than inline router logic so the gate itself is unit-testable without
    spinning up the FastAPI app.
    """
    if not require_ratified:
        return
    if taxonomy.status != TaxonomyStatus.RATIFIED:
        raise ValueError(
            f"Taxonomy {taxonomy.taxonomy_id} v{taxonomy.version} is still {taxonomy.status.value}; ratify it "
            "first (POST /api/taxonomies/{taxonomy_id}/ratify) or disable ARP_REQUIRE_RATIFIED_TAXONOMY."
        )
