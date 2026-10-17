"""Read-only diagnostic of order caps and adjustments relative to Q_base."""
import argparse
import statistics as st
from collections import Counter
from result_io import ResultError, collect_episodes, is_factor, periods, report_completeness


def mean(values):
    return f"{st.mean(values):.2f}" if values else "-"


def main(argv=None):
    parser = argparse.ArgumentParser(description="상한 주문 및 기준 대비 주문 조정 진단 (API 사용 없음)")
    parser.add_argument("folder", help="episodes/가 있는 결과 폴더")
    parser.add_argument("--seed", type=int, help="분석할 seed")
    args = parser.parse_args(argv)
    try:
        data = collect_episodes([args.folder], None if args.seed is None else [args.seed])
        report_completeness(data)
        stages = ["소매", "도매", "유통", "공장"]
        print("Q_final−Q_base는 기준 대비 조정량이며, 양수만으로 과잉 주문임을 확정하지 않습니다.")
        print("P_pre는 미입고 발주 잔량(운송 중 + 상류 미출고)이며, 가까운 시점의 입고 보장량이 아닙니다.")
        for seed in sorted({s for _, s in data}):
            eps = [(c, periods(item.path)) for (c, s), item in data.items() if s == seed]
            for cond, rows in eps:
                for w in rows:
                    if w.get("agent") not in range(4) or any(k not in w for k in ["B", "P_pre", "Q_base"]):
                        raise ResultError(f"진단에 필요한 상태 기록이 없거나 잘못되었습니다: seed {seed}, {cond}")
            print(f"\n[seed {seed}: 상한 100 주문 출처]")
            counts = Counter()
            for cond, rows in eps:
                for w in rows:
                    if w["Q_final"] != 100:
                        continue
                    group = "CMT (OUT 기준)" if is_factor(cond) else cond
                    base = w["Q_base"]
                    origin = "기준주문량 없음" if base is None else "기준도 100" if base == 100 else "기준 대비 상향 조정"
                    counts[(group, stages[w["agent"]], origin)] += 1
            for key, count in sorted(counts.items()):
                print("  " + " | ".join(key) + f": {count}회")
            if not counts:
                print("  상한 주문 없음")
            print("D의 기준량은 LR·EOQ 지원량으로, CMT의 OUT 기준과 별도로 표시합니다.")
            print("[CMT 소매점 B>0: 기준 대비 조정량]")
            for lv in ["C0", "C1", "C2", "C3"]:
                rows = [w for c, records in eps if is_factor(c) and c.startswith(lv) for w in records if w["agent"] == 0 and w["B"] > 0 and w["Q_base"] is not None]
                diffs = [w["Q_final"] - w["Q_base"] for w in rows]
                lo = [w["Q_final"] - w["Q_base"] for w in rows if w["P_pre"] < 30]
                hi = [w["Q_final"] - w["Q_base"] for w in rows if w["P_pre"] >= 30]
                print(f"  {lv}: {len(diffs)}회 | 평균 조정 {mean(diffs)} | 20 초과 상향 {sum(d > 20 for d in diffs)}회 | 최대 {max(diffs) if diffs else '-'}")
                print(f"    P_pre 30 미만: {mean(lo)} ({len(lo)}회) / 30 이상: {mean(hi)} ({len(hi)}회)")
        print("\nP_pre=30은 원본 진단의 기술적 구분값이며 최적 재고 기준이 아닙니다. 기준 대비 상향 조정에는 대체 실행·수량 보정도 영향을 줄 수 있습니다.")
    except ResultError as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
