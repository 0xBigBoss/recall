from __future__ import annotations

import typer

from recall.cli.utils import format_datetime, print_json
from recall.core.time import parse_since
from recall.core.types import parse_source
from recall.services import list_sessions


def command(
    source: str | None = typer.Option(None, "--source", help="claude-code or codex"),
    since: str | None = typer.Option(None, "--since", help="Time window (7d, 24h, 2024-01-01)"),
    project: str | None = typer.Option(None, "--project", help="Filter by git repo path"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    src = parse_source(source) if source else None
    since_dt = parse_since(since) if since else None
    sessions = list_sessions(source=src, since=since_dt, project=project, limit=50)
    if json_output:
        print_json(sessions)
        return

    if not sessions:
        typer.echo("No sessions found.")
        return

    for session in sessions:
        started = format_datetime(session.started_at)
        project_label = session.git_repo or session.cwd or "unknown"
        typer.echo(
            f"[{started}] {session.id} ({session.source}) {project_label} "
            f"messages={session.message_count} tools={session.tool_count}"
        )
