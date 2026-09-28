"""Validate the PSX official-report manifest and print its publication gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.providers.stock_fundamentals import (
    OfficialReportManifestProvider,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate source hosts, provenance, units, duplicate periods, "
            "accounting identities, and human-review publication rules."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("data/psx/psx_fundamentals.candidate.json"),
    )
    parser.add_argument(
        "--require-all-approved",
        action="store_true",
        help="Fail unless every company is human-approved and publishable.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        provider = OfficialReportManifestProvider.from_file(args.path)
    except (OSError, ValueError, json.JSONDecodeError, ValidationError) as error:
        print(f"INVALID: {error}")
        return 1

    summary = provider.publication_summary
    print(summary.model_dump_json(indent=2))
    if args.require_all_approved and summary.approved != summary.total:
        print("NOT PUBLISHABLE: one or more companies still require human review.")
        return 2
    print("VALID: schema and automated consistency checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
