"""Compare one seed across explicitly named settings, using matched conditions."""
import argparse
from result_io import ResultError, cap_count, collect_episodes, groups, is_factor, median, paired_keys, print_pair_summary, report_completeness


def main(argv=None):
    parser = argparse.ArgumentParser(description="같은 seed의 기준·개선 설정 대응 비교 (기술통계, API 사용 없음)")
    parser.add_argument("--baseline", required=True, help="기준 배치 결과 폴더")
    parser.add_argument("--variant", required=True, action="append", metavar="NAME=FOLDER", help="개선 설정 이름=결과 폴더 (여러 번 지정 가능)")
    parser.add_argument("--seed", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        base = collect_episodes([args.baseline], [args.seed])
        data = {}
        for value in args.variant:
            if "=" not in value:
                raise ResultError("--variant는 NAME=FOLDER 형식이어야 합니다.")
            name, folder = value.split("=", 1)
            if not name.strip() or not folder.strip() or name in data or name == "기준":
                raise ResultError(f"설정 이름은 비어 있지 않고 중복되지 않아야 합니다: {name!r}")
            data[name] = collect_episodes([folder], [args.seed])
        comparisons = {name: paired_keys(base, items) for name, items in data.items()}
        report_completeness(base, "기준")
        print("대응 차이는 개선−기준입니다. 조건 간 비교는 기술통계이며 독립 seed 반복 수가 아닙니다.")
        for name, items in data.items():
            report_completeness(items, name)
            keys = comparisons[name]
            fac = [k for k in keys if is_factor(k[0])]
            print(f"\n[{name} vs 기준 | seed {args.seed} | 공통 CMT {len(fac)}조건]")
            print(f"짝 없는 결과: 기준 {len(set(base) - set(items))}개 / 개선 {len(set(items) - set(base))}개 (대응 비교 제외)")
            for label, matches in groups():
                ks = [k for k in fac if matches(k[0])]
                if ks:
                    print_pair_summary(base, items, ks, label)
            if fac:
                print(f"  상한100 주문 합: {sum(cap_count(base[k]) for k in fac)} → {sum(cap_count(items[k]) for k in fac)}")
                for metric, title in [("retailer_immediate_fill_rate", "소매 즉시충족률(0~1)"), ("global_bullwhip", "채찍효과")]:
                    valid = [k for k in fac if base[k].metrics.get(metric) is not None and items[k].metrics.get(metric) is not None]
                    print(f"  {title} 중앙값: {median(base[k].metrics[metric] for k in valid)} → {median(items[k].metrics[metric] for k in valid)} (유효 {len(valid)}쌍)")
            print("[비교군 기당 비용: 기준 → 개선]")
            for cond in ["A", "D_cost", "D_bullwhip"]:
                k = (cond, args.seed)
                a = median([base[k].metrics["cost_per_period"]]) if k in base else "-"
                b = median([items[k].metrics["cost_per_period"]]) if k in items else "-"
                print(f"  {cond}: {a} → {b}")
        print("\n고객 수요 해시(있는 경우), 목적 및 평가 기간을 대조했습니다. 안전재고 변경에 따른 준비기간 상태 변화는 별도의 설계 해석 대상입니다.")
    except ResultError as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
