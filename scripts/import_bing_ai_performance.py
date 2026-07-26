#!/usr/bin/env python3
"""Import a customer-authorized Bing AI Performance CSV/JSON export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reputation_core.bing_ai_performance import import_bing_ai_performance
from reputation_core.installation import data_path
from reputation_core.measurement import summarize_bing_ai_performance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Defaults to installation data/bing_ai_performance.json",
    )
    args = parser.parse_args()
    dataset = import_bing_ai_performance(args.input)
    output = args.output or data_path("bing_ai_performance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = summarize_bing_ai_performance(dataset)
    print(f"Imported {len(dataset['rows'])} Bing AI Performance rows.")
    print(f"Total citations: {summary['total_citations']}")
    print(f"Unique cited pages: {summary['unique_cited_pages']}")
    print(f"Unique grounding queries: {summary['unique_grounding_queries']}")
    print(f"Saved: {output.resolve()}")
    print("Collection method: authorized UI export; not an undocumented API.")


if __name__ == "__main__":
    main()
