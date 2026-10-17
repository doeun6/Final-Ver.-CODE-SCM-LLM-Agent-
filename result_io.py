"""Read-only helpers for the supplementary experiment analyses (standard library)."""
import json
import re
from dataclasses import dataclass
from pathlib import Path
import statistics as st


class ResultError(ValueError):
    """An input result is missing, ambiguous, or incompatible with the comparison."""


def read_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResultError(f"JSON 파일을 읽을 수 없습니다: {path} ({exc})") from exc


def is_factor(cond):
    """Only the registered 4 x 5 x 5 factorial conditions, excluding A and D."""
    return isinstance(cond, str) and re.fullmatch(r"C[0-3]M[0-4]T[0-4]", cond) is not None


EXPECTED_CONDITIONS = {f"C{c}M{m}T{t}" for c in range(4) for m in range(5) for t in range(5)} | {"A", "D_cost", "D_bullwhip"}
SUPPORTED_CONDITIONS = EXPECTED_CONDITIONS | {"N0", "N0-G0"}


@dataclass(frozen=True)
class Episode:
    condition: str
    seed: int
    objective: str
    path: Path
    summary: dict

    @property
    def metrics(self):
        return self.summary["metrics"]


def _episode(path):
    summary = read_json(path / "summary.json")
    if isinstance(summary, dict) and summary.get("status") == "aborted":
        raise ResultError(f"중단된 실행은 정상 비용 분석에 포함할 수 없습니다: {path}. "
                          "배치 execution_outcomes.json 및 failures.csv에서 실패율을 함께 확인하세요.")
    if not isinstance(summary, dict) or summary.get("complete") is not True:
        raise ResultError(f"완료되지 않았거나 잘못된 summary: {path}")
    match = re.fullmatch(r"(.+)__(cost|bullwhip)__seed-(-?\d+)", path.name)
    if not match:
        raise ResultError(f"에피소드 폴더 이름을 해석할 수 없습니다: {path}")
    cond, objective, seed_text = match.groups()
    seed = int(seed_text)
    if cond not in SUPPORTED_CONDITIONS:
        raise ResultError(f"등록되지 않은 조건입니다: {cond} ({path})")
    if (summary.get("condition"), summary.get("seed"), summary.get("objective")) != (cond, seed, objective):
        raise ResultError(f"폴더 이름과 summary의 조건·seed·목적이 다릅니다: {path}")
    if (cond == "D_cost" and objective != "cost") or (cond == "D_bullwhip" and objective != "bullwhip"):
        raise ResultError(f"D 비교조건 이름과 목적이 다릅니다: {path}")
    ms = summary.get("metrics")
    if not isinstance(ms, dict) or ms.get("status") != "completed":
        raise ResultError(f"완료 지표가 없습니다: {path}")
    for key in ("cost_per_period", "retailer_immediate_fill_rate"):
        if not isinstance(ms.get(key), (int, float)) or isinstance(ms[key], bool):
            raise ResultError(f"필수 수치 지표 {key}가 없습니다: {path}")
    return Episode(cond, seed, objective, path.resolve(), summary)


def episodes(folder, seed=None):
    """Yield (condition, seed, episode directory), preserving the supplied API."""
    for item in collect_episodes([folder], seeds=None if seed is None else [seed]).values():
        yield item.condition, item.seed, item.path


def collect_episodes(folders, seeds=None):
    selected = None if seeds is None else set(seeds)
    data = {}
    objectives = {}
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            raise ResultError(f"결과 폴더가 없습니다: {folder}")
        files = sorted(folder.glob("episodes/*/summary.json"))
        if not files:
            raise ResultError(f"완료 summary.json이 없습니다: {folder}/episodes/")
        for summ in files:
            item = _episode(summ.parent)
            if selected is not None and item.seed not in selected:
                continue
            key = (item.condition, item.seed)
            if key in data:
                if data[key].path == item.path:
                    continue
                raise ResultError(f"같은 조건·seed가 두 폴더에 있습니다: {key}\n  {data[key].path}\n  {item.path}\n중복 실행 중 사용할 결과 하나만 지정하세요.")
            old = objectives.setdefault(item.condition, item.objective)
            if old != item.objective:
                raise ResultError(f"같은 조건의 목적이 seed마다 다릅니다: {item.condition} ({old}, {item.objective})")
            data[key] = item
    if not data:
        raise ResultError("지정한 폴더·seed에 해당하는 완료 결과가 없습니다.")
    if selected is not None:
        missing = selected - {s for _, s in data}
        if missing:
            raise ResultError(f"완료 결과가 없는 요청 seed: {sorted(missing)}")
    validate_objectives(data)
    return data


def validate_objectives(data):
    objectives = {item.objective for item in data.values() if is_factor(item.condition) or item.condition in {"A", "N0", "N0-G0"}}
    if len(objectives) > 1:
        raise ResultError("CMT·A·N0 결과에 서로 다른 목적(cost, bullwhip)이 섞여 있습니다. 목적별로 분석 입력을 분리하세요.")


def metrics(d):
    return _episode(Path(d)).metrics


def periods(d):
    rows = read_json(Path(d) / "periods.json")
    if not isinstance(rows, list) or not rows:
        raise ResultError(f"평가기간 기록이 없거나 잘못된 periods.json: {d}")
    if any(not isinstance(w, dict) or "Q_final" not in w for w in rows):
        raise ResultError(f"Q_final이 없는 기간 기록: {d}")
    return rows


def cap_count(item):
    return sum(w["Q_final"] == 100 for w in periods(item.path))


def median(values, digits=3):
    values = [v for v in values if v is not None]
    return f"{st.median(values):.{digits}f}" if values else "-"


def assert_comparable(left, right):
    if (left.condition, left.seed, left.objective) != (right.condition, right.seed, right.objective):
        raise ResultError(f"대응 비교의 조건·seed·목적 불일치: {left.path} / {right.path}")
    for key in ("periods_evaluated", "evaluation_start", "evaluation_end"):
        if left.metrics.get(key) != right.metrics.get(key):
            raise ResultError(f"대응 비교의 평가 기간({key}) 불일치: {left.path} / {right.path}")
    a, b = left.summary.get("demand_hash"), right.summary.get("demand_hash")
    if a and b and a != b:
        raise ResultError(f"동일 seed의 고객 수요 이력이 다릅니다: {left.path} / {right.path}")


def paired_keys(base, variant):
    keys = sorted(set(base) & set(variant))
    if not keys:
        raise ResultError("기준과 개선 설정 사이에 같은 조건·seed의 완료 결과가 없습니다.")
    for key in keys:
        assert_comparable(base[key], variant[key])
    return keys


def report_completeness(data, label="결과"):
    for seed in sorted({s for _, s in data}):
        found = {c for c, s in data if s == seed}
        missing = EXPECTED_CONDITIONS - found
        controls = found - EXPECTED_CONDITIONS
        print(f"{label} | seed {seed}: {len(found & EXPECTED_CONDITIONS)}/103조건 완료"
              + (f" + 추가 기준조건 {len(controls)}개" if controls else "")
              + (f" (미완료/미제공 {len(missing)}조건; 관측된 조건만 분석)" if missing else ""))


def groups():
    yield "전체", lambda c: True
    for pos, levels in [(0, range(4)), (2, range(5)), (4, range(5))]:
        prefix = "CMT"[pos // 2]
        for level in levels:
            name = f"{prefix}{level}"
            yield name, lambda c, pos=pos, name=name: c[pos:pos + 2] == name


def print_pair_summary(base, variant, keys, label):
    """Descriptive statistics only: observations are not independent seed replicates."""
    diffs = [variant[k].metrics["cost_per_period"] - base[k].metrics["cost_per_period"] for k in keys]
    a = [base[k].metrics["cost_per_period"] for k in keys]
    b = [variant[k].metrics["cost_per_period"] for k in keys]
    print(f"  {label}: {len(keys)}쌍 | 비용 중앙값 {median(a)} → {median(b)} | 대응 차이 중앙값 {median(diffs)} | 비용 감소 {sum(d < 0 for d in diffs)}/{len(keys)}")
