"""CI quality gate; evaluation completion alone does not mean acceptance."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail CI when QC02 accuracy is below 85%")
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8-sig"))
        metric = report["qc02_intent"]
        accuracy = metric["accuracy_5class"]
        total = metric["total_5class"]
        correct = metric["correct_5class"]
        if (type(accuracy) not in (int, float) or not math.isfinite(accuracy)
                or not 0 <= accuracy <= 1 or type(total) is not int or total <= 0
                or type(correct) is not int or not 0 <= correct <= total
                or abs(accuracy - correct / total) > 0.0001):
            raise ValueError("Invalid or inconsistent QC02 accuracy/counts")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"QC02 FAIL: cannot validate report: {exc}", file=sys.stderr)
        return 1
    if accuracy < 0.85:
        print(f"QC02 FAIL: {accuracy:.1%} ({correct}/{total}) < 85%", file=sys.stderr)
        return 1
    print(f"QC02 PASS: {accuracy:.1%} ({correct}/{total}) >= 85%; overall acceptance still requires other checks and human review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
