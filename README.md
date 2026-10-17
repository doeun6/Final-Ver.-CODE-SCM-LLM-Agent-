# SCM_LLM_Agent_Harness

4단계 공급망에서 LLM 에이전트의 관측 정보(C), 상류로 보내는 메시지(M), 예측 지원(T)을 비교하는 Python 실험 코드입니다. 연구에 사용한 FINAL revision 4(R4)를 보존하고 사용 방법과 코드 설명을 정리한 배포본입니다.

핵심 실험은 `C 4수준 × M 5수준 × T 5수준 = 100조건`이며, 비교조건 `A`, `D_cost`, `D_bullwhip`, `N0`, `N0-G0`를 더해 **105조건**을 지원합니다. 실행 진입점은 `run_final.py`입니다.

- [설치·실행·순차 실행·재개·결과 확인](docs/USAGE.md)
- [공급망·의사결정·모듈 설명](docs/CODE_GUIDE.md)
- [환경·C/M/T·비교조건·평가 설계](docs/EXPERIMENT_DESIGN.md)
- [실제 seed 201·202·203 실행본과의 대응·해시·검증](docs/REPRODUCIBILITY.md)
- [R4 변경 이력과 당시 검증 범위](docs/FINAL_RELEASE.md)
- [M2·N0·N0-G0 정의와 중단 처리](docs/M2_N0_GUIDE.md)

## 어떤 실험인가?

```text
고객 → 소매상 → 도매상 → 유통업자 → 공장 → 외부 공급원
          주문과 메시지: 하류 → 상류
          제품의 이동:   상류 → 하류
```

각 에이전트는 자기 상태와 허용된 메시지를 관측해 상류에 주문합니다. 준비기간 30기 이후 100기를 평가하며, 같은 seed의 조건들은 공통 수요와 준비기간 상태를 사용합니다. 수요 seed는 LLM 출력의 난수까지 고정하지 않습니다.

| 요인 | 수준 |
|---|---|
| C: 자기 운영 이력 | C0: 10기 원자료 / C1: 20기 원자료 / C2: 5기 원자료 / C3: 10기 요약 |
| M: 상류 추가 정보 | M0: 없음 / M1: 상태 / M2: 당기 확정 주문의 이유 / M3: 향후 2기 주문 계획 / M4: 자유 메시지 |
| T: 예측 지원 | T0: LLM 자유 예측 / T1: 고정 LR·LLM 계산 / T2: 고정 LR·코드 계산 / T3: 방법 선택·LLM 계산 / T4: 방법 선택·코드 계산 |

CMT 조건의 예측 입력은 C 창 길이와 별도로 **자기 수주 이력 30기**를 사용합니다. 선택 가능한 예측 방법은 선형회귀(LR), 30기 이동평균(MA30), 단순지수평활(SES)입니다. 메시지는 현재 주문을 확정한 후 상류에 전달하며, 소매상은 다른 공급망 에이전트의 메시지를 받지 않습니다.

| 비교조건 | 동작 |
|---|---|
| A | C0·M0에서 상세 공통 주문 지시로 LLM이 직접 주문. CMT의 예측·OUT 기준량은 제공하지 않음 |
| D_cost | C0·M4, LR30의 1기 예측 참조값을 받아 비용 목적의 LLM 주문 |
| D_bullwhip | C0·M4, EOQ30 참조값을 받아 발주 변동 목적의 LLM 주문 |
| N0 | C0·M0에서 최소 프롬프트로 직접 주문. 일반 복구 정책 적용 |
| N0-G0 | N0와 같은 최소 프롬프트, 재시도·수량 보정·대체 없이 첫 대상 오류에 해당 에피소드 종료 |

## 빠르게 확인하기

**Python 3.11 이상**이 필요합니다. 실행·테스트·기본 분석은 Python 표준 라이브러리만 사용합니다. 아래는 Windows PowerShell 예시이며 저장소 루트에서 실행합니다.

```powershell
python --version
python -m venv .venv
$scmPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $scmPython -m pip install -r requirements.txt

# 실제 API 호출과 결과 파일 생성 없이 실행 계획 확인
& $scmPython run_final.py --conditions A C0M0T2 D_cost N0 N0-G0 --seeds 201 --safety-stock 10 --backend openrouter --workers 1 --budget-usd 2 --output results/plan_seed201 --dry-run

# API 없이 짧은 소프트웨어 동작 확인; 연구 성능 결과로 사용하지 않음
& $scmPython run_final.py --conditions A C0M0T2 D_cost N0 N0-G0 --seeds 201 --safety-stock 10 --backend mock --evaluation-periods 2 --output results/mock_seed201

# 회귀 테스트: 유료 API 호출 없음
& $scmPython -m unittest discover -s tests -v
```

실제 LLM 실행은 `OPENROUTER_API_KEY` 환경변수를 설정한 뒤 `--backend openrouter`에서 `--dry-run` 없이 실행합니다. 키 입력, 단일 조건, 전체 105조건, **202→203 순차 실행** 명령은 [사용 방법](docs/USAGE.md)에 있습니다.

## 연구 실행 설정

| 항목 | R4 seed 201·202·203에 적용한 설정 |
|---|---|
| 공급망 | 소매상·도매상·유통업자·공장, 직렬 4단계 |
| 준비 / 평가 | 30기 / 100기 |
| 고객 수요 | 정규분포 평균 10·표준편차 3에서 생성 후 반올림·음수 0 처리 |
| 제품 리드타임 | 출하 후 2기; 주문 전달 지연과 구분 |
| 주문 | 0~100 정수 |
| 백로그 | 허용, 소멸시키지 않고 후속 기에서 처리 |
| 초기 재고 / 안전재고 계수 | 0 / 10 (`--safety-stock 10` 필수 지정) |
| 비용 | 보유·백로그·단위 주문 비용 각 1, 양수 주문의 고정비 1 |
| 모델 | `google/gemini-2.5-flash-lite` |
| 코드에 등록된 경로 | OpenRouter Responses → `google-ai-studio/flex` |
| 생성 설정 | temperature 0.1, 출력 최대 300 tokens, 일반 조건 최대 1회 재시도 |

안전재고 10은 OUT 목표량에 더하는 설정이며 **항상 재고 10을 유지시키는 하한이 아닙니다**. `SimulationConfig` 자체 기본값은 0이지만, R4 실험은 최종 실행기에 10을 명시했습니다. 환경·하네스의 상세 구분은 [코드 설명](docs/CODE_GUIDE.md)을 참고하세요.

위 모델·경로는 저장된 코드 설정입니다. 현재 서비스 제공 여부와 응답 내용까지 재현을 보장하지는 않습니다. `--budget-usd`는 코드 내부 요청 제어 한도이며 예상 요금이나 외부 결제의 절대 상한이 아닙니다.

## 결과와 재현성

각 실행은 환경·모델·조건·seed·소스 해시를 manifest에 기록합니다. 완료 결과는 `episodes/<조건>__<목적>__seed-<seed>/summary.json`, 기간별 상태는 `periods.json` 및 `periods.csv`, 실제 요청·응답은 `api_calls.jsonl`에 저장합니다.

- `execution_outcomes.json`과 `failures.csv`에서 정상 완료와 실험적 중단을 구분합니다.
- `N0-G0`의 중단은 그 실행의 최종 실험 결과이며 `--resume`으로 다시 시도하지 않습니다.
- 소스·프롬프트·과학적 설정이 바뀌면 기존 결과 폴더에 이어 실행하지 않습니다.
- 공급망 비용과 API 비용(USD)은 별개입니다. BW는 4개 단계의 **발주 CV를 곱한 지표**이며 일반적인 주문/수요 분산비와 구분합니다.
- 동일 수요 seed에서도 LLM 경로는 달라질 수 있습니다. `mock` 결과는 실제 LLM 성과가 아닙니다.

이 저장소의 주된 배포 대상은 코드·테스트·설명서입니다. 로컬의 전체 실험 결과와 API 로그는 별도 연구 자료입니다. 원논문의 정확한 재현판이라고 주장하지 않으며, 현재 문서의 설정 설명과 개별 가정의 문헌 출처 확인은 구분합니다.

기존 `docs/FINAL_GUIDE.md`, `docs/BASE_README.md` 등에는 통합 과정과 이전 시점의 설명이 남아 있습니다. 현재 실행 방법은 이 README와 [USAGE](docs/USAGE.md)를 우선하고, 실제 실행에 적용된 값은 해당 결과의 manifest를 확인하세요.
