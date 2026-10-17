"""C/M/T treatment execution with explicit, stateless information boundaries."""

from copy import deepcopy
import math
import statistics
import time

from .config import ROLES, canonical_hash
from .forecasting import METHODS, forecast, normalize_order, order_up_to
from .ownership import build_information_sources
from .provider import EpisodeAborted, RecoverableCallError
from .m2_validation import validate_m2_message
from . import prompts


STATE_FIELDS = ("D", "I", "B", "P_pre")
WINDOWS = {"C0": 10, "C1": 20, "C2": 5, "C3": 10}
# C3 order statistics use the same t-9..t-1 past orders that C0 shows as raw rows.
ORDER_STAT_FIELDS = ("Q_base", "Q_final", "Q_final_minus_Q_base")
ORDER_STAT_DEFINITIONS = {
    "Q_base": "reference support quantity calculated by the code in that period",
    "Q_final": "order actually executed and sent upstream in that period",
    "Q_final_minus_Q_base": ("executed order minus reference support in the same period; "
                             "positive means the executed order exceeded the support"),
}


def _summary(values):
    return {"mean": statistics.mean(values),
            "standard_deviation": statistics.stdev(values),
            "minimum": min(values), "maximum": max(values)}


def _order_statistics(past):
    """Past-order summary for C3; null when any past reference is unavailable."""
    series = {"Q_final": [row["Q_final"] for row in past]}
    if any(row["Q_base"] is None for row in past):
        series.update(Q_base=None, Q_final_minus_Q_base=None)
    else:
        series["Q_base"] = [row["Q_base"] for row in past]
        series["Q_final_minus_Q_base"] = [row["Q_final"]-row["Q_base"] for row in past]
    return {key: None if series[key] is None else _summary(series[key])
            for key in ORDER_STAT_FIELDS}


def build_C(level, history, currentrow):
    """Current-inclusive state windows; past orders have one fewer observation."""
    if level not in WINDOWS:
        raise ValueError(f"Unknown C level {level!r}")
    n = WINDOWS[level]
    t = currentrow["t"]
    past = [row for row in history if row["t"] < t][-(n-1):]
    if [row["t"] for row in past] != list(range(t-n+1, t)):
        raise ValueError("C requires contiguous completed local history ending at t-1")
    current = {key: currentrow[key] for key in STATE_FIELDS}
    rows = [*past, currentrow]
    result = {"current": {"t": t, **current}}
    if level == "C3":
        result.update({
            "representation": "statistics", "window": 10,
            "period_start": t-9, "period_end": t,
            "statistics": {key: _summary([row[key] for row in rows]) for key in STATE_FIELDS},
            # The current order is not yet decided, so order statistics end at t-1.
            "order_window": len(past),
            "order_period_start": t-len(past), "order_period_end": t-1,
            "order_definitions": dict(ORDER_STAT_DEFINITIONS),
            "order_statistics": _order_statistics(past),
        })
    else:
        result.update({
            "representation": "raw", "window": n,
            "states": [{"t": row["t"], **{key: row[key] for key in STATE_FIELDS}}
                       for row in rows],
            "past_orders": [{"t": row["t"], "Q_base": row["Q_base"],
                             "Q_final": row["Q_final"]} for row in past],
        })
    return result


build_context = build_C


def _schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


FORECAST_SCHEMA = _schema({"forecast_h1": {"type": "number"},
                           "forecast_h2": {"type": "number"}})
SELECTION_SCHEMA = _schema({"method": {"type": "string", "enum": list(METHODS)}})
ORDER_SCHEMA = _schema({"order_quantity": {"type": "number"},
                       "rationale": {"type": "string"}})
MESSAGE_SCHEMA = _schema({"message": {"type": "string"}})
PLAN_FIELDS = ("plan_t_plus_1", "plan_t_plus_2")

class InvalidOrderQuantity(ValueError):
    """G0 rejects an illegal action instead of rounding/clipping it."""


def _validate_unrepaired_order(value, order_cap):
    quantity = value["order_quantity"]
    # JSON numbers such as 10, 10.0 and 1e1 represent the same valid action.
    # Accept only exact integral values: no tolerance, rounding or clipping.
    if (type(quantity) not in (int, float) or not 0 <= quantity <= order_cap
            or (type(quantity) is float and (not math.isfinite(quantity) or not quantity.is_integer()))):
        raise InvalidOrderQuantity(f"Order must be a finite integer-valued number between 0 and {order_cap}; G0 cannot repair it")


def plan_schema(order_cap):
    """Internal M3 response; only the two plan quantities are sent upstream."""
    quantity = {"type": "integer", "minimum": 0, "maximum": order_cap}
    return _schema({**{key: dict(quantity) for key in PLAN_FIELDS},
                    "planning_evidence": {"type": "string", "maxLength": 600}})


def _validate_message(value, level, order_cap=None):
    if level == "M3":
        # validate_schema checks the integer type but not minimum/maximum,
        # so the range is enforced here and shares the common retry budget.
        if order_cap is None:
            raise ValueError("M3 validation requires the order cap")
        for key in PLAN_FIELDS:
            quantity = value[key]
            if type(quantity) is not int:
                raise ValueError(f"M3 {key} must be an integer order quantity")
            if not 0 <= quantity <= order_cap:
                raise ValueError(f"M3 {key} must be between 0 and {order_cap}")
        evidence = value.get("planning_evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("M3 planning_evidence must be nonblank audit text")
        if len(evidence) > 600:
            raise ValueError("M3 planning_evidence must be at most 600 characters")
        return
    if not value["message"].strip():
        raise ValueError("Message fields must not be empty")
    if level == "M2":
        validate_m2_message(value["message"])


def _event_counts(events):
    """The provider's ledger is authoritative; do not count ordinary stages as retries."""
    result = {"api_call_count": len(events), "retry_count": 0,
              "format_failure_count": 0, "api_error_count": 0}
    for event in events:
        result["retry_count"] += int(event.get("attempt", 0) > 0)
        result["format_failure_count"] += int(bool(event.get("format_failure", False)))
        result["api_error_count"] += int(event.get("success") is False and
                                         not event.get("format_failure", False))
    for field in ("input_tokens", "output_tokens", "total_tokens", "reported_cost_usd"):
        values = [event.get(field) for event in events]
        available = [value for value in values if value is not None]
        result[field] = sum(available) if len(available) == len(values) else None
        result[field + "_reported_subtotal"] = sum(available)
        result[field + "_missing_count"] = len(values)-len(available)
    return result


class Harness:
    def __init__(self, config, condition, provider):
        self.config = config
        self.condition = condition
        self.provider = provider
        if condition.no_recovery and not (condition.minimal_prompt and condition.direct_order and condition.m == "M0"):
            raise ValueError("No-recovery execution is registered only for the minimal direct-order control")

    def decide(self, env, i, row, received_message):
        """Finish one already-begun agent exactly once, then construct its message."""
        started = time.perf_counter()
        t, role = row["t"], ROLES[i]
        condition = self.condition
        replayed = any((event.get("t"), event.get("agent"), event.get("condition")) ==
                       (t, i, condition.id) for event in self.provider.events)
        state = env.agents[i]
        context = build_C(condition.c, state.history, row)
        message = None if condition.m == "M0" else deepcopy(received_message)
        # A has no forecasting stage, including on failure. Its authorized C0 is
        # built from local records; the separate thirty-request series is never read.
        history = None
        if not condition.direct_order:
            history = list(state.demands[-self.config.forecast_window:])
            if len(history) != 30:
                raise ValueError("Every forecasting condition requires exactly thirty requests")
        meta = {"t": t, "agent": i, "role": role, "condition": condition.id,
                "objective": condition.objective, "message_level": condition.m,
                "tool_level": condition.t, "direct_order": condition.direct_order}
        meta.update(minimal_prompt=condition.minimal_prompt, no_recovery=condition.no_recovery)
        diagnostics = {
            "context_sha256": canonical_hash(context), "context_payload": context,
            "received_message": message, "selected_method": None,
            "llm_selected_method": None,
            "forecast_fallback": False, "order_fallback": False,
            "message_fallback": False, "fallback_count": 0,
            "correction_count": 0, "forecast_correction_count": 0,
            "arithmetic_error": False, "arithmetic_error_count": 0,
            "forecast_arithmetic_error": None,
            # Research diagnostics only. build_C explicitly selects its allowed fields.
            "stage_audit": [],
        }

        def stage_context(task, payload):
            customer, supplier = prompts.role_neighbors(role)
            details = {
                "stage": task, "owner_role": role, "period": t,
                "phase": ("after_current_order_commit" if task == "message"
                          else "after_fulfillment_before_current_order"),
                "incoming_request_from": customer, "replenishment_to": supplier,
                "source_fields": sorted(payload),
            }
            if "C" in payload:
                details["own_context"] = {
                    "level": condition.c, "owner_role": role,
                    "snapshot_period": context["current"]["t"],
                    "snapshot_phase": "after_fulfillment_before_current_order",
                    "representation": context["representation"],
                    "state_period_start": t - context["window"] + 1,
                    "state_period_end": t,
                    "order_period_start": t - context["window"] + 1,
                    "order_period_end": t - 1,
                }
            if "M" in payload:
                details["downstream_message"] = {
                    "present": payload["M"] is not None,
                    "sender_role": customer if i else None,
                    "received_period": t,
                    "sender_phase": "after_current_order_commit",
                    "level": condition.m,
                }
            if "history_30" in payload:
                details["own_request_history"] = {
                    "owner_role": role, "variable": "D", "period_start": t-29,
                    "period_end": t, "count": len(payload["history_30"]),
                }
            if task == "forecast":
                details["target_periods"] = [t+1, t+2]
            return details

        def audit_stage(task, payload, executor):
            details = stage_context(task, payload)
            audit = {
                **details, "executor": executor, "status": "started",
                "input_sha256": canonical_hash(payload),
            }
            diagnostics["stage_audit"].append(audit)
            return audit, details

        def prepare_payload(task, payload):
            # C/M values remain unchanged. Labels are generated from this call's
            # authorized fields only; no environment or hidden history is read.
            prepared = deepcopy(payload)
            if not condition.minimal_prompt:
                prepared["information_sources"] = build_information_sources(role, t, task, payload)
            return prepared

        def ask(task, instructions, payload, schema, **kwargs):
            prepared = prepare_payload(task, payload)
            audit, details = audit_stage(task, prepared, "llm")
            # Absolute time/phase are metadata, not additional state observations.
            if not condition.minimal_prompt:
                instructions = prompts.stage_instructions(role, t, task) + instructions
            if condition.no_recovery:
                kwargs["max_retries_override"] = 0
            try:
                result = self.provider.ask(task, instructions, prepared, schema,
                                           dict(meta, stage_context=details), **kwargs)
            except RecoverableCallError as exc:
                audit["status"] = "aborted_without_recovery" if condition.no_recovery else "failed_after_retries"
                if condition.no_recovery:
                    matches = [e for e in self.provider.events
                               if (e.get("t"), e.get("agent"), e.get("condition"), e.get("task")) ==
                               (t, i, condition.id, task)]
                    last = matches[-1] if matches else {}
                    kind = ("invalid_action" if last.get("validation_error_type") == "InvalidOrderQuantity"
                            else "invalid_output" if last.get("format_failure") else "api_error")
                    raise EpisodeAborted(str(exc), failure_kind=kind, details={
                        **meta, "task": task, "error_type": last.get("error_type", type(exc).__name__),
                        "attempts_for_task": len(matches), "stage_audit": deepcopy(diagnostics["stage_audit"]),
                    }) from exc
                raise
            audit["status"] = "completed"
            return result

        def audit_code(task, payload, output, executor="code"):
            audit, _ = audit_stage(task, payload, executor)
            audit.update(status="completed", output=deepcopy(output))

        if condition.direct_order:
            raw_support = None
            diagnostics.update(forecast=None, forecast_raw=None, support_policy=None)
        elif condition.reference:
            if condition.reference == "LR30":
                values = forecast("linear_regression", history, self.config.ses_alpha)
                raw_support = values[0]
                method = "linear_regression"
            elif condition.reference == "EOQ30":
                if self.config.holding_cost <= 0:
                    raise ValueError("EOQ requires strictly positive holding cost")
                raw_support = math.sqrt(2*statistics.mean(history)*
                                        self.config.fixed_order_cost/self.config.holding_cost)
                values = None
                method = "EOQ30"
            else:
                raise ValueError(f"Unknown reference {condition.reference!r}")
            diagnostics.update(selected_method=method, forecast=values,
                               forecast_raw=values, support_policy=condition.reference)
            audit_code("reference", {"history_30": history, "method": method},
                       {"forecast": values, "Q_base_raw": raw_support})
        else:
            method = "linear_regression" if condition.t in ("T1", "T2") else None
            values = None
            try:
                if condition.t in ("T3", "T4"):
                    selection = ask("select", prompts.selection_instructions(role),
                                    {"C": context, "M": message,
                                     "candidates": prompts.METHOD_DESCRIPTIONS}, SELECTION_SCHEMA)
                    method = selection["method"]
                    diagnostics["llm_selected_method"] = method
                if condition.t in ("T0", "T1", "T3"):
                    payload = {"history_30": history,
                               "targets": ["D[t+1]", "D[t+2]"]}
                    if method:
                        payload.update(method=method,
                                       formula=prompts.formula(method, self.config.ses_alpha))
                    result = ask("forecast", prompts.forecast_instructions(role, method),
                                 payload, FORECAST_SCHEMA)
                    raw_values = [result["forecast_h1"], result["forecast_h2"]]
                    values = [max(0.0, float(value)) for value in raw_values]
                    corrected = sum(a != b for a, b in zip(raw_values, values))
                    diagnostics["forecast_correction_count"] = corrected
                    diagnostics["correction_count"] += corrected
                    diagnostics["forecast_raw"] = raw_values
                    if condition.t in ("T1", "T3"):
                        exact = forecast(method, history, self.config.ses_alpha)
                        errors = [float(value)-expected for value, expected in zip(values, exact)]
                        diagnostics["forecast_arithmetic_error"] = errors
                        diagnostics["arithmetic_error_count"] = sum(abs(e) > 1e-8 for e in errors)
                        diagnostics["arithmetic_error"] = any(abs(e) > 1e-8 for e in errors)
                        diagnostics["forecast_audit_exact"] = exact
                elif condition.t in ("T2", "T4"):
                    values = forecast(method, history, self.config.ses_alpha)
                    diagnostics["forecast_raw"] = list(values)
                    audit_code("forecast", {"history_30": history, "method": method}, values)
                else:
                    raise ValueError(f"Unknown T level {condition.t!r}")
            except RecoverableCallError as exc:
                method = "linear_regression"
                values = forecast(method, history, self.config.ses_alpha)
                diagnostics.update(forecast_fallback=True, forecast_fallback_reason=str(exc),
                                   forecast_raw=list(values))
                diagnostics["fallback_count"] += 1
                audit_code("forecast", {"history_30": history, "method": method}, values,
                           executor="code_fallback")
            diagnostics.update(selected_method=method or "llm_direct", forecast=list(values),
                               support_policy="order_up_to")
            raw_support = order_up_to(values, row["I"], row["B"], row["P_pre"], self.config)
            audit_code("reference", {"forecast": values, "own_I": row["I"],
                                     "own_B": row["B"], "own_P_pre": row["P_pre"],
                                     "safety_stock": self.config.safety_stock},
                       {"Q_base_raw": raw_support})

        # Q_base_raw = 정수·상한 보정 전 기준량; OUT의 max(0, ...)는 이미 적용됨.
        # Q_base는 보정 후 최종 판단에 제공하는 참고량이며, 실제 발주는 Q_final입니다.
        # A에는 기준량 자체가 없으므로 두 필드 모두 None(null)을 기록합니다.
        base = None if condition.direct_order else normalize_order(raw_support, self.config.order_cap)
        diagnostics["Q_base_raw"] = raw_support
        diagnostics["base_corrected"] = base != raw_support
        diagnostics["correction_count"] += int(base != raw_support)
        order_payload = ({"C": context, "D": row["D"]} if condition.direct_order
                         else {"C": context, "M": message, "Q_base": base})
        order_prompt = (prompts.minimal_order_instructions(role, condition.objective, self.config)
                        if condition.minimal_prompt else
                        prompts.direct_order_instructions(role, condition.objective, self.config)
                        if condition.direct_order else
                        prompts.order_instructions(role, condition.objective,
                                                   self.config, condition.reference))
        try:
            order_kwargs = ({"validate": lambda v: _validate_unrepaired_order(v, self.config.order_cap)}
                            if condition.no_recovery else {})
            result = ask("order", order_prompt, order_payload, ORDER_SCHEMA, **order_kwargs)
            raw_order = result["order_quantity"]
            # G0 validation has already established an exact integer value.
            # Canonical int storage changes only its numeric representation;
            # raw_order preserves the parsed proposal (including 10.0/-0.0).
            # No rounding, clamping or fallback is permitted under G0.
            final = int(raw_order) if condition.no_recovery else normalize_order(raw_order, self.config.order_cap)
            rationale = result["rationale"]
            diagnostics["order_corrected"] = raw_order != final
            diagnostics["correction_count"] += int(raw_order != final)
        except RecoverableCallError as exc:
            raw_order = None
            if condition.direct_order:
                final = normalize_order(row["D"], self.config.order_cap)
                rationale = "Final-order call failed; executed the normalized current incoming request."
                fallback_policy = "current_request"
                fallback_corrected = final != row["D"]
                diagnostics["fallback_quantity_raw"] = row["D"]
                diagnostics["correction_count"] += int(fallback_corrected)
            else:
                final = base
                rationale = "Final-order call failed; executed the normalized current support quantity."
                fallback_policy = "current_reference_order"
                fallback_corrected = False
            diagnostics.update(order_fallback=True, order_fallback_reason=str(exc),
                               order_corrected=fallback_corrected, fallback_policy=fallback_policy)
            diagnostics["fallback_count"] += 1
        # Q_final_raw = LLM이 제안한 보정 전 수량; Q_final = 실제 실행 수량.
        # 최종 호출 실패 시 유효한 제안이 없으므로 raw는 None, 실행량은 fallback 기록 참조.
        diagnostics.update(Q_final_raw=raw_order, rationale=rationale,
                           order_deviation=None if base is None else abs(final-base))
        diagnostics["rationale_audit"] = {
            "use": "research_only_not_model_input", "owner_role": role, "period": t,
            "source": "environment_fallback" if diagnostics["order_fallback"] else "llm_order_output",
            "explains": "executed_Q_final" if diagnostics["order_fallback"] else "proposed_Q_final_raw",
            "explained_quantity": final if diagnostics["order_fallback"] else raw_order,
            "executed_Q_final": final,
            "environment_normalization_changed_quantity": diagnostics["order_corrected"],
            "authorized_input_fields": sorted(prepare_payload("order", order_payload)),
            "context_level": condition.c,
            "order_input_sha256": canonical_hash(prepare_payload("order", order_payload)),
        }
        committed = env.finish_agent(i, t, base, final, diagnostics)

        outgoing = None
        if i < len(ROLES)-1 and condition.m == "M1":
            demands = state.demands[-10:]
            if len(demands) != 10:
                raise ValueError("M1 requires exactly ten current-inclusive local requests")
            outgoing = {"t": t, "sender": role, "I": committed["I"], "B": committed["B"],
                        "P_post": committed["P_post"], "D": committed["D"],
                        "D_mean_10": statistics.mean(demands),
                        "D_std_10": statistics.stdev(demands)}
            audit_code("message", {"own_post_order_state": {
                key: committed[key] for key in ("I", "B", "P_post", "D")},
                "own_D_history_10": demands}, outgoing, executor="environment")
        elif i < len(ROLES)-1 and condition.m in ("M2", "M3", "M4"):
            payload = {"C": context, "M": message, "Q_base": base, "Q_final": final,
                       "P_post": committed["P_post"]}
            cap = self.config.order_cap
            schema = plan_schema(cap) if condition.m == "M3" else MESSAGE_SCHEMA
            try:
                output = ask("message", prompts.message_instructions(role, condition.m, cap),
                             payload, schema,
                             validate=lambda value: _validate_message(value, condition.m, cap))
                if condition.m == "M3":
                    outgoing = {key: output[key] for key in PLAN_FIELDS}
                    diagnostics["planning_evidence"] = output["planning_evidence"]
                else:
                    outgoing = output["message"]
            except RecoverableCallError as exc:
                diagnostics.update(message_fallback=True, message_fallback_reason=str(exc))
                diagnostics["fallback_count"] += 1
        elif condition.m not in ("M0", "M1", "M2", "M3", "M4"):
            raise ValueError(f"Unknown M level {condition.m!r}")
        # Include the original physical attempts when a resumed provider replays its journal.
        decision_events = [event for event in self.provider.events
                           if (event.get("t"), event.get("agent"), event.get("condition")) ==
                           (t, i, condition.id)]
        diagnostics.update(_event_counts(decision_events))
        elapsed_ms = (time.perf_counter()-started)*1000
        diagnostics.update(outgoing_message=outgoing, latency_replayed=replayed,
                           decision_latency_ms=None if replayed else elapsed_ms,
                           replay_wall_time_ms=elapsed_ms if replayed else None)
        return env.update_agent_record(i, t, diagnostics)
