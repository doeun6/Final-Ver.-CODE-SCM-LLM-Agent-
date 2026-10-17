"""Seed-wise matched analyses from a JSON mapping (any seed count; no pooled p-values)."""
import argparse
from pathlib import Path
from result_io import ResultError, cap_count, collect_episodes, groups, is_factor, median, paired_keys, print_pair_summary, read_json, report_completeness, validate_objectives

CORE = "C0M0T2 C1M0T2 C2M0T2 C3M0T2 C0M1T2 C0M2T2 C0M3T2 C0M4T2 C0M0T0 C0M0T1 C0M0T3 C0M0T4".split()


def load_config(path):
    path = Path(path).resolve()
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        raise ResultError("설정 JSON은 객체여야 합니다.")
    seeds, variants, baseline = cfg.get("seeds"), cfg.get("variants"), cfg.get("baseline")
    if not isinstance(seeds, list) or not seeds or any(type(s) is not int for s in seeds) or len(set(seeds)) != len(seeds):
        raise ResultError("config.seeds는 중복 없는 정수 목록이어야 합니다.")
    if not isinstance(variants, dict) or len(variants) < 2 or not isinstance(baseline, str) or baseline not in variants:
        raise ResultError("config.variants에는 기준을 포함한 2개 이상 설정이 필요하며 config.baseline은 그 이름이어야 합니다.")
    data = {}
    for name, by_seed in variants.items():
        if not name or not isinstance(by_seed, dict):
            raise ResultError(f"설정 {name!r}: seed별 폴더 목록이 필요합니다.")
        items = {}
        for seed in seeds:
            folders = by_seed.get(str(seed))
            if not isinstance(folders, list) or not folders or any(not isinstance(x, str) or not x for x in folders):
                raise ResultError(f"설정 {name}, seed {seed}: 결과 폴더 문자열 목록이 필요합니다.")
            resolved = [Path(f) if Path(f).is_absolute() else path.parent / f for f in folders]
            items.update(collect_episodes(resolved, [seed]))
        validate_objectives(items)
        data[name] = items
    return seeds, baseline, data


def main(argv=None):
    parser = argparse.ArgumentParser(description="JSON에 지정한 seed·설정별 대응 기술통계 (시드 수 제한 없음, API 사용 없음)")
    parser.add_argument("--config", required=True, help="baseline, seeds, variants를 가진 JSON. 상대 경로는 JSON 파일 기준")
    args = parser.parse_args(argv)
    try:
        seeds, baseline, data = load_config(args.config)
        base = data[baseline]
        matches = {name: paired_keys(base, items) for name, items in data.items() if name != baseline}
        print("[완료 현황]")
        for name, items in data.items():
            report_completeness(items, name)
        print("기술통계만 출력합니다. 같은 seed의 여러 조건을 독립 반복으로 간주하는 통합 p값은 산출하지 않습니다.")
        for seed in seeds:
            print(f"\n========== seed {seed} ==========")
            for name, items in data.items():
                if name == baseline:
                    continue
                ks = [k for k in matches[name] if k[1] == seed and is_factor(k[0])]
                if not ks:
                    raise ResultError(f"seed {seed}: {name}와 {baseline} 사이 공통 CMT 조건이 없습니다.")
                base_only = {k for k in base if k[1] == seed} - set(items)
                variant_only = {k for k in items if k[1] == seed} - set(base)
                print(f"\n[{name} vs {baseline}; 공통 CMT {len(ks)}조건; 짝 없는 기준 {len(base_only)}, 개선 {len(variant_only)}]")
                for label, fits in groups():
                    selected = [k for k in ks if fits(k[0])]
                    if selected:
                        print_pair_summary(base, items, selected, label)
                print(f"  상한100 주문 합: {sum(cap_count(base[k]) for k in ks)} → {sum(cap_count(items[k]) for k in ks)}")
                for metric, title in [("retailer_immediate_fill_rate", "소매 즉시충족률(0~1)"), ("global_bullwhip", "채찍효과")]:
                    valid = [k for k in ks if base[k].metrics.get(metric) is not None and items[k].metrics.get(metric) is not None]
                    print(f"  {title} 중앙값: {median(base[k].metrics[metric] for k in valid)} → {median(items[k].metrics[metric] for k in valid)} (유효 {len(valid)}쌍)")
            print("\n[핵심 12조건 및 비교군: 기당 비용]")
            for cond in CORE + ["A", "D_cost", "D_bullwhip"]:
                cells = [f"{name} {median([items[(cond, seed)].metrics['cost_per_period']]) if (cond, seed) in items else '-'}" for name, items in data.items()]
                print(f"  {cond}: " + " | ".join(cells))
            print("\n[설정 내 요인 수준별 대응 비교: 같은 나머지 요인을 고정]")
            for name, items in data.items():
                print(f"  ({name})")
                for pos, ref, levels in [(0, "C0", ["C1", "C2", "C3"]), (2, "M0", ["M1", "M2", "M3", "M4"]), (4, "T2", ["T0", "T1", "T3", "T4"])]:
                    for lv in levels:
                        diffs = []
                        for (cond, sd), item in items.items():
                            if sd == seed and is_factor(cond) and cond[pos:pos + 2] == lv:
                                ref_key = (cond[:pos] + ref + cond[pos + 2:], seed)
                                if ref_key in items:
                                    if item.objective != items[ref_key].objective:
                                        raise ResultError(f"요인 수준 비교 목적 불일치: {name}, {cond} vs {ref_key[0]}")
                                    diffs.append(item.metrics["cost_per_period"] - items[ref_key].metrics["cost_per_period"])
                        print(f"    {lv} vs {ref}: 감소 {sum(d < 0 for d in diffs)}/{len(diffs)} | 대응 차이 중앙값 {median(diffs)}")
        print("\n차이는 비교수준−기준수준입니다. 없는 조건은 대응 비교에서 제외합니다. seed 간 결과를 평균내지 않았으며 조건 수는 독립 seed 반복 수가 아닙니다.")
    except ResultError as exc:
        parser.exit(2, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
