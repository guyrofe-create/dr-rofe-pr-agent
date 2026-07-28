#!/usr/bin/env python3
"""Import evidence-backed consumer AI samples for the shared measurement model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reputation_core.orchestrator import load_serp_targets

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "manual_ai_samples.json"


def normalize(sample: dict, allowed: set[tuple[str, str]]) -> dict:
    key = (sample.get("engine"), sample.get("surface"))
    if key not in allowed:
        raise ValueError(f"Unconfigured AI surface: {key}")
    required = {
        "engine", "surface", "interface", "collection_method", "model",
        "country", "language", "prompt", "exact_answer", "observed_at",
    }
    missing = sorted(field for field in required if not sample.get(field))
    if missing:
        raise ValueError(f"AI sample missing fields: {missing}")
    if (
        sample["collection_method"] == "authorized_browser_sample"
        and not sample.get("screenshot_sha256")
    ):
        raise ValueError("Browser samples require screenshot_sha256 evidence")
    return {
        **sample,
        "status": sample.get("status", "observed"),
        "cited_sources": list(dict.fromkeys(sample.get("cited_sources") or [])),
        "evidence_preserved": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    config = load_serp_targets()
    allowed = {
        (item["engine"], item["surface"])
        for item in config["measurement_plan"]["ai_surfaces"]
    }
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    samples = raw if isinstance(raw, list) else raw.get("samples", [])
    normalized = [normalize(sample, allowed) for sample in samples]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"version": 1, "samples": normalized}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"imported": len(normalized), "output": str(output)}))


if __name__ == "__main__":
    main()
