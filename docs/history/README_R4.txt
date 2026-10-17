# SCM_LLM_Agent_Final

기존 SCM 실험에 **안전재고 실행 설정·Q_base 설명 + V1 프롬프트 정밀화 + V2 M3 상세 계획 + 양방향 상태 주체 구분**을 합친 로컬 최종본입니다. 기존 `SCM_LLM_Agent` 및 독립 V1/V2 폴더와 결과는 보존했습니다. GitHub에는 게시하지 않았습니다.

2026-10-16 수정본에는 **M2 당기 발주 설명 개선, N0 최소 프롬프트 조건, N0-G0 복구 없는 조건**을 추가했습니다. 등록 조건은 기존 103개 + 신규 2개 = **105개**입니다. N0-G0는 첫 복구 가능 호출 오류 또는 유효하지 않은 주문에서 해당 조건·seed만 즉시 중단하고, 실패 횟수와 중단 시점을 기록합니다. 기존 seed201 결과는 이전 코드로 얻은 결과이며 변경하지 않았습니다.

## 설명

- [최종 배포본 revision 4: 수정 내용·점검·소규모 실험](docs/FINAL_RELEASE.md)
- [FINAL 변경 내용·의사결정·정보 흐름](docs/FINAL_GUIDE.md)
- [M2 수정·N0·N0-G0 실행과 중단 결과 설명](docs/M2_N0_GUIDE.md)
- [안전재고·Q_base 실행 및 분석 스크립트](docs/IMPROVEMENT_EXPERIMENTS.md)
- [SCM 시스템과 코드 구성](docs/SYSTEM_GUIDE.md)
- [통합 전 기본 README 보존본](docs/BASE_README.md)

최초 통합 당시의 JSON·검사 로그는 원래 로컬 폴더에 보존합니다. 공유 배포본의 현재 검증 결과는 revision 4 문서를 기준으로 확인하세요.

V1과 V2는 각각 원본에서 만든 독립 버전입니다. 이 폴더에서 처음 두 개선을 결합했습니다. V1의 원칙에 따라 당기 주문 근거 `rationale`는 후속 모델 입력에서 제외하며, V2의 `planning_evidence`도 연구 로그에만 저장합니다. M3를 수신하는 상류는 기존과 같이 계획 정수 두 개만 받습니다.

## 실행

이 폴더에서 Python 3.11 이상으로 실행합니다. 기본 패키지 외 설치는 필요하지 않습니다. 통합 처치를 모두 적용하려면 **`run_final.py`**를 사용합니다. 안전재고는 실행자가 반드시 명시하며, 아래 `10`은 전달본의 실험값 예시입니다. `0`도 허용됩니다. 준비기간부터 적용되고 초기 재고는 별도 기본값 0입니다.

```powershell
# 계획 확인만: 파일 생성·API 호출 없음
python run_final.py --conditions C0M1T2 C0M3T2 C3M3T4 --seeds 7 --safety-stock 10 --backend openrouter --workers 3 --budget-usd 2 --output results/final_seed7 --dry-run

# 무료 소프트웨어 점검: 실제 LLM 성능 결과가 아님
python run_final.py --conditions A C0M1T2 C0M3T2 C3M3T4 D_cost D_bullwhip --seeds 7 --safety-stock 10 --backend mock --evaluation-periods 2 --output results/final_mock_seed7

# 실제 실험은 첫 번째 명령에서 --dry-run을 제거해 실행
# API 키: OPENROUTER_API_KEY 환경변수. 소스/로그에 키를 적지 않음.
```

조건과 seed를 직접 입력해야 합니다. 전체 105조건을 실행하려면 명시적으로 목록을 선택하세요.

```powershell
$scmConditions = @((Get-Content ./configs/registered_conditions.json -Raw | ConvertFrom-Json).id)
python run_final.py --conditions $scmConditions --seeds 7 --safety-stock 10 --backend openrouter --workers 16 --budget-usd 20 --output results/final_all105_seed7 --dry-run
```

기존 103조건만 선택하려면 `$scmConditions = @($scmConditions | Where-Object { $_ -notin @('N0', 'N0-G0') })`로 신규 2개를 제외합니다. `run_all_settings.py`의 기존 6개 배치 구성은 계속 원래 103조건을 사용합니다.

```powershell
# N0 두 조건 + A + 수정 M2의 소프트웨어 점검. 실제 LLM 성과 실험이 아닙니다.
python run_final.py --conditions A N0 N0-G0 C0M2T2 C3M2T2 --seeds 201 --safety-stock 10 --backend mock --evaluation-periods 2 --output results/m2_n0_mock_seed201

# 실제 API 실행 계획만 확인. --dry-run을 빼야 실제로 실행됩니다.
python run_final.py --conditions A N0 N0-G0 C0M2T2 C3M2T2 --seeds 201 --safety-stock 10 --backend openrouter --workers 5 --budget-usd 20 --output results/m2_n0_seed201 --dry-run
```

`--objective cost` 또는 `--objective bullwhip`로 A/CMT/N0/N0-G0의 목적을 선택합니다. D_cost·D_bullwhip의 목적은 기존처럼 고정이므로 전체 조건 명령에서는 objective를 생략합니다. 같은 실행을 재개할 때만 동일 명령에 `--resume`을 추가합니다. **새 소스로 이전 결과에 이어 돌릴 수 없으므로 반드시 새 결과 폴더를 사용하세요.** N0-G0의 오류 중단은 그 실행의 최종 결과이므로 `--resume`해도 다시 시도하지 않고 중단 횟수도 중복 집계하지 않습니다.

실행 후 `execution_outcomes.json`에서 조건별 완료·중단 횟수와 비율을, `failures.csv`에서 중단 원인·기·역할을 확인할 수 있습니다. 중단된 실행의 `summary.json`에는 정상 비용·서비스·채찍효과 지표가 없고, 부분 비용은 `partial_metrics`에만 보관합니다. `batch_status.json`의 `terminal=true`는 모든 실행이 완료 또는 실험적 중단으로 끝났다는 뜻이며, 모두 정상 완료했다는 뜻은 `complete=true`입니다.

`python -m scm run`은 FINAL의 V1·V2·주체 구분을 사용하지만 런타임 Q_base 문장을 추가하지 않습니다. `run_variant.py`는 안전재고만, `run_qmean.py`는 Q_base 문장까지 적용합니다. FINAL의 권장 진입점은 `run_final.py`입니다. 이름만 FINAL이라고 해서 모든 실행 명령이 같은 처치를 적용하는 것은 아닙니다. 실제 처치는 `intervention_manifest.json`과 `batch_manifest.json`으로 확인합니다.

Windows 실행기 `Run-Experiment.ps1`도 revision 3부터 `run_final.py`를 호출하며 안전재고를 반드시 받습니다. 아래 명령은 계획만 확인합니다.

```powershell
.\Run-Experiment.ps1 -Conditions A,N0,N0-G0,C0M2T2 -Seeds 201 -Backend openrouter -SafetyStock 10 -EvaluationPeriods 10 -Workers 4 -BudgetUsd 2 -Output results/final_r3_example -DryRun
```

## 검증과 한계

```powershell
python -m unittest discover -s tests -v
```

정보 출처 표시는 허용된 입력의 주체·시점을 코드가 붙이는 기능이며, 다른 에이전트의 비공개 상태를 제공하지 않습니다. 프롬프트는 자기→하류, 하류→자기 오인 둘 다 금지합니다. 다만 자연어 설명의 모든 사실을 자동 검증하거나 오류가 완전히 없어졌음을 보장하는 기능은 아닙니다. 실제 오류 감소와 비용·채찍효과 개선은 후속 LLM 실험에서 확인해야 합니다. 추가 설명과 메타데이터로 토큰 사용량은 증가할 수 있습니다.
