"""Episode runner: one downstream-to-upstream flow, durable checkpoints, explicit selection."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import platform
import threading
import time
import uuid

from .config import APIConfig, SimulationConfig, canonical_hash
from .registry import get_condition
from .variant import variant_metadata
from .provider import Budget, EpisodeAborted, FatalAPIError, MockProvider, OpenRouterProvider

def atomic_json(path, data):
    """Replace a complete JSON snapshot, tolerating brief Windows reader locks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(min(0.05 * 2 ** attempt, 0.5))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # Preserve the original persistence error if cleanup is blocked.

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def source_fingerprint():
    root = Path(__file__).parent
    return canonical_hash({p.name: p.read_text(encoding="utf-8") for p in sorted(root.glob("*.py"))})

def episode_name(condition, seed):
    return f"{condition.id}__{condition.objective}__seed-{seed}"

def write_rows(path, rows, *, empty_columns=None):
    """Persist rows without inventing an unexecuted order for a pending decision."""
    columns = sorted(set().union(*(r.keys() for r in rows))) if rows else (empty_columns or ["t", "agent", "role"])
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})

def record_abort(folder, condition, seed, config, backend, source_hash, warmup_hash,
                 demand_hash, signature, env, provider, next_message, exc):
    """A scientific G0 abort is terminal, with partial evidence kept separately."""
    from .metrics import _usage
    rows = sorted([r for a in env.agents for r in a.history if r["t"] > config.warmup_periods],
                  key=lambda r: (r["t"], r["agent"]))
    snapshot = env.to_dict()
    details = dict(exc.details or {})
    pending = snapshot.get("pending")
    abort = {
        "status": "aborted", "terminal": True, "complete": False,
        "condition": condition.id, "objective": condition.objective, "seed": seed,
        "failure_kind": exc.failure_kind, "type": type(exc).__name__, "reason": str(exc),
        "failed_period": details.get("t", pending.get("t") if pending else None),
        "failed_agent": details.get("agent", pending.get("agent") if pending else None),
        "failed_role": details.get("role"), "failed_phase": details.get("task"),
        "error_type": details.get("error_type"), "details": details,
        "period_completed": env.period_completed,
        "completed_evaluation_periods": max(0, env.period_completed - config.warmup_periods),
        "completed_agent_periods": len(rows), "at": datetime.now(timezone.utc).isoformat(),
        "resume_policy": "terminal_abort_not_replayed",
    }
    partial = {
        "scope": "committed_evaluation_rows_before_abort_only",
        "full_horizon_comparable": False,
        "planned_evaluation_periods": config.evaluation_periods,
        "completed_evaluation_periods": abort["completed_evaluation_periods"],
        "committed_agent_periods": len(rows),
        "partial_realized_cost": sum(r["cost"] for r in rows),
        "partial_cost_components": {key: sum(r[key] for r in rows) for key in
                                    ("holding_cost", "backlog_cost", "variable_order_cost", "fixed_order_cost")},
        "pending_physical_snapshot_cost_not_included": pending is not None,
        "usage": _usage(provider.events),
        "budget_accounted_usd": sum(event.get("budget_charge_usd", 0) for event in provider.events),
    }
    result = {"condition": condition.id, "objective": condition.objective, "seed": seed,
              "backend": backend, "complete": False, "status": "aborted", "terminal": True,
              "abort_count": 1, "completion_rate": 0.0, "source_hash": source_hash,
              "variant": variant_metadata(), "warmup_hash": warmup_hash, "demand_hash": demand_hash,
              "metrics": {}, "partial_metrics": partial, "abort": abort}
    # The stopped physical state may contain a begun but uncommitted order. It is
    # evidence only, deliberately not a runnable checkpoint for --resume.
    atomic_json(folder / "abort_snapshot.json", {"signature_hash": canonical_hash(signature),
                "warmup_hash": warmup_hash, "environment": snapshot,
                "next_message": next_message, "terminal": True, "resume_allowed": False})
    atomic_json(folder / "partial_periods.json", rows)
    write_rows(folder / "partial_periods.csv", rows)
    if backend == "mock":
        atomic_json(folder / "mock_calls.json", provider.events)
    atomic_json(folder / "abort.json", abort)
    atomic_json(folder / "failure.json", abort)
    atomic_json(folder / "progress.json", {**abort, "api_attempts": len(provider.events),
                "known_cost_usd": partial["usage"]["known_reported_cost_usd_sum"]})
    atomic_json(folder / "summary.json", result)
    return result

class WarmupCache:
    def __init__(self, directory, config, source_hash):
        self.directory, self.config, self.source_hash = Path(directory), config, source_hash
        self.lock = threading.Lock()
        self.cache = {}
    def get(self, seed):
        from .engine import SupplyChain, make_warmup
        with self.lock:
            path = self.directory / f"seed-{seed}.json"
            if seed not in self.cache:
                if path.exists():
                    saved = read_json(path)
                    if saved["config_hash"] != canonical_hash(self.config) or saved["source_hash"] != self.source_hash:
                        raise ValueError("Warm-up cache does not match the current configuration/source; choose a new output folder")
                else:
                    env, demand = make_warmup(self.config, seed)
                    saved = {"seed": seed, "config_hash": canonical_hash(self.config), "source_hash": self.source_hash,
                             "demand": demand, "demand_hash": canonical_hash(demand), "snapshot": env.to_dict()}
                    saved["snapshot_hash"] = canonical_hash(saved["snapshot"])
                    atomic_json(path, saved)
                if canonical_hash(saved["snapshot"]) != saved["snapshot_hash"] or canonical_hash(saved["demand"]) != saved["demand_hash"]:
                    raise ValueError("Warm-up cache integrity check failed")
                self.cache[seed] = saved
            saved = self.cache[seed]
            return SupplyChain.from_dict(saved["snapshot"], self.config), list(saved["demand"]), saved["snapshot_hash"], saved["demand_hash"]

def run_episode(output_root, condition, seed, config, api_config, backend, budget, cache, source_hash, resume=False, stop=None):
    from .engine import SupplyChain
    from .harness import Harness
    from .metrics import summarize
    folder = Path(output_root) / "episodes" / episode_name(condition, seed)
    folder.mkdir(parents=True, exist_ok=True)
    signature = {"condition": asdict(condition), "seed": seed, "config": asdict(config),
                 "api": asdict(api_config), "backend": backend, "source_hash": source_hash,
                 "variant": variant_metadata()}
    manifest_path = folder / "manifest.json"
    if manifest_path.exists():
        existing = read_json(manifest_path)
        if existing["signature"] != signature:
            raise ValueError("Existing episode signature differs: " + str(folder))
        if not resume:
            raise ValueError("Episode already exists; use --resume or a new output folder: " + str(folder))
        if (folder / "summary.json").exists():
            saved_summary = read_json(folder / "summary.json")
            if saved_summary.get("complete") is True or saved_summary.get("status") == "aborted":
                return saved_summary
            raise ValueError("Existing episode summary is not a terminal result: " + str(folder))
    else:
        atomic_json(manifest_path, {"signature": signature, "created_at": datetime.now(timezone.utc).isoformat(),
                                   "python_version": platform.python_version()})
    lock_path = folder / ".running.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("Episode has an active/stale lock; verify its process before removing the lock: " + str(lock_path)) from None
    os.write(lock_fd, str(os.getpid()).encode())
    os.close(lock_fd)
    try:
        env, demand, warmup_hash, demand_hash = cache.get(seed)
        next_message = None
        checkpoint_path = folder / "checkpoint.json"
        if checkpoint_path.exists():
            cp = read_json(checkpoint_path)
            if cp["signature_hash"] != canonical_hash(signature) or cp["warmup_hash"] != warmup_hash:
                raise ValueError("Checkpoint signature mismatch")
            env = SupplyChain.from_dict(cp["environment"], config)
            next_message = cp["next_message"]
        provider = OpenRouterProvider(api_config, folder / "api_calls.jsonl", budget, stop=stop) if backend == "openrouter" else MockProvider()
        if backend == "mock" and (folder / "mock_calls.json").exists():
            provider.events = read_json(folder / "mock_calls.json")
        harness = Harness(config, condition, provider)
        end_period = config.warmup_periods + config.evaluation_periods
        while env.period_completed < end_period:
            if stop and stop.is_set():
                raise FatalAPIError("Run stopped after another episode failed; checkpoint retained")
            t, i = env.period_completed + 1, env.next_agent
            incoming = demand[t-1] if i == 0 else env.agents[i-1].history[-1]["Q_final"]
            if i == 0:
                next_message = None
            row = env.begin_agent(i, t, incoming)
            result = harness.decide(env, i, row, next_message)
            next_message = result["outgoing_message"]
            if backend == "mock":
                atomic_json(folder / "mock_calls.json", provider.events)
            atomic_json(checkpoint_path, {"signature_hash": canonical_hash(signature), "warmup_hash": warmup_hash,
                                         "environment": env.to_dict(), "next_message": next_message})
            atomic_json(folder / "progress.json", {"condition": condition.id, "seed": seed,
                "period_completed": env.period_completed, "next_agent": env.next_agent,
                "api_attempts": len(provider.events), "known_cost_usd": sum(x.get("reported_cost_usd") or 0 for x in provider.events),
                "updated_at": datetime.now(timezone.utc).isoformat()})
        rows = sorted([r for a in env.agents for r in a.history if r["t"] > config.warmup_periods], key=lambda r: (r["t"], r["agent"]))
        metrics = summarize(rows, provider.events, config)
        result = {"condition": condition.id, "objective": condition.objective, "seed": seed,
                  "backend": backend, "complete": True, "status": "completed", "terminal": True,
                  "abort_count": 0, "completion_rate": 1.0, "source_hash": source_hash,
                  "variant": variant_metadata(),
                  "warmup_hash": warmup_hash, "demand_hash": demand_hash, "metrics": metrics}
        atomic_json(folder / "periods.json", rows)
        write_rows(folder / "periods.csv", rows)
        atomic_json(folder / "summary.json", result)
        return result
    except EpisodeAborted as exc:
        return record_abort(folder, condition, seed, config, backend, source_hash, warmup_hash,
                            demand_hash, signature, env, provider, next_message, exc)
    except BaseException as exc:
        atomic_json(folder / "failure.json", {"type": type(exc).__name__, "message": str(exc),
                                              "at": datetime.now(timezone.utc).isoformat(), "complete": False})
        raise
    finally:
        lock_path.unlink(missing_ok=True)

def run_batch(condition_names, seeds, output, backend="mock", objective=None, workers=1,
              budget_usd=8, resume=False, config=None, api_config=None):
    config, api_config = config or SimulationConfig(), api_config or APIConfig()
    conditions = [get_condition(c, objective) for c in condition_names]
    if not conditions or not seeds or len({c.id for c in conditions}) != len(conditions) or len(set(seeds)) != len(seeds):
        raise ValueError("Select nonempty, nonduplicated conditions and seeds explicitly")
    if workers < 1 or workers > 16 or backend not in ("mock", "openrouter"):
        raise ValueError("workers must be 1..16 and backend mock/openrouter")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    source_hash = source_fingerprint()
    batch = {"conditions": [asdict(c) for c in conditions], "seeds": seeds, "backend": backend,
             "simulation": asdict(config), "api": asdict(api_config), "source_hash": source_hash,
             "budget_usd": budget_usd, "variant": variant_metadata()}
    if (root / "batch_manifest.json").exists():
        previous_batch = read_json(root / "batch_manifest.json")
        previous_scientific = {k:v for k,v in previous_batch.items() if k != "budget_usd"}
        current_scientific = {k:v for k,v in batch.items() if k != "budget_usd"}
        if previous_scientific != current_scientific:
            raise ValueError("Output folder belongs to another frozen batch; use a new folder")
        if not resume:
            raise ValueError("Batch exists; use --resume to continue")
        if budget_usd != previous_batch["budget_usd"]:
            changes_path = root / "budget_changes.json"
            changes = read_json(changes_path) if changes_path.exists() else []
            changes.append({"previous_limit": previous_batch["budget_usd"], "new_limit": budget_usd,
                            "at": datetime.now(timezone.utc).isoformat()})
            atomic_json(changes_path, changes)
            atomic_json(root / "batch_manifest.json", batch)
    else:
        atomic_json(root / "batch_manifest.json", batch)
    prior_spend = 0.0
    for p in root.glob("episodes/*/api_calls.jsonl"):
        with p.open(encoding="utf-8") as ledger:
            for line in ledger:
                prior_spend += json.loads(line).get("budget_charge_usd", 0.0)
    budget = Budget(budget_usd, prior_spend)
    cache = WarmupCache(root / "warmup", config, source_hash)
    # Build exactly one common warm-up snapshot per seed before any paid call.
    for seed in seeds:
        cache.get(seed)
    stop = threading.Event()
    results, errors = [], []
    tasks = [(condition, seed) for seed in seeds for condition in conditions]

    def save_batch_status():
        from .analysis import execution_outcomes
        results.sort(key=lambda x: (x["seed"], x["condition"]))
        outcomes = execution_outcomes(results, conditions=[c.id for c in conditions], seeds=seeds, errors=errors)
        totals = outcomes["totals"]
        all_terminal = len(results) == len(tasks) and not errors
        status = {"complete": all_terminal and totals["aborted"] == 0,
                  "terminal": all_terminal, "all_trials_terminal": all_terminal,
                  "completed": totals["completed"], "aborted": totals["aborted"],
                  "terminal_episodes": len(results), "attempted": totals["attempted"],
                  "expected": len(tasks), "unexpected_error_count": totals["unexpected_errors"],
                  "cancelled": totals["cancelled"], "budget_accounted_usd": budget.spent,
                  "completion_rate": totals["completion_rate"], "abort_rate": totals["abort_rate"],
                  "attempted_outcome_denominator": totals["attempted_outcome_denominator"],
                  "scientific_resolved_episodes": totals["scientific_resolved_episodes"],
                  "experiment_completion_rate": totals["experiment_completion_rate"],
                  "experiment_abort_rate": totals["experiment_abort_rate"],
                  "rate_denominators": outcomes["rate_denominators"],
                  "condition_outcomes": outcomes["by_condition"], "errors": errors}
        atomic_json(root / "results.json", results)
        atomic_json(root / "failures.json", outcomes["failures"])
        write_rows(root / "failures.csv", outcomes["failures"],
                   empty_columns=["condition", "seed", "status", "failure_kind", "failed_period",
                                  "failed_role", "failed_phase", "error_type", "reason"])
        atomic_json(root / "execution_outcomes.json", outcomes)
        write_rows(root / "execution_outcomes.csv", outcomes["by_condition"])
        atomic_json(root / "batch_status.json", status)
        return status

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(run_episode, root, c, s, config, api_config, backend, budget, cache, source_hash, resume, stop): (c.id, s) for c,s in tasks}
        for future in as_completed(pending):
            c, s = pending[future]
            try:
                result = future.result()
                results.append(result)
                print(json.dumps({"finished": c, "seed": s, "status": result.get("status", "completed"),
                                  "cost_per_period": result["metrics"].get("cost_per_period"),
                                  "completed_episodes": sum(r.get("complete") is True for r in results),
                                  "aborted_episodes": sum(r.get("status") == "aborted" for r in results),
                                  "total_episodes": len(tasks),
                                  "api_budget_spent_usd": round(budget.spent, 6)}), flush=True)
            except BaseException as exc:
                stop.set()
                errors.append({"condition": c, "seed": s, "type": type(exc).__name__, "message": str(exc)})
                print(json.dumps({"failed": c, "seed": s, "type": type(exc).__name__, "message": str(exc)}), flush=True)
                for other in pending:
                    other.cancel()
            save_batch_status()
    status = save_batch_status()
    if errors:
        raise RuntimeError(f"Batch incomplete: {status['completed']} completed, {status['aborted']} aborted, "
                           f"{len(tasks)} planned; inspect batch_status.json")
    return results
