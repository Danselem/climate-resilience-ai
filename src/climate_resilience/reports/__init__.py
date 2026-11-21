"""PDF evidence reports.

A report is a rendered set of mart rows with an appendix, produced by a worker
so the HTTP path never blocks on a PDF engine.
"""

from __future__ import annotations

from .content import ReportData, collect, render_html
from .jobs import (
    Job,
    RendererUnavailable,
    claim,
    enqueue,
    fail,
    finish,
    process,
    render_pdf,
)

__all__ = [
    "Job",
    "RendererUnavailable",
    "ReportData",
    "claim",
    "collect",
    "enqueue",
    "fail",
    "finish",
    "process",
    "render_html",
    "render_pdf",
]
