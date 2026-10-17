from dataclasses import dataclass, replace

@dataclass(frozen=True)
class Condition:
    id: str
    c: str
    m: str
    t: str | None
    objective: str = "cost"
    reference: str | None = None
    direct_order: bool = False
    minimal_prompt: bool = False
    no_recovery: bool = False

def registry():
    result = {"A": Condition("A", "C0", "M0", None, direct_order=True)}
    for c in range(4):
        for m in range(5):
            for t in range(5):
                name = f"C{c}M{m}T{t}"
                result[name] = Condition(name, f"C{c}", f"M{m}", f"T{t}")
    result["D_cost"] = Condition("D_cost", "C0", "M4", None, "cost", "LR30")
    result["D_bullwhip"] = Condition("D_bullwhip", "C0", "M4", None, "bullwhip", "EOQ30")
    # Additional controls, outside the unchanged 4 x 5 x 5 factorial design.
    result["N0"] = Condition("N0", "C0", "M0", None, direct_order=True, minimal_prompt=True)
    result["N0-G0"] = Condition("N0-G0", "C0", "M0", None, direct_order=True,
                                minimal_prompt=True, no_recovery=True)
    return result

def get_condition(name, objective=None):
    try:
        condition = registry()[name]
    except KeyError:
        raise ValueError(f"Unknown condition {name!r}; use list to see the 105 registered conditions") from None
    if objective and condition.reference and objective != condition.objective:
        raise ValueError("D reference objectives are fixed; use the matching D reference")
    if objective:
        if objective not in ("cost", "bullwhip"):
            raise ValueError("Objective must be cost or bullwhip")
        condition = replace(condition, objective=objective)
    return condition
