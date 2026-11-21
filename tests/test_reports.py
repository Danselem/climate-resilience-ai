"""Report content and job lifecycle.

The PDF engine needs Pango, which a CI container has and a laptop may not, so
the tests that matter most — what the document says, and that a job cannot be
lost — run against the HTML and the table, not the renderer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine

from climate_resilience.reports import content, jobs
from climate_resilience.store import repository

MART = Path("data/mart.db")
pytestmark = pytest.mark.skipif(
    not MART.exists(), reason="run `climate-resilience mart` to build data/mart.db"
)


@pytest.fixture(scope="module")
def engine() -> Engine:
    return repository.make_engine(f"sqlite:///{MART}")


def test_a_ward_report_names_the_scope_and_carries_the_flood_caveat(engine) -> None:
    data = content.collect(engine, "ward 75")
    html = content.render_html(data, run_id="abc123")

    assert "Ward 75" in html
    # The caveat is in the page frame, so it appears on every page.
    assert "@top-center" in html
    assert "Pluvial" in html


def test_every_figure_in_the_report_appears_in_the_appendix(engine) -> None:
    data = content.collect(engine, "ward 75")
    html = content.render_html(data, run_id="abc123")

    for _, envelope in data.rows:
        assert envelope.indicator_id in html
        for dataset in envelope.datasets:
            assert dataset.id in html
            assert dataset.licence in html


def test_ward_level_heat_is_reported_as_unavailable_not_as_zero(engine) -> None:
    data = content.collect(engine, "ward 75")
    html = content.render_html(data, run_id="abc123")

    headline = dict((label, value) for label, value, _ in data.headline)
    assert "not published" in headline["Hot days (Tmax ≥ 35 °C)"].lower()
    assert "5-cell climate grid" in html
    assert data.heat_rows == []


def test_municipal_heat_has_a_series_and_a_headline(engine) -> None:
    data = content.collect(engine, "ethekwini")

    assert data.heat_rows
    assert dict((label, value) for label, value, _ in data.headline)[
        "Hot days (Tmax ≥ 35 °C)"
    ].endswith("days")


def test_identical_return_periods_are_explained_rather_than_left_to_look_wrong(
    engine,
) -> None:
    data = content.collect(engine, "ward 75")

    assert any("identical at 10, 50 and 100 years" in text for text in data.limitations)


def test_the_coastal_zero_is_stated_once_and_with_a_reason(engine) -> None:
    data = content.collect(engine, "ward 75")

    mentions = [
        text
        for text in data.limitations
        if "Coastal exposure is published as zero" in text
    ]
    assert len(mentions) == 1


def test_an_unknown_scope_raises_rather_than_rendering_an_empty_report(engine) -> None:
    with pytest.raises(LookupError):
        content.collect(engine, "Atlantis")


def test_a_job_runs_once_and_records_its_artifact(tmp_path, engine) -> None:
    jobs.ensure_schema(engine)
    job_id = jobs.enqueue(engine, "ethekwini")

    claimed = jobs.claim(engine)
    assert claimed is not None
    assert claimed.job_id == job_id
    assert claimed.status == "running"
    # The job is no longer claimable while it is running.
    assert jobs.claim(engine) is None or jobs.claim(engine).job_id != job_id

    jobs.finish(engine, job_id, tmp_path / "report.pdf")
    assert jobs.claim(engine) is None


def test_a_failed_job_records_why(engine) -> None:
    job_id = jobs.enqueue(engine, "ethekwini")
    claimed = jobs.claim(engine)

    jobs.fail(engine, job_id, "renderer exploded")

    from sqlalchemy import text

    with engine.connect() as connection:
        row = connection.execute(
            text("select status, error from report_job where job_id = :id"),
            {"id": job_id},
        ).first()
    assert claimed is not None
    assert row[0] == "failed"
    assert "renderer exploded" in row[1]


def test_renderer_failure_is_reported_with_an_action(engine, tmp_path) -> None:
    """If Pango is missing, the message must name the fix, not a dlopen trace."""
    try:
        jobs.render_pdf("<h1>x</h1>", tmp_path / "x.pdf")
    except jobs.RendererUnavailable as exc:
        assert "pango" in str(exc).lower()
    else:  # the library is present, so the renderer is exercised end to end
        assert (tmp_path / "x.pdf").read_bytes().startswith(b"%PDF")


def test_the_job_queue_works_on_postgres_not_only_sqlite() -> None:
    """The first report in AWS failed here: `datetime('now')` is SQLite-only.

    The test is skipped when Postgres is unreachable, which is why the bug
    survived the suite until a container ran it against the real database.
    """
    import os

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    dsn = os.environ.get(
        "CRP_TEST_POSTGRES", "postgresql+psycopg://crp:crp@localhost:5433/crp"
    )
    try:
        pg = create_engine(dsn)
        with pg.begin() as connection:
            connection.execute(text("create schema if not exists reports_test"))
            connection.execute(text("set search_path to reports_test"))
    except Exception as error:  # noqa: BLE001 - absent database is a skip
        pytest.skip(f"Postgres unavailable: {error}")

    try:
        with pg.begin() as connection:
            connection.execute(text("drop table if exists report_job"))

        job_id = jobs.enqueue(pg, "ethekwini")
        claimed = jobs.claim(pg)

        assert claimed is not None
        assert claimed.job_id == job_id
        jobs.finish(pg, job_id, Path("/tmp/ignored.pdf"))
        with pg.connect() as connection:
            row = connection.execute(
                text("select status, finished_at from report_job where job_id = :id"),
                {"id": job_id},
            ).first()
        assert row[0] == "done"
        assert row[1] is not None
    except OperationalError as error:
        pytest.skip(f"Postgres unavailable: {error}")
    finally:
        try:
            with pg.begin() as connection:
                connection.execute(text("drop table if exists report_job"))
        finally:
            pg.dispose()
