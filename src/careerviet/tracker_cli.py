"""CLI records user decisions only; apply never transmits data."""
import json
from typing import Annotated

import typer

from .applications.tracker import ApplicationTracker
from .models.application import ApplicationState

applications_app = typer.Typer(no_args_is_help=True)


def _run(ctx, operation):
    try:
        tracker = ApplicationTracker(ctx.obj['repository'])
        typer.echo(json.dumps(operation(tracker), ensure_ascii=False, indent=2))
    except (ValueError, PermissionError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None


def track(ctx: typer.Context, job_id: str,
          state: Annotated[ApplicationState | None, typer.Option('--state')] = None,
          cv: Annotated[str | None, typer.Option('--cv')] = None):
    """Inspect tracking or explicitly change state; applied requires the apply command."""
    if state == ApplicationState.APPLIED:
        raise typer.BadParameter('use apply --cv ID --confirm after manual submission')
    if state is None and cv is not None:
        raise typer.BadParameter('--cv requires --state ready')
    _run(ctx, lambda t: t.get(job_id) if state is None else
         t.transition(job_id, state.value, cv_id=cv))


def apply(ctx: typer.Context, job_id: str,
          cv: Annotated[str, typer.Option('--cv')],
          confirm: Annotated[bool, typer.Option('--confirm', help='Confirm you already manually submitted')] = False):
    """Record an already manually submitted application. Does NOT send anything."""
    _run(ctx, lambda t: t.transition(job_id, 'applied', cv_id=cv, confirm=confirm))


@applications_app.command('list')
def list_applications(ctx: typer.Context,
                      state: Annotated[ApplicationState | None, typer.Option('--state')] = None):
    _run(ctx, lambda t: t.list(state.value if state else None))


@applications_app.command('skill')
def skill():
    """Print packaged agent instructions without accessing a workspace."""
    from importlib.resources import files
    typer.echo(files('careerviet.assets.skills').joinpath('track.md').read_text())


@applications_app.command('history')
def history(ctx: typer.Context, job_id: str):
    _run(ctx, lambda t: t.history(job_id))
