"""Pick a reproducible subset of SWE-bench Lite and write instances.json.

Runs inside the harness image, because it needs `datasets` and `swebench`. It
deliberately reuses the harness's own loader rather than calling `datasets`
directly, so the field names cannot drift away from what grading expects.

The output feeds the agent runner on the host. Only the fields the runner needs
survive; every oracle field is dropped, so a leaked file cannot hand the agent
the answer.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

DEFAULT_DATASET = "SWE-bench/SWE-bench_Lite"
DEFAULT_SPLIT = "test"

# Everything the agent runner needs, and nothing more.
KEEP = ("instance_id", "repo", "base_commit", "problem_statement", "version")

# Must never appear in the output: these either contain the answer or describe
# how it is graded. `hints_text` holds human hints from the issue thread and is
# withheld in the standard no-hints setting.
ORACLE = frozenset(
    {
        "patch",
        "test_patch",
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "eval_script",
        "log_parser",
        "eval_type",
        "image",
        "image_assets",
        "hints_text",
    }
)


def load_dataset(dataset: str, split: str) -> tuple[list[dict], str]:
    """Load the dataset, preferring the harness's own loader.

    Falls back to Hugging Face's dataset-viewer API when `swebench` is not
    importable, which happens on the host where the harness image is not in play.
    The fallback reads the same rows the official loader would, but its field
    names come from the dataset viewer, so the harness loader stays the
    authoritative path whenever it is available.
    """
    try:
        from swebench.harness.utils import load_swebench_dataset
    except ImportError:
        return _load_via_dataset_viewer(dataset, split), "hf dataset-viewer (fallback)"
    return list(load_swebench_dataset(dataset, split)), "swebench harness loader"


def _load_via_dataset_viewer(dataset: str, split: str, page: int = 100) -> list[dict]:
    from urllib.parse import quote
    from urllib.request import urlopen

    rows: list[dict] = []
    offset = 0
    while True:
        url = (
            f"https://datasets-server.huggingface.co/rows?dataset={quote(dataset)}"
            f"&config=default&split={quote(split)}&offset={offset}&length={page}"
        )
        with urlopen(url, timeout=120) as response:
            payload = json.load(response)
        batch = payload.get("rows") or []
        if not batch:
            break
        rows.extend(item["row"] for item in batch)
        offset += len(batch)
        if offset >= (payload.get("num_rows_total") or 0):
            break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help=f"Dataset name (default: {DEFAULT_DATASET})")
    parser.add_argument("--split", default=DEFAULT_SPLIT, help=f"Split (default: {DEFAULT_SPLIT})")
    parser.add_argument("--count", type=int, default=15, help="How many instances to sample (default: 15)")
    parser.add_argument("--seed", type=int, default=0, help="Sampling seed, for reproducibility (default: 0)")
    parser.add_argument("--out", default="instances.json", help="Where to write the sample (default: instances.json)")
    parser.add_argument(
        "--instance-ids",
        nargs="*",
        default=None,
        help="Take exactly these instance IDs instead of sampling.",
    )
    parser.add_argument(
        "--difficulty",
        default=None,
        help="Only instances carrying this difficulty label, e.g. '1-4 hours'.",
    )
    parser.add_argument(
        "--list-difficulties",
        action="store_true",
        help="Print the difficulty labels and their counts, then exit.",
    )
    args = parser.parse_args()

    try:
        dataset, source = load_dataset(args.dataset, args.split)
    except ImportError as exc:  # pragma: no cover - depends on environment
        print(f"Could not load {args.dataset}: {exc}", file=sys.stderr)
        return 2
    print(f"Loading {args.dataset} (split={args.split}) via {source}...")
    print(f"  {len(dataset)} instances available")

    full = dataset
    if args.list_difficulties:
        counts = Counter(inst.get("difficulty", "") for inst in full)
        print("difficulty labels (unlabelled included):")
        for label, n in sorted(counts.items()):
            print(f"  {n:>4}  {label or '(unlabelled)'}")
        return 0

    if args.difficulty is not None:
        # Only 93 of the 300 Lite instances carry a difficulty label at all; the
        # rest are unannotated rather than easy.
        dataset = [inst for inst in full if inst.get("difficulty") == args.difficulty]
        if not dataset:
            labels = sorted({inst["difficulty"] for inst in full if inst.get("difficulty")})
            print(f"No instances with difficulty {args.difficulty!r}.", file=sys.stderr)
            print(f"Available labels: {labels}", file=sys.stderr)
            return 2
        print(f"  {len(dataset)} instances labelled {args.difficulty!r}")

    if args.instance_ids:
        by_id = {inst["instance_id"]: inst for inst in dataset}
        missing = [i for i in args.instance_ids if i not in by_id]
        if missing:
            print(f"Not in the dataset: {' '.join(missing)}", file=sys.stderr)
            return 2
        chosen = [by_id[i] for i in args.instance_ids]
    else:
        if args.count > len(dataset):
            print(f"--count {args.count} exceeds the {len(dataset)} available", file=sys.stderr)
            return 2
        # Sorted first so the sample depends only on --seed, not on dataset order.
        ordered = sorted(dataset, key=lambda d: d["instance_id"])
        chosen = random.Random(args.seed).sample(ordered, args.count)
        chosen.sort(key=lambda d: d["instance_id"])

    picks = []
    for inst in chosen:
        absent = [key for key in KEEP if key not in inst]
        if absent:
            print(f"{inst.get('instance_id')}: missing {absent}", file=sys.stderr)
            return 2
        picks.append({key: inst[key] for key in KEEP})

    leaked = sorted({key for pick in picks for key in pick if key in ORACLE})
    if leaked:  # pragma: no cover - a bug in KEEP, not a runtime condition
        print(f"Refusing to write: oracle fields present: {leaked}", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.write_text(json.dumps(picks, indent=2) + "\n", encoding="utf-8")

    repos = Counter(pick["repo"] for pick in picks)
    print(f"\nWrote {len(picks)} instances to {out}")
    for repo, n in sorted(repos.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {n:>2}  {repo}")
    print(f"\nNext: python run_agent.py --instances {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
