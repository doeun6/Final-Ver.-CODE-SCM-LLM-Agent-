"""Deterministic source labels for the evidence already authorized in one call.

This module never reads the environment or another agent's private history. It
adds no observations or numeric state values. Textual reports retain their
explicit attribution; knowing who sent a report does not establish its subject.
"""

from .config import ROLES


PRE_ORDER = "after_fulfillment_before_current_order"
POST_ORDER = "after_current_order_commit"

STATE_MEANINGS = {
    "D": "Own new incoming request, not a receipt or own outgoing order.",
    "I": "Own on-hand inventory after current receipts and shipments.",
    "B": "Own unfulfilled obligations to the immediate customer, not supplier debt to self.",
    "P_pre": "Own unreceived orders after receipts and before own current order; includes unshipped orders.",
}


def build_information_sources(role, t, task, payload):
    """Return owner/time/source metadata only for fields present in ``payload``.

    Period numbers describe the supplied window or requested forecast horizon;
    they are not new observations. The input and nested C/M objects are untouched.
    In particular, this function does not infer another agent's inventory from
    own C and does not infer the owner of a quoted textual claim from its sender.
    """
    index = ROLES.index(role)
    customer = ROLES[index - 1] if index else "external customer"
    supplier = ROLES[index + 1] if index + 1 < len(ROLES) else "external supply source"
    fields = []

    def add(path, owner, meaning, *, period=None, phase=None, **extra):
        item = {"source_path": path, "owner_role": owner, "meaning": meaning}
        if period is not None:
            item["period"] = period
        if phase is not None:
            item["phase"] = phase
        item.update(extra)
        fields.append(item)

    if "C" in payload:
        context = payload["C"]
        add("C", role, "Own local evidence only; never relabel these values as downstream state.")
        current = context.get("current", {})
        current_t = current.get("t", t)
        for key, meaning in STATE_MEANINGS.items():
            if key in current:
                extra = {"incoming_from_role": customer} if key == "D" else {}
                if key == "D" and index:
                    extra["relationship"] = (
                        "Equals immediate downstream's executed current outgoing Q; "
                        "does not equal that downstream agent's own incoming D in general."
                    )
                add(f"C.current.{key}", role, meaning,
                    period=current_t, phase=PRE_ORDER, **extra)
        if "states" in context:
            add("C.states[*]", role,
                "Own supplied state rows; each row's t determines its observation time.",
                phase=PRE_ORDER, period_source="C.states[*].t")
        if "past_orders" in context:
            add("C.past_orders[*]", role,
                "Own completed past decisions: Q_base is support; Q_final is own executed order to supplier.",
                phase=POST_ORDER, period_source="C.past_orders[*].t", supplier_role=supplier)
        if "statistics" in context:
            add("C.statistics", role,
                "Summary of own current-inclusive state window, not current observations or a time sequence.",
                phase=PRE_ORDER, period_start=context.get("period_start"),
                period_end=context.get("period_end"))
        if "order_statistics" in context:
            add("C.order_statistics", role,
                "Summary of own completed past reference/executed orders and their differences; excludes current order.",
                phase=POST_ORDER, period_start=context.get("order_period_start"),
                period_end=context.get("order_period_end"))

    if "M" in payload:
        message = payload["M"]
        sender = customer if index else None
        if message is None:
            add("M", None, "No additional message is available; this is not zero demand.",
                period=t, availability="absent", sender_role=sender)
        elif isinstance(message, str):
            # A relayed claim may concern somebody other than the immediate sender.
            add("M", None,
                "Text received from downstream. First-person pronouns refer to the sender; explicit third-party claims retain their named subject. Unclear subjects stay unknown.",
                period=t, phase=POST_ORDER, sender_role=sender,
                reported_owner="as_explicitly_attributed_in_text_or_unknown",
                claim_period="as_explicitly_stated_in_text_or_unknown",
                factual_status="unverified_report")
        elif isinstance(message, dict):
            if any(key in message for key in ("plan_t_plus_1", "plan_t_plus_2")):
                for key, offset in (("plan_t_plus_1", 1), ("plan_t_plus_2", 2)):
                    if key in message:
                        add(f"M.{key}", sender,
                            "Sender's intended future outgoing order to receiver, not receiver's own plan, confirmed demand, or scheduled receipt.",
                            period=t+offset, phase="future_intention", sender_role=sender,
                            created_period=t, factual_status="nonbinding_plan")
            else:
                # M1 is populated by the environment from the routed sender.
                message_t = message.get("t", t)
                definitions = {
                    "I": "Sender's own on-hand inventory after its receipts/shipments; its current order does not change I.",
                    "B": "Sender's own unmet incoming requests owed to its customer; not receiver's own backlog.",
                    "P_post": "Sender's own unreceived orders to receiver, already including sender's current executed order.",
                    "D": "Sender's own incoming request from its customer; not the order sender sent to receiver.",
                    "D_mean_10": "Mean of sender's own ten current-inclusive incoming requests.",
                    "D_std_10": "Sample standard deviation of sender's own ten current-inclusive incoming requests.",
                }
                for key, meaning in definitions.items():
                    if key not in message:
                        continue
                    extra = {"sender_role": sender, "factual_status": "environment_record"}
                    if key in ("D_mean_10", "D_std_10"):
                        extra.update(period_start=message_t-9, period_end=message_t)
                        add(f"M.{key}", sender, meaning,
                            phase="current_inclusive_incoming_request_history", **extra)
                    else:
                        phase = POST_ORDER if key == "P_post" else PRE_ORDER
                        add(f"M.{key}", sender, meaning,
                            period=message_t, phase=phase, **extra)

    if "D" in payload:
        add("D", role,
            "Own current incoming request; when C is present this repeats C.current.D, not an extra request.",
            period=t, phase=PRE_ORDER, incoming_from_role=customer)
    if "Q_base" in payload:
        add("Q_base", role,
            "Reference support for receiver's own current order; not downstream's reference, target stock, or a future commitment.",
            period=t, phase=PRE_ORDER, supplier_role=supplier)
    if "Q_final" in payload:
        add("Q_final", role,
            "Own already committed current outgoing order to supplier; not an incoming request or immediate receipt.",
            period=t, phase=POST_ORDER, supplier_role=supplier)
    if "P_post" in payload:
        add("P_post", role,
            "Own unreceived ordered quantity after commitment; already includes own Q_final and does not reveal dated receipts.",
            period=t, phase=POST_ORDER, supplier_role=supplier)
    if "history_30" in payload:
        add("history_30", role,
            "Own incoming requests D, oldest first, used only by this forecast call.",
            phase="current_inclusive_incoming_request_history",
            period_start=t-len(payload["history_30"])+1, period_end=t,
            incoming_from_role=customer)
    if "targets" in payload:
        add("targets", role,
            "Forecast own next and second-next incoming requests D, not own outgoing Q or physical receipts.",
            phase="forecast_target", target_periods=[t+1, t+2])

    return {"schema_version": 1, "receiver_role": role, "stage": task, "fields": fields}
