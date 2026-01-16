from __future__ import annotations

import typer

from recall.cli import index as index_cmd
from recall.cli import list as list_cmd
from recall.cli import search as search_cmd
from recall.cli import show as show_cmd
from recall.cli.stats import app as stats_app

app = typer.Typer(add_completion=False)

app.command("index")(index_cmd.command)
app.command("search")(search_cmd.command)
app.command("list")(list_cmd.command)
app.command("show")(show_cmd.command)
app.add_typer(stats_app, name="stats")


if __name__ == "__main__":
    app()
