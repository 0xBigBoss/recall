from __future__ import annotations

import typer

from recall.cli.utils import print_json
from recall.services import (
    bash_breakdown,
    bash_suggestions,
    overview,
    token_usage,
    tool_usage,
)

app = typer.Typer(help="Analytics commands")


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    stats = overview()
    if json_output:
        print_json(stats)
        return
    typer.echo("Overview")
    typer.echo(f"  Sessions: {stats.sessions}")
    typer.echo(f"  Messages: {stats.messages}")
    typer.echo(f"  Tool calls: {stats.tool_calls}")
    typer.echo(f"  Bash calls: {stats.bash_calls}")


@app.command("tools")
def tools(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    stats = tool_usage()
    if json_output:
        print_json(stats)
        return
    for stat in stats:
        typer.echo(f"{stat.tool_name}: {stat.count}")


@app.command("bash")
def bash(
    suggest: bool = typer.Option(False, "--suggest", help="Generate permission suggestions"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    if suggest:
        suggestions, skipped = bash_suggestions()
        if json_output:
            print_json({"suggestions": suggestions, "skipped": skipped})
            return
        typer.echo("Suggested Bash Permissions")
        typer.echo("=" * 26)
        for suggestion in suggestions:
            typer.echo(f"{suggestion.confidence}: {suggestion.pattern} ({suggestion.count} uses)")
        if skipped:
            typer.echo("Skipped")
            for item in skipped:
                typer.echo(f"- {item.pattern} ({item.count} uses): {item.reason}")
        return

    stats = bash_breakdown()
    if json_output:
        print_json(stats)
        return
    for stat in stats:
        base = stat.bash_base or "unknown"
        sub = stat.bash_sub or "*"
        suffix = " (compound)" if stat.is_compound else ""
        typer.echo(f"{base} {sub}: {stat.count}{suffix}")


@app.command("tokens")
def tokens(
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
) -> None:
    stats = token_usage()
    if json_output:
        print_json(stats)
        return
    for repo, input_tokens, output_tokens in stats:
        label = repo or "unknown"
        typer.echo(f"{label}: {input_tokens} in / {output_tokens} out")
