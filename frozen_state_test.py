"""Replay selected decision snapshots under three prompts (diagnosis, not a policy trial).

Examples (run from the repository root)::

    python frozen_state_test.py results/BASE_RUN --dry-run
    python frozen_state_test.py results/BASE_RUN --backend mock --budget-usd 1 --output results/frozen_mock

Use ``--backend openrouter`` explicitly for paid calls. Source episode manifests
determine the API configuration. A new output directory is required for each run.
The original candidate thresholds and prompt additions are retained from the ZIP.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics as st

from scm.config import APIConfig, canonical_hash
from scm.forecasting import normalize_order
from scm.provider import Budget, FatalAPIError, MockProvider, OpenRouterProvider, RecoverableCallError
from scm.runner import atomic_json, source_fingerprint


QMEAN = (
    " Q_base = 0 means your on-hand inventory plus outstanding orders already cover the"
    " forecast demand for the next two periods and your current backlog; it is not a signal to build inventory."
)
LIMITATION = (
    "Selected high-overordering snapshots are replayed without advancing the supply chain. "
    "These results diagnose local response sensitivity, not overall policy cost, service or causal performance. "
    "Mock responses test plumbing only and are not LLM performance evidence."
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def collect_candidates(source_paths):
    """Keep the ZIP's retailer/C0-C2/B/P/excess thresholds, without hidden path defaults."""
    candidates = []
    seen = set()
    for source_path in source_paths:
        root = Path(source_path).resolve()
        if not root.is_dir() or not (root / "episodes").is_dir():
            raise ValueError(f"Expected a result folder containing episodes/: {root}")
        for summary_path in sorted((root / "episodes").glob("*/summary.json")):
            episode = summary_path.parent
            if episode in seen:
                continue
            seen.add(episode)
            manifest = read_json(episode / "manifest.json")
            signature = manifest["signature"]
            condition = signature["condition"]["id"]
            if not re.fullmatch(r"C[012]M[0-4]T[0-4]", condition):
                continue
            rows = {(w["t"], w["agent"]): w for w in read_json(episode / "periods.json")}
            wanted = {
                t for (t, agent), w in rows.items()
                if agent == 0 and w["B"] > 0 and w["P_pre"] >= 30
                and w["Q_base"] is not None and w["Q_final"] - w["Q_base"] >= 20
            }
            if not wanted:
                continue
            calls_path = episode / "api_calls.jsonl"
            if not calls_path.is_file():
                raise ValueError(f"Selected source episode has no original API journal: {episode}")
            with calls_path.open(encoding="utf-8") as calls:
                for line in calls:
                    event = json.loads(line)
                    if not (event.get("task") == "order" and event.get("agent") == 0
                            and event.get("success") and event.get("t") in wanted):
                        continue
                    row = rows[(event["t"], 0)]
                    payload = {k: v for k, v in event["payload"].items() if k != "retry_feedback"}
                    candidates.append({
                        "ep": condition, "seed": signature["seed"], "t": event["t"],
                        "I": row["I"], "B": row["B"], "P": row["P_pre"],
                        "Q_base": row["Q_base"], "Q_orig": row["Q_final"],
                        "instructions": event["instructions"], "payload": payload,
                        "schema": event["response_schema"], "source_episode": str(episode),
                        "source_signature": signature,
                        "source_call_key": event.get("call_key"),
                        "source_attempt": event.get("attempt"),
                        "source_retry_feedback_removed": "retry_feedback" in event["payload"],
                        "source_actual_model": event.get("actual_model"),
                        "source_actual_provider": event.get("actual_provider"),
                        "source_actual_service_tier": event.get("actual_service_tier"),
                    })
    return candidates


def variants(state):
    """The three experimental texts below are identical to the supplied ZIP."""
    ip = state["I"] + state["P"] - state["B"]
    yield "base", state["instructions"], state["payload"]
    yield "ip", state["instructions"] + (
        f" Your current inventory position is IP = I + P_pre - B = {state['I']} + {state['P']} - {state['B']} = {ip}."
        " Outstanding orders (P_pre) will still arrive; ordering more does not speed them up."), state["payload"]
    yield "qmean", state["instructions"] + QMEAN, state["payload"]


def positive_int(text):
    number = int(text)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def positive_money(text):
    number = float(text)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive amount")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("source_paths", nargs="+", type=Path, help="Completed baseline result folders containing episodes/")
    result.add_argument("--states", type=positive_int, default=12)
    result.add_argument("--reps", type=positive_int, default=3)
    result.add_argument("--dry-run", action="store_true", help="List selected snapshots; no calls or output writes")
    result.add_argument("--backend", choices=("mock", "openrouter"), help="Required unless --dry-run")
    result.add_argument("--budget-usd", type=positive_money, help="Required positive total call budget unless --dry-run")
    result.add_argument("--output", type=Path, help="Required new output directory unless --dry-run")
    return result


def append_jsonl(path, item):
    # Immediate persistence: interrupted diagnostics retain every finished replay.
    import os
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def summarize(states, results, events, budget, status, backend):
    groups = {}
    for variant in ("base", "ip", "qmean"):
        records = [r for r in results if r["variant"] == variant]
        excess = [r["excess_over_Q_base"] for r in records if r["success"]]
        groups[variant] = {
            "attempted_replays": len(records), "successful_replays": len(excess),
            "failed_replays": len(records) - len(excess),
            "mean_excess_over_Q_base": st.mean(excess) if excess else None,
            "excess_strictly_above_20_count": sum(x > 20 for x in excess),
        }
    return {
        "status": status, "backend": backend, "limitation": LIMITATION,
        "selected_states": len(states),
        "original_mean_excess_over_Q_base": st.mean(s["Q_orig"] - s["Q_base"] for s in states),
        "variants": groups, "api_attempts_including_retries": len(events),
        "reported_cost_usd_known_total": sum(e.get("reported_cost_usd") or 0 for e in events),
        "reported_cost_missing_attempts": sum(e.get("reported_cost_usd") is None for e in events),
        "budget_charge_usd": budget.spent, "budget_limit_usd": budget.limit,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None):
    args_parser = parser()
    args = args_parser.parse_args(argv)
    if not args.dry_run and any(x is None for x in (args.backend, args.budget_usd, args.output)):
        args_parser.error("An actual replay requires --backend, --budget-usd and --output (use --dry-run for inspection).")
    try:
        candidates = collect_candidates(args.source_paths)
        states = random.Random(0).sample(candidates, min(args.states, len(candidates)))
        print(f"Candidates: {len(candidates)}; selected: {len(states)}; planned logical calls: {len(states) * 3 * args.reps}")
        for state in states:
            print(f"  {state['ep']} seed {state['seed']} t{state['t']}: I={state['I']} B={state['B']} P_pre={state['P']} Q_base={state['Q_base']} original={state['Q_orig']}")
        print(LIMITATION)
        if not states:
            print("No eligible states were found. No calls were made and no result folder was created.")
            return 0
        # Do not silently replace the historical model, route or generation settings.
        api_dicts = [s["source_signature"]["api"] for s in states]
        if len({canonical_hash(api) for api in api_dicts}) != 1:
            raise ValueError("Selected episodes use different API configurations; supply separate result groups.")
        api = APIConfig(**api_dicts[0])
        if args.dry_run:
            print("Source API configuration: " + json.dumps(asdict(api), ensure_ascii=False))
            return 0
        if args.backend == "openrouter" and api.endpoint != APIConfig().endpoint:
            raise ValueError("The source endpoint is not the registered OpenRouter Responses endpoint; no credentials were sent.")
        output = args.output.resolve()
        if output.exists():
            raise ValueError(f"Output already exists; choose a new directory to avoid mixed diagnostics: {output}")
        budget = Budget(args.budget_usd)
        # Validate credentials before creating output files. Mock never needs credentials.
        provider = OpenRouterProvider(api, output / "api_calls.jsonl", budget) if args.backend == "openrouter" else MockProvider()
        output.mkdir(parents=True, exist_ok=False)
        atomic_json(output / "manifest.json", {
            "created_at": datetime.now(timezone.utc).isoformat(), "backend": args.backend,
            "source_paths": [str(p.resolve()) for p in args.source_paths],
            "source_candidate_count": len(candidates), "requested_states": args.states,
            "sample_random_seed": 0, "repetitions_per_variant": args.reps,
            "api": asdict(api), "current_default_api": asdict(APIConfig()),
            "uses_source_api_configuration": True,
            "current_defaults_differ_from_source": asdict(api) != asdict(APIConfig()),
            "budget_usd": args.budget_usd, "current_scm_source_hash": source_fingerprint(),
            "diagnostic_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "candidate_rule": "C0/C1/C2 retailer; B > 0; P_pre >= 30; Q_final - Q_base >= 20",
            "retry_feedback_policy": "Remove saved retry_feedback from every variant, including base (retains ZIP behavior).",
            "limitation": LIMITATION,
            "prompt_additions_example_state_0": {name: instruction[len(states[0]["instructions"]):]
                                                 for name, instruction, _ in variants(states[0])},
        })
        atomic_json(output / "selected_states.json", states)
        results = []
        status = "completed"
        try:
            for state_index, state in enumerate(states):
                cap = state["source_signature"]["config"]["order_cap"]
                for name, instruction, payload in variants(state):
                    for repetition in range(1, args.reps + 1):
                        meta = {"diagnostic_state_index": state_index, "variant": name, "repetition": repetition,
                                "condition": state["ep"], "seed": state["seed"], "t": state["t"], "agent": 0}
                        record = dict(meta, success=False)
                        before = len(provider.events)
                        try:
                            reply = provider.ask("order", instruction, payload, state["schema"], meta,
                                                 validate=lambda value: normalize_order(value["order_quantity"], cap))
                            quantity = normalize_order(reply["order_quantity"], cap)
                            record.update(success=True, parsed_output=reply, order_quantity=quantity,
                                          Q_base=state["Q_base"], excess_over_Q_base=quantity - state["Q_base"])
                        except RecoverableCallError as exc:
                            record.update(error_type=type(exc).__name__, error=str(exc), fallback_applied=False)
                        except FatalAPIError as exc:
                            record.update(error_type=type(exc).__name__, error=str(exc), fallback_applied=False)
                            raise
                        finally:
                            results.append(record)
                            append_jsonl(output / "replays.jsonl", record)
                            if args.backend == "mock":
                                for event in provider.events[before:]:
                                    append_jsonl(output / "mock_calls.jsonl", event)
        except BaseException:
            status = "interrupted_or_failed"
            raise
        finally:
            summary = summarize(states, results, provider.events, budget, status, args.backend)
            atomic_json(output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Saved diagnostic outputs to {output}")
        return 0
    except (ValueError, OSError, KeyError, FatalAPIError) as exc:
        args_parser.exit(1, f"Diagnostic stopped: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
