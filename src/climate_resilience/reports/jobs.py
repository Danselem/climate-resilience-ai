"""Report jobs and rendering.

The queue is an interface with a local implementation, because the specification
calls for SQS in AWS and the same code path locally. ``enqueue`` and ``claim``
are the whole contract: an SQS implementation sends and receives messages, this
one uses a table, and the worker does not know which it is talking to.

Rendering is separated from content so the HTML can be tested without a PDF
engine. WeasyPrint needs Pango and GObject at run time; where they are missing
the error says so instead of failing with a dlopen traceback.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, text

from ..config import Settings
from .content import collect, render_html

JOB_SCHEMA = """
create table if not exists report_job (
    job_id       text primary key,
    scope_id     text not null,
    status       text not null,
    requested_at text not null,
    started_at   text,
    finished_at  text,
    artifact     text,
    error        text
);
create index if not exists ix_report_job_status on report_job (status);
"""


class RendererUnavailable(RuntimeError):
    """Raised with an actionable message when the PDF engine cannot load."""


@dataclass(frozen=True)
class Job:
    job_id: str
    scope_id: str
    status: str


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        for statement in JOB_SCHEMA.strip().split(";"):
            if statement.strip():
                connection.execute(text(statement))


def enqueue(engine: Engine, scope_id: str) -> str:
    ensure_schema(engine)
    job_id = uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into report_job (job_id, scope_id, status, requested_at) "
                "values (:job_id, :scope_id, 'queued', datetime('now'))"
            ),
            {"job_id": job_id, "scope_id": scope_id},
        )
    return job_id


def claim(engine: Engine) -> Job | None:
    """Take the oldest queued job, atomically enough for a single worker pool."""
    ensure_schema(engine)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "update report_job set status = 'running', started_at = datetime('now') "
                "where job_id = (select job_id from report_job where status = 'queued' "
                "order by requested_at limit 1) returning job_id, scope_id, status"
            )
        ).first()
    return Job(row[0], row[1], row[2]) if row else None


def finish(engine: Engine, job_id: str, artifact: Path) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "update report_job set status = 'done', finished_at = datetime('now'), "
                "artifact = :artifact where job_id = :job_id"
            ),
            {"job_id": job_id, "artifact": str(artifact)},
        )


def fail(engine: Engine, job_id: str, error: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "update report_job set status = 'failed', finished_at = datetime('now'), "
                "error = :error where job_id = :job_id"
            ),
            {"job_id": job_id, "error": error[:500]},
        )


def render_pdf(html: str, target: Path) -> Path:
    """Render HTML to PDF, or fail with a message that names the missing library."""
    try:
        from weasyprint import HTML
    except OSError as exc:  # Pango/GObject not found
        raise RendererUnavailable(_renderer_hint(exc)) from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(target))
    return target


def _renderer_hint(exc: Exception) -> str:
    if os.uname().sysname == "Darwin":
        return (
            "PDF rendering needs Pango and GObject, which WeasyPrint loads at run "
            "time. On macOS install them with `brew install pango` and run with "
            "DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib. The container image "
            f"installs them already. Underlying error: {exc}"
        )
    return (
        "PDF rendering needs Pango and GObject. On Debian install "
        "`libpango-1.0-0 libpangocairo-1.0-0`. The container image installs them "
        f"already. Underlying error: {exc}"
    )


def process(engine: Engine, settings: Settings, job: Job) -> Path:
    """Build one report and write it, with a sidecar JSON of its envelopes."""
    data = collect(engine, job.scope_id)
    html = render_html(data, run_id=job.job_id)
    target = settings.data_dir / "reports" / f"{job.job_id}.pdf"
    render_pdf(html, target)
    sidecar = target.with_suffix(".json")
    sidecar.write_text(
        "{\n"
        f'  "job_id": "{job.job_id}",\n'
        f'  "scope_id": "{job.scope_id}",\n'
        f'  "generated_at": "{data.generated_at.isoformat()}",\n'
        '  "envelopes": [\n'
        + ",\n".join(
            "    " + envelope.model_dump_json() for _, envelope in data.rows
        )
        + "\n  ]\n}\n",
        encoding="utf-8",
    )
    return target
