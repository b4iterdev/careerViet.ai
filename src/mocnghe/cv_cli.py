"""M4 CLI entry points; all output is local unless explicit provider consent is given."""
import json
import os
import sqlite3
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from reportlab.platypus.doctemplate import LayoutError

from .application_drafts import ApplicationDraftService
from .cv import CVService
from .cv_render import export_cv, publish_bundle
from .cv_runtime import create_packet, import_response, run_provider
from .evaluation_runtime import EvaluationProviderConfig

cv_app = typer.Typer(no_args_is_help=True)
draft_app = typer.Typer(no_args_is_help=True)


def guarded(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValidationError:
            typer.echo("Invalid structured input; review field types and evidence contracts.", err=True)
            raise typer.Exit(1) from None
        except (ValueError, OSError, RuntimeError, sqlite3.Error, LayoutError) as exc:
            typer.echo(f"Operation failed: {exc}", err=True)
            raise typer.Exit(1) from None
    return wrapped


def service(ctx):
    return CVService(ctx.obj["repository"])


def emit(value):
    typer.echo(value.model_dump_json(indent=2))


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("input exceeds 1 MB")
    return json.loads(raw)


@cv_app.command("create")
@guarded
def create(ctx: typer.Context, profile_version: Annotated[str, typer.Option()],
           evidence: Annotated[list[str], typer.Option(help="Repeat to select evidence IDs")],
           language: Annotated[str, typer.Option(help="en or vi; source wording is not auto-translated")],
           job_id: Annotated[str | None, typer.Option()] = None,
           identity: Annotated[list[str] | None, typer.Option(help="Explicit local identity fields")] = None):
    emit(service(ctx).create(profile_version, evidence, language=language, job_id=job_id,
                             identity_keys=identity or []))


@cv_app.command("review")
@guarded
def review(ctx: typer.Context, cv_id: str):
    s = service(ctx)
    cv = s.get(cv_id)
    typer.echo(json.dumps({"cv": cv.model_dump(mode="json"), "content_hash": s.content_hash(cv),
                           "approved": s.approved(cv_id)}, ensure_ascii=False, indent=2))


@cv_app.command("list")
@guarded
def list_cvs(ctx: typer.Context):
    s = service(ctx)
    with s.repo.connect() as db:
        ids = [r[0] for r in db.execute("SELECT id FROM cv_revisions ORDER BY rowid")]
    typer.echo(json.dumps(ids))


@cv_app.command("revise")
@guarded
def revise(ctx: typer.Context, cv_id: str, claims: Annotated[Path, typer.Option()]):
    """Create an unapproved revision from a JSON array of claims."""
    emit(service(ctx).revise(cv_id, read_json(claims), provenance="human-proposed"))


@cv_app.command("approve")
@guarded
def approve(ctx: typer.Context, cv_id: str,
            content_hash: Annotated[str, typer.Option("--hash", help="Exact hash from review")]):
    service(ctx).approve(cv_id, content_hash)
    typer.echo("Approved reviewed CV content; not submitted.")


@cv_app.command("export")
@guarded
def export(ctx: typer.Context, cv_id: str, output: Annotated[Path, typer.Option()],
           max_pages: Annotated[int, typer.Option(min=1, max=10)] = 2):
    export_cv(service(ctx), cv_id, output, max_pages=max_pages)
    typer.echo(f"Exported CV bundle: {output}")


@cv_app.command("export-packet")
@guarded
def export_packet(ctx: typer.Context, cv_id: str, output: Annotated[Path, typer.Option()],
                  consent: Annotated[bool, typer.Option(help="Agent may be remote; evidence leaves device")] = False):
    packet = create_packet(service(ctx), cv_id, consent=consent)
    publish_bundle(output, {"packet.json": json.dumps(packet, ensure_ascii=False, indent=2).encode()})
    typer.echo(f"Exported tailoring packet: {output}")


@cv_app.command("import-response")
@guarded
def import_tailoring(ctx: typer.Context, cv_id: str, response: Annotated[Path, typer.Option()]):
    emit(import_response(service(ctx), cv_id, read_json(response), provenance="cli-agent"))


@cv_app.command("provider")
@guarded
def provider(ctx: typer.Context, cv_id: str,
             consent: Annotated[bool, typer.Option(help="Transmit selected evidence/JD to configured provider")] = False):
    config = EvaluationProviderConfig.from_env(os.environ)
    # Deliberately never print full endpoint (could contain secrets) or API key.
    from urllib.parse import urlsplit
    parsed = urlsplit(config.endpoint)
    typer.echo(f"Destination host: {parsed.hostname}; model: {config.model}", err=True)
    typer.echo("Data: selected evidence quotes/wording and optional JD. Identity fields omitted.", err=True)
    emit(run_provider(service(ctx), cv_id, config, consent=consent))


@cv_app.command("skill")
def skill():
    typer.echo(files("mocnghe.assets").joinpath("skills/tailor.md").read_text())


@draft_app.command("create")
@guarded
def create_draft(ctx: typer.Context, cv_id: str, job_id: Annotated[str, typer.Option()],
                 subject: Annotated[str, typer.Option(help="Exact subject specified by user/employer")],
                 route: Annotated[str, typer.Option(help="Exact application route; never followed automatically")],
                 questions: Annotated[Path | None, typer.Option()] = None):
    data = read_json(questions) if questions else {"questions": [], "answers": {}}
    if not isinstance(data, dict) or set(data) - {"questions", "answers"}:
        raise ValueError("questions input needs only questions and answers fields")
    emit(ApplicationDraftService(service(ctx)).create(cv_id, job_id, subject=subject, route=route,
                    questions=data.get("questions", []), answers=data.get("answers", {})))


@draft_app.command("review")
@guarded
def review_draft(ctx: typer.Context, draft_id: str):
    s = ApplicationDraftService(service(ctx))
    draft = s.get(draft_id)
    typer.echo(json.dumps({"draft": draft.model_dump(mode="json"),
                           "content_hash": s.content_hash(draft)}, ensure_ascii=False, indent=2))


@draft_app.command("approve")
@guarded
def approve_draft(ctx: typer.Context, draft_id: str,
                  content_hash: Annotated[str, typer.Option("--hash")]):
    ApplicationDraftService(service(ctx)).approve(draft_id, content_hash)
    typer.echo("Approved local application draft; not submitted.")


@draft_app.command("export")
@guarded
def export_draft(ctx: typer.Context, draft_id: str, output: Annotated[Path, typer.Option()]):
    ApplicationDraftService(service(ctx)).export(draft_id, output)
    typer.echo(f"Exported local application draft: {output}")
