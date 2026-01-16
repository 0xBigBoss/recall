from __future__ import annotations

import typer

from recall.core.types import parse_source
from recall.db import RecallLockError
from recall.services import index_sessions
from recall.cli.utils import print_json


def command(
    full: bool = typer.Option(False, "--full", help="Force full reindex"),
    source: str | None = typer.Option(None, "--source", help="claude-code or codex"),
    recreate: bool = typer.Option(False, "--recreate", help="Backup and rebuild database"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    src = parse_source(source) if source else None
    try:
        summary = index_sessions(source=src, full=full, recreate=recreate, verbose=verbose)
    except RecallLockError as err:
        typer.echo(f"error: {err}")
        raise typer.Exit(code=1)

    if json_output:
        print_json(summary)
        return

    typer.echo(
        f"Indexed {summary.indexed} sessions, skipped {summary.skipped}, "
        f"failed {summary.failed} (total {summary.total})."
    )
