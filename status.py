"""Read terminal episode summaries only: python status.py results/pilot.

No active progress, checkpoint, or API ledger is opened. Completed and aborted
episodes are separate; their API costs are not live whole-batch totals.
Supply-chain costs remain separate for each condition/seed; they are copied from
saved metrics, not summed across experiments or combined with API costs in USD.
"""
import json
from pathlib import Path
import sys
from scm.analysis import execution_outcomes


def completed_status(root):
    root = Path(root)
    manifest_path = root / "batch_manifest.json"
    if not manifest_path.exists():
        raise SystemExit("No batch_manifest.json in " + str(root))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = len(manifest["conditions"]) * len(manifest["seeds"])
    completed, aborted = [], []
    for path in sorted(root.glob("episodes/*/summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("complete") is True:
            completed.append(summary)
        elif summary.get("status") == "aborted":
            aborted.append(summary)
    costs = [summary["metrics"]["reported_cost_usd"] for summary in completed]
    known_cost = sum(summary["metrics"]["known_reported_cost_usd_sum"]
                     for summary in completed)
    outcomes = execution_outcomes(completed + aborted,
                                  conditions=[item["id"] for item in manifest["conditions"]],
                                  seeds=manifest["seeds"])
    aborted_known_cost = sum(item.get("partial_metrics", {}).get("usage", {}).get("known_reported_cost_usd_sum", 0)
                             for item in aborted)
    return {
        "scope": "completed_episode_summaries_only",
        "terminal_status_scope": "completed_and_aborted_summaries_only_no_active_files",
        "completed_episodes": len(completed),
        "aborted_episodes": len(aborted),
        "terminal_episodes": len(completed) + len(aborted),
        "all_trials_terminal": len(completed) + len(aborted) == planned,
        "all_episodes_completed": len(completed) == planned,
        "condition_outcomes": outcomes["by_condition"],
        "rate_denominators": outcomes["rate_denominators"],
        "experiment_completion_rate": outcomes["totals"]["experiment_completion_rate"],
        "experiment_abort_rate": outcomes["totals"]["experiment_abort_rate"],
        "aborted": outcomes["failures"],
        "aborted_episodes_known_api_cost_subtotal_usd": round(aborted_known_cost, 6),
        "terminal_episodes_known_api_cost_subtotal_usd": round(known_cost + aborted_known_cost, 6),
        "planned_episodes": planned,
        "completed_episode_percent": round(100 * len(completed) / planned, 2) if planned else None,
        "completed_episodes_reported_cost_usd": round(sum(costs), 6) if all(cost is not None for cost in costs) else None,
        "completed_episodes_known_cost_subtotal_usd": round(known_cost, 6),
        "completed_episodes_missing_cost_reports": sum(cost is None for cost in costs),
        "unfinished_episode_progress_included": False,
        "unfinished_episode_spend_included": False,
        "note": "Active episodes are excluded. Completed and aborted episodes are counted separately. Completed supply-chain metrics exclude aborted trials; their partial costs are not comparable with full-horizon costs. USD fields explicitly identify completed/aborted/terminal scope and are not live total spend.",
        "completed": [{**{key: summary[key] for key in ("condition", "seed")},
                       **{key: summary["metrics"].get(key)
                          for key in ("total_cost", "cost_per_period", "periods_evaluated")}}
                      for summary in completed],
    }


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    root = arguments[0] if arguments else "results/pilot"
    print(json.dumps(completed_status(root), indent=2))


if __name__ == "__main__":
    main()
