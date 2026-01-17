from __future__ import annotations

import typer

from recall.cli.utils import format_datetime, print_json
from recall.services import load_session


def command(
    session_id: str = typer.Argument(..., help="Session ID"),
    tools: bool = typer.Option(False, "--tools", help="Include tool calls"),
    thinking: bool = typer.Option(False, "--thinking", help="Include thinking blocks"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    session = load_session(session_id, include_tools=tools)
    if json_output:
        print_json(session)
        return

    started = format_datetime(session.started_at)
    typer.echo(f"[{started}] Session {session.id} ({session.source.value})")
    if session.git_repo or session.cwd:
        typer.echo(f"Project: {session.git_repo or session.cwd}")
    duration = session.duration_seconds or 0
    msg_count, tool_count = session.message_count, session.tool_count
    typer.echo(f"Duration: {duration}s | Messages: {msg_count} | Tools: {tool_count}")
    typer.echo("")

    for message in session.messages:
        timestamp = format_datetime(message.timestamp)
        typer.echo(f"[{timestamp}] {message.role.value}:")
        if message.content:
            typer.echo(message.content)
        if thinking and message.thinking:
            typer.echo("[thinking]")
            typer.echo(message.thinking)
        if tools and message.tool_calls:
            for tool_call in message.tool_calls:
                label = tool_call.tool_name
                detail = tool_call.bash_command or ""
                typer.echo(f"  [{label}] {detail}")
        typer.echo("")

    if tools and session.orphan_tool_calls:
        typer.echo("Orphan tool calls:")
        for tool_call in session.orphan_tool_calls:
            label = tool_call.tool_name
            detail = tool_call.bash_command or ""
            typer.echo(f"  [{label}] {detail}")
