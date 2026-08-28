"""Re-render an existing dashboard with the current HTML shell.

This keeps the embedded Plotly figure intact while applying the latest mobile
layout, typography, accessibility, and data-view controls from the template.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render


FIGURE_PATTERN = re.compile(
    r"const\s+figure\s*=\s*(\{.*?\});\s*(?=const\s+layout|window\.addEventListener)",
    re.DOTALL,
)


def extract_figure(html: str) -> dict:
    match = FIGURE_PATTERN.search(html)
    if not match:
        raise ValueError("Could not find the embedded `const figure = {...}` payload")
    figure = json.loads(match.group(1))
    if not isinstance(figure, dict):
        raise ValueError("Embedded Plotly figure must be a JSON object")
    return figure


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the latest dashboard template to an existing report.")
    parser.add_argument("html", type=Path, help="Existing dashboard index.html")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--created-at", default="")
    parser.add_argument("--data-source", default="")
    parser.add_argument("--dashboard-id", default="")
    parser.add_argument("--template", default="base.html.tmpl")
    args = parser.parse_args()

    source = args.html.read_text(encoding="utf-8")
    figure = extract_figure(source)
    dashboard_id = args.dashboard_id or args.html.parent.name
    polished = render.render_html(
        title=args.title,
        description=args.description,
        data_source=args.data_source,
        dashboard_id=dashboard_id,
        created_at=args.created_at,
        figure=figure,
        template_name=args.template,
    )
    args.html.write_text(polished, encoding="utf-8")
    print(args.html)


if __name__ == "__main__":
    main()
