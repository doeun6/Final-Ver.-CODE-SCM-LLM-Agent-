"""Run core then remaining conditions for both, qmean, and safety-stock 10.

There are SIX separate batches (12/91 conditions times three settings).
--budget-per-batch-usd is not a combined budget: the combined ceiling is six
times that amount, shared across all selected seeds within each batch.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from variant_support import (REPO_ROOT, nonnegative_int, positive_int,
                             positive_real, repository_path,
                             validate_selection, worker_count)


CORE = "C0M0T2 C1M0T2 C2M0T2 C3M0T2 C0M1T2 C0M2T2 C0M3T2 C0M4T2 C0M0T0 C0M0T1 C0M0T3 C0M0T4".split()
SETTINGS = [("both", "run_qmean.py", "10"),
            ("qmean", "run_qmean.py", "0"),
            ("ss10", "run_variant.py", "10")]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--backend", choices=("mock", "openrouter"), required=True)
    parser.add_argument("--workers", type=worker_count, default=14)
    parser.add_argument("--budget-per-batch-usd", type=positive_real, default=15)
    parser.add_argument("--output-root", type=Path, default=Path("results"))
    parser.add_argument("--initial-inventory", type=nonnegative_int, default=0)
    parser.add_argument("--evaluation-periods", type=positive_int, default=100)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="print and validate all six batches without API requests or output files")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.tag):
        parser.error("--tag must use letters, digits, underscore, dot or hyphen, starting with a letter/digit")
    with (REPO_ROOT / "configs" / "registered_conditions.json").open(encoding="utf-8-sig") as stream:
        # This legacy six-batch launcher still targets the original 103 design.
        # Minimal controls are selected explicitly through run_final.py.
        ids = [c["id"] for c in json.load(stream) if c["id"] not in ("N0", "N0-G0")]
    validate_selection(ids, args.seeds)
    if len(ids) != 103 or not set(CORE).issubset(ids):
        raise ValueError("Expected the complete 103-condition registry including all core conditions")
    rest = [name for name in ids if name not in CORE]
    output_root = repository_path(args.output_root)
    jobs = []
    for phase, conditions in (("core", CORE), ("rest", rest)):
        for name, script, safety in SETTINGS:
            output = output_root / f"{phase}_{name}_{args.tag}"
            command = [sys.executable, str(REPO_ROOT / script),
                       "--conditions", *conditions,
                       "--seeds", *map(str, args.seeds),
                       "--backend", args.backend,
                       "--safety-stock", safety,
                       "--initial-inventory", str(args.initial_inventory),
                       "--evaluation-periods", str(args.evaluation_periods),
                       "--workers", str(args.workers),
                       "--budget-usd", str(args.budget_per_batch_usd),
                       "--output", str(output)]
            if args.resume:
                command.append("--resume")
            jobs.append({"phase": phase, "setting": name, "conditions": len(conditions),
                         "output": str(output), "command": command})
    print(json.dumps({
        "batches": len(jobs), "episodes": len(ids) * len(args.seeds) * len(SETTINGS),
        "backend": args.backend, "seeds": args.seeds,
        "budget_per_batch_usd": args.budget_per_batch_usd,
        "combined_budget_ceiling_usd": len(jobs) * args.budget_per_batch_usd,
        "budget_note": "Six independent batch caps, not one shared cap; each cap covers all selected seeds in that batch.",
        "dry_run": args.dry_run,
        "jobs": [{k: v for k, v in job.items() if k != "command"} for job in jobs],
    }, ensure_ascii=False, indent=2), flush=True)
    # Preflight ALL destinations before any paid work. A mismatch in a late batch
    # must not cause earlier batches to incur costs before the error is noticed.
    preflight_failed = False
    for job in jobs:
        print(f"PREFLIGHT {job['phase']} {job['setting']}", flush=True)
        result = subprocess.run(job["command"] + ["--dry-run"], cwd=REPO_ROOT, check=False)
        if result.returncode:
            preflight_failed = True
            print(f"Preflight failed ({result.returncode}): {job['output']}", file=sys.stderr)
    if preflight_failed:
        return 1
    if args.dry_run:
        return 0
    results = []
    for job in jobs:
        print(f"RUN {job['phase']} {job['setting']}", flush=True)
        result = subprocess.run(job["command"], cwd=REPO_ROOT, check=False)
        results.append({"phase": job["phase"], "setting": job["setting"],
                        "output": job["output"], "returncode": result.returncode})
    print(json.dumps({"batch_results": results,
                      "complete": all(r["returncode"] == 0 for r in results)},
                     ensure_ascii=False, indent=2), flush=True)
    return 0 if all(r["returncode"] == 0 for r in results) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
