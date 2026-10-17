"""Safe, explicit runtime interventions without changing the registered scm files.

The runtime fingerprint includes the intervention and its wrapper sources. This
also makes the ordinary scm runner reject a resume into an intervention folder.
"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import threading

from scm import prompts, runner
from scm.config import APIConfig, SimulationConfig, canonical_hash
from scm.registry import get_condition


REPO_ROOT = Path(__file__).resolve().parent
MANIFEST_NAME = "intervention_manifest.json"
LOCK_NAME = ".intervention.running.lock"
_PATCH_LOCK = threading.Lock()


def nonnegative_real(text):
    try:
        value = float(text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number") from exc
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number")
    return value


def positive_real(text):
    value = nonnegative_real(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def nonnegative_int(text):
    try:
        value = int(text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from exc
    if str(value) != str(text).strip() and not isinstance(text, int):
        # Accept a leading + and zero padding, but never decimal quantities.
        if not str(text).strip().lstrip("+").isdigit():
            raise argparse.ArgumentTypeError("must be a nonnegative integer")
    if value < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return value


def positive_int(text):
    value = nonnegative_int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least one")
    return value


def worker_count(text):
    value = positive_int(text)
    if value > 16:
        raise argparse.ArgumentTypeError("the unchanged scm runner supports workers 1..16")
    return value


def add_common_arguments(parser, default_budget, require_safety_stock=False):
    parser.add_argument("--conditions", nargs="+", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument("--backend", choices=("mock", "openrouter"), required=True)
    parser.add_argument("--objective", choices=("cost", "bullwhip"))
    parser.add_argument("--output", type=Path, required=True,
                        help="relative paths are resolved from the repository root")
    parser.add_argument("--workers", type=worker_count, default=1)
    parser.add_argument("--budget-usd", type=positive_real, default=default_budget)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--safety-stock", type=nonnegative_real, default=0.0,
                        required=require_safety_stock)
    parser.add_argument("--initial-inventory", type=nonnegative_int, default=0)
    parser.add_argument("--evaluation-periods", type=positive_int, default=100,
                        help="values other than 100 are diagnostic runs")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and print the plan; no API calls or output files")


def repository_path(path):
    path = Path(path).expanduser()
    return (path if path.is_absolute() else REPO_ROOT / path).resolve()


def validate_selection(conditions, seeds, objective=None):
    resolved = [get_condition(name, objective) for name in conditions]
    if not resolved or len({c.id for c in resolved}) != len(resolved):
        raise ValueError("Select nonempty, nonduplicated conditions")
    if not seeds or any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("Select nonempty, nonduplicated integer seeds")
    return resolved


def estimated_calls(conditions, seeds, evaluation_periods):
    calls_per_period = sum(
        4 * (1 + {"T0": 1, "T1": 1, "T2": 0, "T3": 2, "T4": 1, None: 0}[c.t])
        + (3 if c.m in ("M2", "M3", "M4") else 0)
        for c in conditions
    )
    return calls_per_period * len(seeds) * evaluation_periods


def _signature(args, wrapper_file, intervention, qmean_sentence):
    conditions = validate_selection(args.conditions, args.seeds, args.objective)
    # Validate programmatic callers as well as argparse callers.
    worker_count(args.workers)
    positive_real(args.budget_usd)
    initial = nonnegative_int(args.initial_inventory)
    safety = nonnegative_real(args.safety_stock)
    evaluation = positive_int(args.evaluation_periods)
    if args.backend not in ("mock", "openrouter"):
        raise ValueError("backend must be mock or openrouter")
    config = SimulationConfig(safety_stock=safety, initial_inventory=initial,
                              evaluation_periods=evaluation)
    api = APIConfig()
    sources = {}
    for path in sorted({Path(__file__).resolve(), Path(wrapper_file).resolve()}):
        sources[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    source_hash = runner.source_fingerprint()
    intervention_spec = {
        "name": intervention,
        "q_base_meaning_sentence": qmean_sentence,
        "q_base_sentence_scope": "100 CMT order-up-to conditions only; A, both D references, N0 and N0-G0 excluded",
        "safety_stock_scope": "warm-up from period 1 and evaluation; shared only within the same configuration",
        "wrapper_sources_sha256": sources,
        "wrapper_sources_hash": canonical_hash(sources),
    }
    runtime_hash = canonical_hash({"scm_source_hash": source_hash, "intervention": intervention_spec})
    signature = {
        "format_version": 1,
        "intervention": intervention_spec,
        "scm_source_hash": source_hash,
        "runtime_source_hash": runtime_hash,
        "conditions": [asdict(c) for c in conditions],
        "seeds": list(args.seeds),
        "simulation": asdict(config),
        "api": asdict(api),
        "backend": args.backend,
    }
    return signature, config, api, conditions


def _check_folder(root, signature, resume):
    if not root.exists():
        return
    if not root.is_dir():
        raise ValueError("Output must be a directory: " + str(root))
    manifest = root / MANIFEST_NAME
    if manifest.exists():
        saved = runner.read_json(manifest)
        if saved.get("signature_hash") != canonical_hash(saved.get("signature")):
            raise ValueError("Intervention manifest integrity check failed: " + str(manifest))
        if saved.get("signature") != signature:
            raise ValueError("Different intervention/configuration/wrapper source; choose a new output folder")
        if not resume:
            raise ValueError("Intervention output exists; use --resume or choose a new folder")
    elif any(p.name != LOCK_NAME for p in root.iterdir()):
        raise ValueError("Existing output lacks this intervention manifest; never mix ordinary/legacy results")
    if any(root.glob("episodes/*/.running.lock")):
        raise ValueError("Episode lock exists; verify its process before considering stale-lock recovery")


@contextmanager
def output_lease(root):
    """One variant process per output folder; never remove someone else's lock."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_NAME
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("Intervention lock exists; verify its process before removing a stale lock: " + str(path)) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                       "created_at": datetime.now(timezone.utc).isoformat()}, stream)
        yield
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def runtime_intervention(runtime_hash, qmean_sentence=None):
    """Restore both functions on every exit, including failed batches."""
    if not _PATCH_LOCK.acquire(blocking=False):
        raise RuntimeError("Another runtime intervention is active in this Python process")
    original_prompt = prompts.order_instructions
    original_fingerprint = runner.source_fingerprint
    try:
        if qmean_sentence is not None:
            def patched(role, objective, config, reference=None):
                text = original_prompt(role, objective, config, reference)
                return text + qmean_sentence if reference is None else text
            prompts.order_instructions = patched
        runner.source_fingerprint = lambda: runtime_hash
        yield
    finally:
        prompts.order_instructions = original_prompt
        runner.source_fingerprint = original_fingerprint
        _PATCH_LOCK.release()


def run_intervention(args, wrapper_file, intervention, qmean_sentence=None):
    signature, config, api, conditions = _signature(args, wrapper_file, intervention, qmean_sentence)
    root = repository_path(args.output)
    _check_folder(root, signature, args.resume)
    plan = {
        "intervention": intervention,
        "conditions": [c.id for c in conditions],
        "seeds": args.seeds,
        "objectives": {c.id: c.objective for c in conditions},
        "recovery": {c.id: {"max_retries": 0 if c.no_recovery else api.max_retries,
                            "quantity_repair": not c.no_recovery,
                            "fallback": not c.no_recovery,
                            "terminal_on_first_failure": c.no_recovery}
                     for c in conditions},
        "backend": args.backend,
        "workers": args.workers,
        "output": str(root),
        "episodes": len(conditions) * len(args.seeds),
        "safety_stock": config.safety_stock,
        "initial_inventory": config.initial_inventory,
        "warmup_periods": config.warmup_periods,
        "safety_stock_applies_during_warmup": True,
        "evaluation_periods": config.evaluation_periods,
        "q_base_meaning_sentence": qmean_sentence,
        "estimated_calls_without_retry": estimated_calls(conditions, args.seeds, config.evaluation_periods),
        "budget_usd": args.budget_usd,
        "dry_run": args.dry_run,
        "paid_requests_made_by_plan": 0,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if args.dry_run:
        if (root / LOCK_NAME).exists():
            raise ValueError("Intervention output is locked: " + str(root / LOCK_NAME))
        return 0
    with output_lease(root):
        # Check again after acquiring the filesystem lock (no check/use race
        # between two extension launchers).
        _check_folder(root, signature, args.resume)
        manifest = root / MANIFEST_NAME
        if not manifest.exists():
            runner.atomic_json(manifest, {
                "signature": signature,
                "signature_hash": canonical_hash(signature),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        with runtime_intervention(signature["runtime_source_hash"], qmean_sentence):
            runner.run_batch(args.conditions, args.seeds, root, backend=args.backend,
                             objective=args.objective, workers=args.workers,
                             budget_usd=args.budget_usd, resume=args.resume,
                             config=config, api_config=api)
    return 0
