> **과거 개발·배포 기록**: 아래 본문은 당시 설명입니다. 현재 저장소의 사용법은 [README](../README.md)와 [USAGE](USAGE.md), 실제 R4 seed 201·202·203과의 대응은 [재현성 기록](REPRODUCIBILITY.md)을 우선하세요. 과거 seed201·103조건·파일럿 언급은 현재 R4 전체 실험과 구분합니다.

> **현재 버전 안내:** 아래는 안전재고·Q_base 실행 보조 스크립트를 처음 통합한 내용과 사용 방법입니다. 현재 정의·실행 방법·검증 범위는 [최종 배포본 revision 4](FINAL_RELEASE.md)과 [M2·N0·N0-G0 설명](M2_N0_GUIDE.md)을 우선합니다. V1·V2 결합 과정은 [FINAL 통합 안내](FINAL_GUIDE.md)에 있습니다.

# 안전재고·Q_base 설명 개선 실험

사용자가 전달한 `2차 실험 개선_코드.zip`의 추가 스크립트를 기존 프로젝트에 통합한 안내입니다. 최초 보조 스크립트 통합 당시에는 `scm/` 코드를 수정하지 않았습니다. 이후 FINAL에서는 V1·V2와 M2·N0 등의 변경이 적용되었습니다. 전달본의 처치 의미를 유지하고, 실행 경로·결과 분리·재개 검사·분석 오류를 보완했습니다. 원본 ZIP과 파일별 SHA-256이 담긴 과거 `improvement_integration.json`은 로컬에 보존하며 공유본에는 포함하지 않습니다.

## 1. 무엇을 바꾸는가

| 설정 | 실행 파일 | 안전재고 SS | Q_base 의미 문장 |
|---|---|---:|---|
| 기존 설정 | `run_variant.py` | 0 | 기존 프롬프트 |
| 안전재고 추가 | `run_variant.py` | 예: 10 | 기존 프롬프트 |
| 설명 추가 | `run_qmean.py` | 0 | 추가 |
| 두 처치 동시 적용 | `run_qmean.py` | 예: 10 | 추가 |

안전재고는 **목표 재고 수준에 더하는 수량**입니다. 10은 전달본의 실험값이며, 최적값으로 확정한 것은 아닙니다. `--safety-stock`으로 바꿀 수 있습니다. 초기 재고는 별도 변수로 기본 0이며, 안전재고를 10으로 바꾸어도 초기 재고가 자동으로 10이 되지 않습니다. 초기 재고도 바꾸려면 `--initial-inventory`를 명시해야 합니다.

일반 CMT 조건은 다음 식으로 기준 주문량을 계산합니다.

```text
IP = I + P_pre - B
Q_base_raw = max(0, forecast_h1 + forecast_h2 + SS - IP)
Q_base = Q_base_raw를 반올림하고 0~100 범위로 보정한 값
```

`raw`는 수량 보정 전 값입니다. 안전재고는 이 식의 SS를 바꾸며, 최종 발주량은 계속 LLM이 C·M·Q_base를 종합하여 결정합니다.

**안전재고는 1~30기 준비기간부터 적용됩니다.** 같은 seed·같은 설정 안에서는 모든 조건이 공통 준비기간을 사용합니다. SS=0과 SS=10 사이에서는 고객 수요 경로는 같아도 준비기간 주문과 30기 말 상태는 달라질 수 있습니다. 따라서 두 설정의 비교는 준비기간을 포함한 정책 변경 효과이며, 동일한 30기 말 상태에서 31기에 SS만 바꾸는 실험은 아닙니다. A와 D는 평가기간의 기준 주문 계산에 이 Order-up-to 식을 사용하지 않지만, 변경된 준비기간 상태는 물려받습니다.

## 2. Q_base 설명은 어디에 추가되는가

`run_qmean.py`는 실행 중 일반 CMT **최종 발주 프롬프트**에 아래 문장을 그대로 추가합니다. 파일에 저장된 기본 프롬프트는 바꾸지 않고, 실행 종료 시 함수도 원상복구합니다.

> Q_base = 0 means your on-hand inventory plus outstanding orders already cover the forecast demand for the next two periods and your current backlog; it is not a signal to build inventory.

당기 기준량이 0인지와 무관하게 일반 CMT의 주문 프롬프트에 이 조건문을 항상 덧붙입니다. 예측식·기준량 계산식·C/M 입력·발주 상한을 바꾸는 처치는 아닙니다. **별도 A와 D_cost·D_bullwhip에는 이 문장을 붙이지 않습니다.** 따라서 동일 SS에서 A·D를 다시 실행한 결과 차이는 Q_base 문장 처치 효과로 해석할 수 없습니다. LLM 응답 변동 등도 고려해야 합니다.

이 문장은 전달받은 실험 처치를 보존한 것입니다. 다음 한계가 있습니다.

- `P_pre`는 운송 중 물량뿐 아니라 상류 미출고 잔량도 포함하므로, 가까운 기간의 실제 도착을 보장하지 않습니다.
- 반올림 전 추가 필요량이 0보다 크고 0.5보다 작아도 보정된 `Q_base`는 0이 됩니다.

향후 더 엄밀하게 표현한다면 “현재 정보와 예측을 사용하는 기준 정책이 추가 발주를 권고하지 않는다”로 바꿀 수 있지만, **이번 통합에서는 처치 문장을 임의로 고치지 않았습니다.** 문장을 바꾸면 새 처치 버전으로 분리하여 새 결과 폴더에 실행하세요.

## 3. 파일별 역할

| 파일 | 역할 |
|---|---|
| `run_variant.py` | 안전재고·초기 재고를 지정하여 선택한 조건과 seed 실행 |
| `run_qmean.py` | Q_base 설명을 추가하고 선택한 조건과 seed 실행. SS와 함께 적용 가능 |
| `variant_support.py` | 공통 실행 인자, 처치 기록, 결과 폴더 잠금과 재개 검사, 실행 중 변경 복원 |
| `run_all_settings.py` | 핵심 12조건/나머지 91조건 × 개선 3설정을 순차 배치 실행 |
| `result_io.py` | 완료된 결과 읽기, 조건·seed 식별, 중복/목적 충돌 검사 |
| `analyze_seeds.py` | 지정 결과의 seed별 요인 수준·비교군 요약 |
| `compare_runs.py` | 명시한 기준 실험과 개선 실험을 같은 seed·조건끼리 비교 |
| `analyze_3seeds.py` | JSON으로 지정한 여러 설정·여러 seed의 대응 비교. 이름과 달리 seed 3개로 고정되지 않음 |
| `diagnose_overorder.py` | 상한 주문, 기준 대비 주문 조정량, 백로그·미입고 발주 잔량 조건별 진단 |
| `frozen_state_test.py` | 저장된 특정 상태를 고정하고 원문/IP 설명/Q_base 설명을 다시 묻는 별도 진단 |

분석 스크립트는 기존 결과를 읽습니다. 새 LLM 호출은 실행 스크립트 또는 상태 고정 진단에서 `--backend openrouter`로 실제 실행할 때만 발생합니다.

## 4. 선택한 조건만 실행하기

프로젝트 최상위 폴더에서 실행합니다. Windows PowerShell 예시이며 seed 7과 예산은 예시값입니다. Python 3.11 이상, 기본 실험과 같은 환경을 사용합니다.

```powershell
# 먼저 무료 실행 계획 확인: 실제 API 호출과 실험 결과 생성 없음
python run_variant.py --conditions C0M0T2 C3M0T2 --seeds 7 --backend openrouter --safety-stock 10 --workers 2 --budget-usd 2 --output results/improved_ss10_seed7 --dry-run

# 소프트웨어 동작만 검사: 30기 준비기간 + 평가 2기, API 비용 없음
python run_qmean.py --conditions A C0M0T2 D_cost --seeds 7 --backend mock --safety-stock 0 --evaluation-periods 2 --output results/check_qmean_seed7

# 실제 실행: 선택한 두 조건, 30기 준비기간 + 평가 100기
python run_variant.py --conditions C0M0T2 C3M0T2 --seeds 7 --backend openrouter --safety-stock 10 --workers 2 --budget-usd 2 --output results/improved_ss10_seed7

# Q_base 설명만 추가
python run_qmean.py --conditions C0M0T2 C3M0T2 --seeds 7 --backend openrouter --safety-stock 0 --workers 2 --budget-usd 2 --output results/improved_qmean_seed7

# 안전재고와 설명을 함께 적용
python run_qmean.py --conditions C0M0T2 C3M0T2 --seeds 7 --backend openrouter --safety-stock 10 --workers 2 --budget-usd 2 --output results/improved_both_seed7
```

기존 API 키는 `OPENROUTER_API_KEY` 환경변수로 전달하며 기록 파일에 저장하지 않습니다. 기존 모델·Flex 경로·출력 검증·재시도 정책을 사용합니다. `--evaluation-periods`는 소프트웨어 점검을 위한 단축 옵션이며, 평가기간이 다른 결과를 본 실험 결과와 섞지 마세요. `mock`의 성능은 LLM 실험 결과가 아닙니다.

## 5. 결과 분리와 재개

각 설정은 다른 `--output`을 사용합니다. 기본 결과 파일(`batch_manifest.json`, `warmup/`, `episodes/`, `results.json`, `batch_status.json`) 외에 **`intervention_manifest.json`**에 처치 문구·적용 범위·설정·관련 소스 해시를 저장합니다.

실행 중에는 기본 `scm/` 해시와 처치·실행 스크립트 해시를 결합한 서명을 사용합니다. 따라서 기본 실행과 개선 실행을 같은 폴더에서 재개하거나, Q_base 문장을 바꾼 뒤 기존 결과를 이어 쓰는 것을 차단합니다. 준비기간도 이 실행 서명으로 구분됩니다. 단순히 결과 파일 이름만 바꾸어 새 실험으로 취급하지 마세요.

```powershell
# 같은 코드·처치·조건·seed·설정의 중단된 실행만 재개
python run_qmean.py --conditions C0M0T2 C3M0T2 --seeds 7 --backend openrouter --safety-stock 0 --workers 2 --budget-usd 2 --output results/improved_qmean_seed7 --resume
```

이번 보완 전에 받은 원본 스크립트로 만든 결과에는 처치 서명이 없습니다. **분석에는 사용할 수 있지만, 이 스크립트로 그대로 재개하지는 않습니다.** 원본과 수정본을 구분하여 새 폴더에서 실행합니다. 실행 스크립트나 공통 helper 변경도 서명에 반영되므로 새 버전은 새 출력 폴더를 사용합니다.

## 6. 세 개선 설정을 모두 실행하기

`run_all_settings.py`를 명시적으로 실행했을 때만 여러 배치가 시작됩니다. 일반 개별 실행 명령이 자동으로 103조건을 선택하지 않습니다.

핵심 12조건은 C0M0T2를 공유 기준으로 C 4수준, M 5수준, T 5수준을 바꾼 중복 제외 목록입니다. 나머지 91조건은 A와 D 두 조건을 포함합니다. 안전재고 10, Q_base 설명, 두 처치 동시 적용을 각각 실행하므로 **seed 하나에 103 × 3 = 309개 episode**, 핵심/나머지로 나눈 **6배치**입니다. 원본 기준 실험(SS0·기존 문장)은 이 명령이 새로 실행하지 않습니다.

```powershell
# 실행 계획부터 확인. API 호출 없음
python run_all_settings.py --seeds 7 --tag s7 --backend openrouter --workers 16 --budget-per-batch-usd 5 --dry-run

# 실행을 결정했다면 같은 명령에서 --dry-run 제거
```

`--budget-per-batch-usd 5`는 **각 배치의 상한**이므로 6배치의 설정상 상한 합은 30달러입니다. 예상 지출액이나 전체 5달러 상한이 아닙니다. seed를 여러 개 주면 각 배치 예산 안에서 해당 seed들을 함께 처리합니다. 실제 소요시간과 지출은 API 지연·재시도·선택 조건에 따라 달라집니다. 전달본의 과거 실행 시간·비용을 현재 실행 보장값으로 사용하지 않습니다.

## 7. 결과 분석 시 해석 원칙

- 다른 seed를 먼저 평균내지 않고 **seed별 결과와 같은 seed·조건의 대응 차이**를 확인합니다.
- 기준 폴더를 명시합니다. 기준 실험이 없는데 다른 개선 설정을 자동으로 기준으로 삼지 않습니다.
- 조건별 중앙값이나 개선된 조건 수는 여러 조건에 걸친 기술통계입니다. 같은 seed의 100조합을 독립적인 수요 반복 100회로 취급하지 않습니다. 전달본의 조합·seed를 합친 부호순위 p값은 기본 분석에서 제외했습니다.
- `Q_final - Q_base`가 양수라는 것만으로 과잉 주문이라고 단정하지 않습니다. 이는 **기준 대비 상향 조정량**이며 실제 재고·비용·서비스 결과와 함께 해석합니다.
- A는 기준 주문량이 없고 D의 기준량은 일반 CMT의 Order-up-to 기준과 다릅니다. 진단에서 구분합니다.
- 같은 seed 외에 수요 해시·평가기간·모델·목적·처치·시작 상태도 비교해야 합니다. SS 변경에 따른 준비기간 상태 차이는 위에서 설명한 처치 범위에 포함됩니다.

각 분석 도구의 `--help`에서 입력 형식을 확인할 수 있습니다. 여러 설정 비교용 예시는 `configs/improvement_analysis.example.json`입니다. 결과 폴더 경로를 자신의 실제 경로로 바꾼 후 사용하세요.

```powershell
# 기존 seed5 결과의 요약과 주문 조정 진단: API 호출 없음
python analyze_seeds.py results/all103_seed5_w16_20261014-024049 --seeds 5
python diagnose_overorder.py results/all103_seed5_w16_20261014-024049 --seed 5

# 아래 baseline_seed7와 개선 결과는 해당 실행이 완료된 후 지정
python compare_runs.py --baseline results/baseline_seed7 --variant "SS10=results/improved_ss10_seed7" --variant "Qmean=results/improved_qmean_seed7" --seed 7

# 예시 JSON을 복사해 seeds와 폴더를 수정한 다음 실행
python analyze_3seeds.py --config configs/improvement_analysis.example.json

# 상태 고정 진단: 저장된 입력 중 후보만 확인, API 호출 없음
python frozen_state_test.py results/all103_seed5_w16_20261014-024049 --dry-run
```

`analyze_3seeds.py`의 JSON 안 상대 경로는 **JSON 파일 위치 기준**입니다. 예시의 seed 101~103은 전달자의 이전 실험 경로 예시이며, 이 통합으로 그 결과가 생성되거나 제공된 것은 아닙니다. `compare_runs.py` 등 분석 명령의 상대 경로는 현재 작업 폴더 기준입니다. 실행 wrapper의 `--output`은 저장소 최상위 기준으로 해석합니다.

상태 고정 진단은 C0/C1/C2의 소매점 중 `B>0`, `P_pre≥30`, `Q_final−Q_base≥20`인 상태를 원본 규칙대로 선택합니다. 기본 12개 상태 × 3문구 × 3반복으로 최대 **108개의 논리적 호출**이며, 재시도는 추가될 수 있습니다. 실제 호출은 `--backend openrouter --budget-usd ... --output 새폴더`를 모두 명시해야 합니다. 같은 상태에 대한 국소 응답 변화 진단이며, 공급망을 계속 운영한 총비용·서비스 성과 비교가 아닙니다. 원본처럼 저장된 `retry_feedback`을 제거하고 재질의하므로, 원래 성공 호출의 요청을 완전히 그대로 재현하는 것도 아닙니다. 원본 API 설정과 선택 상태, 문구, 호출 로그, 보정 후 주문량을 별도 저장합니다.

## 8. IncompleteRead 등 중단 시

현재 `scm/provider.py`는 `IncompleteRead`를 timeout·연결 오류와 같은 복구 가능한 호출 오류로 분류합니다. 일반 조건에서는 전송 오류와 형식 오류가 공유하는 최대 1회 재시도 한도를 사용하고, 이를 소진하면 단계별 대체 처리를 적용합니다. N0-G0는 재시도·대체 없이 해당 조건·seed를 실험적으로 중단합니다. 오류가 반드시 복구된다는 뜻은 아니며, 자세한 중단 정의는 [M2·N0·N0-G0 설명](M2_N0_GUIDE.md)을 확인하세요. 최초 보조 스크립트 통합 당시에는 이 통신 분류를 수정하지 않았으므로 과거 오류 기록과 현재 정책을 구분해야 합니다.

1. `batch_status.json`, 해당 episode의 `failure.json`, `api_calls.jsonl`에서 실제 오류를 확인합니다.
2. 기존 결과와 호출 비용 기록을 보존합니다. 기록을 지우거나 episode를 옮긴 뒤 기존 예산으로 재개하면, 이전 사용액이 집계에서 빠질 수 있습니다. 전달본 README의 단순 폴더 이동 복구 절차는 사용하지 않습니다.
3. 동일 소스·설정의 재개 가능한 중단에만 `--resume`을 사용합니다. N0-G0의 실험적 중단은 최종 결과이므로 재개해도 다시 호출하지 않습니다. 새로운 반복이 필요하면 조건·seed를 명시하여 **새 출력 폴더**에서 시작하고, 두 실행의 사용액을 별도로 기록합니다. 이는 중단 지점 재개가 아니라 해당 episode의 새 반복 실행입니다. 두 결과에서 유리한 부분만 골라 합치지 않습니다.
4. `.running.lock` 또는 `.intervention.running.lock`은 프로세스가 실제로 종료된 것을 확인하기 전 삭제하지 않습니다.

통신 복구 정책을 추가로 바꾸려면 G(실패 처리) 변경으로 기록하고 별도 버전으로 검증해야 합니다.

## 9. 최초 보조 스크립트 통합 당시의 검증

- 당시 기존 검사 86개와 추가 검사 9개, 총 **95개 오프라인 테스트가 통과**했습니다. 과거 `verification-tests-improvement.txt`는 로컬에 보존하며 공유본에는 포함하지 않습니다.
- 당시 통합 전후 `scm/`의 12개 Python 파일 SHA-256이 모두 일치했습니다. 과거 `improvement_integration.json`은 로컬에 보존하며 공유본에는 포함하지 않습니다.
- mock 실행에서 CMT의 주문 프롬프트에만 문장이 추가되고 A·D에는 추가되지 않음을 확인했습니다. 같은 처치 재개와 다른 처치의 재개 거부, 예외 발생 후 함수 복원도 검사했습니다.
- 안전재고 0/10에서 같은 수요 경로를 사용하면서 준비기간 상태는 달라지는 것을 확인했습니다.
- 기존 seed5의 완료 103조건을 읽었고, 같은 결과끼리 비교할 때 비용 차이가 0임을 확인했습니다.
- 유료 API를 호출하거나 실제 개선 성능을 측정한 검증은 아닙니다. 기존 결과 파일도 수정하지 않았습니다.

위 검증은 과거 통합 시점의 기록입니다. 현재 배포본의 검사와 소규모 API 점검 결과는 [revision 4 기록](FINAL_RELEASE.md)을 확인하세요.
