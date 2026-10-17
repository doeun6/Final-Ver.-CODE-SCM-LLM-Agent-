"""Seed-wise descriptive summaries of explicitly selected result folders; no API."""
import argparse
from result_io import ResultError, collect_episodes, groups, is_factor, median, report_completeness


def main(argv=None):
    parser = argparse.ArgumentParser(description="선택한 결과 폴더의 seed별 비용·보조지표 요약 (API 사용 없음)")
    parser.add_argument("folders", nargs="+", help="episodes/가 있는 배치 결과 폴더. 동일 설정의 폴더만 함께 지정")
    parser.add_argument("--seeds", type=int, nargs="+", help="분석할 seed (생략하면 입력 폴더의 전체 seed)")
    args = parser.parse_args(argv)
    try:
        data = collect_episodes(args.folders, args.seeds)
        report_completeness(data)
        print("기술통계: seed를 합치지 않으며, 같은 seed의 여러 조합을 독립 반복으로 취급하지 않습니다.")
        for seed in sorted({s for _, s in data}):
            fac = {c: item.metrics for (c, s), item in data.items() if s == seed and is_factor(c)}
            print(f"\n[seed {seed}: 요인 수준별 비용 중앙값]")
            for name, matches in groups():
                values = [m["cost_per_period"] for c, m in fac.items() if matches(c)]
                print(f"  {name}: {median(values)} (조건 {len(values)}개)")
            print("[C3 vs 원자료: 같은 M·T에서 비용 비교, 차이는 C3−비교수준]")
            for other in ["C0", "C1", "C2"]:
                pairs = [(fac["C3" + c[2:]]["cost_per_period"], m["cost_per_period"]) for c, m in fac.items() if c.startswith(other) and "C3" + c[2:] in fac]
                diffs = [a - b for a, b in pairs]
                print(f"  C3 vs {other}: 비용 감소 {sum(d < 0 for d in diffs)}/{len(diffs)} | 대응 차이 중앙값 {median(diffs)}")
            print("[C별 중앙값: 소매 즉시충족률(0~1) / 채찍효과 / 대체결정률 / 기당 재고비 / 기당 백로그비]")
            for lv in ["C0", "C1", "C2", "C3"]:
                ms = [m for c, m in fac.items() if c.startswith(lv)]
                values = [median(m.get(k) for m in ms) for k in ["retailer_immediate_fill_rate", "global_bullwhip", "fallback_decision_rate"]]
                values += [median(m.get("cost_components_per_period", {}).get(k) for m in ms) for k in ["holding_cost", "backlog_cost"]]
                print(f"  {lv} (조건 {len(ms)}개): " + " / ".join(values))
            print("[비교군 기당 비용]")
            for cond in ["A", "D_cost", "D_bullwhip"]:
                item = data.get((cond, seed))
                print(f"  {cond}: {median([item.metrics['cost_per_period']]) if item else '-'}")
        print("\n자료 없음·정의 불가 지표는 '-'로 표시하며 중앙값에서 제외합니다. 부분 결과의 요인별 중앙값은 균형 설계 전체 효과가 아닙니다.")
    except ResultError as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
