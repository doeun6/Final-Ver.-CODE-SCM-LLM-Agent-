"""Identity of the combined version; independent V1/V2 originals are preserved."""
from pathlib import Path
from .config import canonical_hash

VARIANT_ID = "FINAL_V1_V2_OWNERSHIP_M2_N0"
BASELINE_COMMIT = "4aa1e7bf109ee8811563ac9e20415bc29cd0edb1"


def variant_metadata():
    root = Path(__file__).parent
    texts = {name: (root / name).read_text(encoding="utf-8")
             for name in ("prompts.py", "ownership.py", "m2_validation.py")}
    return {
        "id": VARIANT_ID,
        "implementation_revision": 4,
        "baseline_commit": BASELINE_COMMIT,
        "combined_from": ["V1_prompt_precision", "V2_m3_detailed_prompt"],
        "independent_from_original": False,
        "description": "V1 + V2 + ownership; M2 absence/current-action clarification; minimal N0 and mathematically integral no-recovery N0-G0 controls",
        "m2_generation": "evidence_linked_current_committed_order_explanation",
        "m2_validator": "bounded_lexical_rules_not_full_semantic_validation",
        "additional_controls": ["N0", "N0-G0"],
        "no_recovery_policy": "N0-G0: zero retries, no quantity repair or fallback; first recoverable failure terminates episode",
        "no_recovery_quantity": "finite non-boolean JSON number, exactly integral, 0..order_cap; lossless int representation only",
        "m3_generation": "autonomous_llm_with_audit_evidence",
        "prior_order_rationale_in_message_input": False,
        "ownership_mode": "deterministic_source_labels_and_prompt_rules",
        "ownership_exempt_controls": ["N0", "N0-G0"],
        "semantic_rationale_validation": False,
        "q_base_meaning_activation": "run_final.py or run_qmean.py runtime wrapper",
        "safety_stock_activation": "explicit execution setting, includes warm-up",
        "prompt_sha256": canonical_hash(texts),
    }
