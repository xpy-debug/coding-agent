"""Print the SWE-bench results in a readable form.

Two separate things are reported, because they come from different steps:

  1. what the agent produced (predictions.jsonl) -- ready right after
     run_agent.py, before any grading
  2. what the official harness scored (logs/evaluation/<run_id>/results.json)

`results.json` also lists every dataset instance you did not submit under
`incomplete_ids`, which reads like a mountain of failures. This prints the
numbers that matter and the specific tests that failed.

    python show_results.py                 # everything
    python show_results.py coding-web-v1   # one grading run
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "logs" / "evaluation"
PREDICTIONS = HERE / "predictions.jsonl"


def show_predictions() -> None:
    """What the agent produced. Grading has not looked at any of this yet."""
    print("=" * 74)
    print("agent output (predictions.jsonl)")
    print("=" * 74)
    if not PREDICTIONS.is_file():
        print("  none yet -- run run_agent.py first")
        print()
        return

    records = []
    for line in PREDICTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

    empty = [r["instance_id"] for r in records if not (r.get("model_patch") or "").strip()]
    print(f"  {len(records)} predictions ready")
    if empty:
        # Grading filters these out before it runs anything, so they never
        # appear in results.json however many times you grade.
        print(f"  {len(empty)} have an EMPTY patch and grading will drop them:")
        for instance_id in empty:
            print(f"         {instance_id}")
    print()


def show_run(run_dir: Path) -> None:
    results = run_dir / "results.json"
    if not results.is_file():
        print(f"{run_dir.name}: no results.json yet (still running?)")
        return

    data = json.loads(results.read_text(encoding="utf-8"))
    submitted = data.get("submitted_instances", 0)
    resolved = data.get("resolved_instances", 0)
    rate = f"{resolved / submitted * 100:.1f}%" if submitted else "n/a"

    print("=" * 74)
    print(f"run: {run_dir.name}")
    print("=" * 74)
    print(
        f"  submitted {submitted}   completed {data.get('completed_instances', 0)}   "
        f"resolved {resolved}   unresolved {data.get('unresolved_instances', 0)}   "
        f"rate {rate}"
    )
    for label, key in (
        ("infra failures", "infra_failure_instances"),
        ("ambiguous", "ambiguous_failure_instances"),
        ("empty patches", "empty_patch_instances"),
        ("errors", "error_instances"),
        ("leftover containers", "unstopped_instances"),
    ):
        value = data.get(key, 0)
        if value:
            print(f"  {label}: {value}  {data.get(key.replace('_instances', '_ids'), [])}")

    for model_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        for instance_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            report = instance_dir / "report.json"
            if not report.is_file():
                print(f"  {instance_dir.name:<32} (not graded yet)")
                continue
            for instance_id, info in json.loads(report.read_text(encoding="utf-8")).items():
                tests = info.get("tests_status", {})
                f2p = tests.get("FAIL_TO_PASS", {})
                p2p = tests.get("PASS_TO_PASS", {})
                mark = "PASS" if info.get("resolved") else "FAIL"
                print(
                    f"  [{mark}] {instance_id:<32} "
                    f"F2P {len(f2p.get('success', []))}/{len(f2p.get('success', [])) + len(f2p.get('failure', []))}"
                    f"   P2P {len(p2p.get('success', []))}/{len(p2p.get('success', [])) + len(p2p.get('failure', []))}"
                )
                for name in f2p.get("failure", []):
                    print(f"         target test still failing: {name}")
                for name in p2p.get("failure", []):
                    print(f"         regression: {name}")
    print()


def main() -> int:
    show_predictions()

    if not BASE.is_dir():
        print("nothing graded yet -- run evaluate.sh to score the predictions above")
        return 0
    wanted = sys.argv[1] if len(sys.argv) > 1 else None
    runs = sorted(p for p in BASE.iterdir() if p.is_dir())
    if wanted:
        runs = [p for p in runs if p.name == wanted]
    if not runs:
        print(f"no grading run named {wanted!r}", file=sys.stderr)
        return 1
    for run in runs:
        show_run(run)
    print("Per-instance detail: logs/evaluation/<run>/<model>/<instance_id>/")
    print("  report.json     -> resolved + per-test status")
    print("  test_output.txt -> raw pytest output, read this when something fails")
    print("  patch.diff      -> the exact patch that was graded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
