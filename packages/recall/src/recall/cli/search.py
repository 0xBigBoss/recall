from __future__ import annotations

import typer

from recall.cli.utils import print_json
from recall.core.types import parse_source
from recall.services import search as search_service


def command(
    query: str = typer.Argument(..., help="Search query"),
    tool: str | None = typer.Option(None, "--tool", help="Filter by tool name"),
    source: str | None = typer.Option(None, "--source", help="claude-code or codex"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    src = parse_source(source) if source else None
    try:
        results = search_service(query=query, source=src, tool=tool, limit=20)
    except RuntimeError as err:
        typer.echo(f"error: {err}")
        raise typer.Exit(code=1) from None
    if json_output:
        print_json(results)
        return

    if not results:
        typer.echo("No results.")
        return

    for result in results:
        header = f"[{result.score:.2f}] {result.session_id} ({result.source})"
        typer.echo(header)
        if result.kind == "message":
            snippet = (result.content or "").strip()
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            role = result.role or "unknown"
            typer.echo(f"  {role}: {snippet}")
        else:
            tool_name = result.tool_name or "tool"
            command = result.bash_command or ""
            typer.echo(f"  [{tool_name}] {command}")
        if result.source_path:
            typer.echo(f"  source: {result.source_path}")
        if result.timestamp:
            typer.echo(f"  time: {result.timestamp}")
        typer.echo("")
