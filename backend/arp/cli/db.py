from __future__ import annotations

import typer

from arp.config import get_settings
from arp.db.session import require_dsn

db_app = typer.Typer(
    help="Store setup: Postgres/pgvector (required, ARP_POSTGRES_DSN), plus optional object storage "
    "(ARP_OBJECT_STORE_ENDPOINT_URL + the `object_storage` extra); file-era import and verify."
)


@db_app.command("init-postgres")
def db_init_postgres() -> None:
    """Creates or updates the pgvector extension and every table, idempotently.

    Run it against a fresh database before the first start, and again after
    upgrading this codebase: it also adds columns and applies recorded schema
    steps to a database created by an earlier version (see
    arp/storage/postgres_schema.py), and links legacy-keyed rows to companies
    registered since. It never drops anything. Re-running
    against an already-current database changes nothing. `arp db
    check-postgres` reports what a database has without touching it."""
    settings = get_settings()
    from arp.storage.postgres import ensure_schema, get_engine
    from arp.storage.postgres_schema import rekey_company_ids

    result = ensure_schema(settings.postgres_dsn)
    with get_engine(settings.postgres_dsn).begin() as conn:  # rows whose company was registered since
        rekey_company_ids(conn)
    from sqlalchemy import make_url

    typer.echo(f"Postgres schema ready at {make_url(settings.postgres_dsn).render_as_string(hide_password=True)}.")
    for label, key in (
        ("Tables created", "tables_created"),
        ("Columns added", "columns_added"),
        ("Steps applied", "steps_applied"),
    ):
        if result[key]:
            typer.echo(f"  {label}: {', '.join(result[key])}")
    if not any(result[key] for key in ("tables_created", "columns_added", "steps_applied")):
        typer.echo("  Already current -- nothing to change.")


@db_app.command("check-postgres")
def db_check_postgres() -> None:
    """Reports whether a Postgres database matches what this codebase's
    models expect -- missing tables/columns, unapplied schema steps, and
    drift this codebase won't fix on its own (a column the models no longer
    define, a nullability mismatch). Read-only: safe against production.
    Exits non-zero when the database is not current, so it can gate a
    deploy."""
    settings = get_settings()
    from sqlalchemy import make_url

    from arp.storage.postgres_schema import schema_report

    report = schema_report(settings.postgres_dsn)
    typer.echo(f"Postgres schema at {make_url(settings.postgres_dsn).render_as_string(hide_password=True)}:")
    typer.echo(f"  pgvector extension: {'present' if report['vector_extension'] else 'MISSING'}")
    typer.echo(f"  applied schema steps: {', '.join(report['applied_steps']) or 'none'}")
    for label, key in (
        ("missing tables", "missing_tables"),
        ("missing columns", "missing_columns"),
        ("pending schema steps", "pending_steps"),
    ):
        typer.echo(f"  {label}: {', '.join(report[key]) or 'none'}")
    for note in report["drift"]:
        typer.echo(f"  drift: {note}")
    for table, count in report["unmatched_company_rows"].items():
        typer.echo(f"  rows without a company: {table}={count} (matched by `arp db import` once the company exists)")
    if report["current"]:
        typer.echo("Current -- every table, column and schema step this codebase expects is present.")
        return
    typer.echo("NOT current -- run `arp db init-postgres` to apply what's missing.", err=True)
    raise typer.Exit(1)


companies_app = typer.Typer(help="Company registry maintenance.")
db_app.add_typer(companies_app, name="companies")


@companies_app.command("merge")
def companies_merge(keep: str, drop: str) -> None:
    """Moves DROP's identifiers and every row that references it onto KEEP (both company UUIDs)."""
    from uuid import UUID

    from arp.db.companies import merge
    from arp.db.session import transaction

    with transaction() as session:
        merge(session, UUID(keep), UUID(drop))
    typer.echo(f"Merged {drop} into {keep}.")


@db_app.command("import")
def db_import(dry_run: bool = typer.Option(False, "--dry-run", help="Import inside a transaction that is rolled back.")) -> None:
    """Imports the file-era history (universe files, identifier map, schema registry, content.db documents,
    every run oldest first, ESG loads, the file portfolio store's portfolios, companies, securities, resolutions
    and holdings snapshots) into Postgres. Idempotent and resumable: re-running skips what is
    already imported and completes an interrupted run. Files are only read."""
    import json

    from arp.db.importer import import_all

    settings = get_settings()
    report = import_all(require_dsn(settings), settings, dry_run=dry_run)
    typer.echo(("Dry run (nothing written): " if dry_run else "Imported: ")
               + ", ".join(f"{k}={v}" for k, v in report.counts.items()))
    typer.echo(f"Identity conflicts: {len(report.identity_conflicts)}")
    for c in report.identity_conflicts:
        typer.echo(f"  {json.dumps(c, default=str)}")
    typer.echo(f"Fact conflicts (a later run replaced a different value): {len(report.fact_conflicts)}")
    for c in report.fact_conflicts:
        typer.echo(f"  {json.dumps(c, default=str)}")
    typer.echo(f"Decisions skipped (not a review decision value): {len(report.skipped_decisions)}")
    for c in report.skipped_decisions:
        typer.echo(f"  {json.dumps(c, default=str)}")


@db_app.command("verify")
def db_verify() -> None:
    """Compares the run files with the database: row counts per run and each current fact. Exits
    non-zero on any difference; it must report none before the API starts on the database."""
    import json

    from arp.db.importer import verify

    settings = get_settings()
    report = verify(require_dsn(settings), settings)
    for d in report.skipped_decisions:
        typer.echo(f"skipped decision (not a difference): {json.dumps(d, default=str)}")
    for d in report.differences:
        typer.echo(json.dumps(d, default=str))
    if report.differences:
        typer.echo(f"{len(report.differences)} difference(s) between files and database.", err=True)
        raise typer.Exit(1)
    typer.echo("No differences between files and database.")


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply all pending Alembic migrations up to `head`."""
    from arp.db.migrations import current_revision, upgrade_head

    dsn = require_dsn(get_settings())
    upgrade_head(dsn)
    typer.echo(f"Alembic upgraded to {current_revision(dsn)}.")


@db_app.command("current")
def db_current() -> None:
    """Print the database's current Alembic migration revision."""
    from arp.db.migrations import current_revision

    rev = current_revision(require_dsn(get_settings()))
    typer.echo(rev or "unversioned")


@db_app.command("stamp-head")
def db_stamp_head() -> None:
    """Stamp an existing database at Alembic `head` without executing migration DDL."""
    from arp.db.migrations import current_revision, stamp_head

    dsn = require_dsn(get_settings())
    stamp_head(dsn)
    typer.echo(f"Alembic stamped at {current_revision(dsn)}.")
