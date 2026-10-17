# 사용 방법

이 문서는 `run_final.py`, `variant_support.py`, `scm/runner.py`, `status.py`, `analyze_seeds.py`의 실제 인터페이스를 기준으로 작성했습니다. 명령은 별도 설명이 없으면 **저장소 루트의 Windows PowerShell**에서 실행합니다. 설명용 명령을 게시하는 작업 자체로 LLM 실험을 실행하지는 않습니다.

## 1. 설치

```powershell
git clone https://github.com/doeun6/Final-Ver.-CODE-SCM-LLM-Agent-.git
Set-Location Final-Ver.-CODE-SCM-LLM-Agent-

# 3.11 이상인지 확인
python --version
python -m venv .venv
$scmPython = Join-Path (Get-Location) '.venv/Scripts/python.exe'
& $scmPython -m pip install -r requirements.txt
& $scmPython run_final.py --help
```

런타임과 테스트는 표준 라이브러리만 사용하며 `requirements.txt`에는 외부 패키지가 없습니다. 가상환경 활성화 대신 Python 실행 파일을 직접 호출하므로 PowerShell의 활성화 스크립트 정책 변경이 필요하지 않습니다. 새 터미널에서는 `$scmPython`을 다시 지정합니다. macOS/Linux에서는 `python3 -m venv .venv`로 만들고 `.venv/bin/python`으로 같은 Python 인수를 전달할 수 있습니다.

`Run-Experiment.ps1`도 최종 실행기를 호출하지만, Codex 번들 Python이 있으면 이를 먼저 선택합니다. 가상환경 Python을 확실히 사용하려면 아래처럼 `run_final.py`를 직접 실행합니다.

## 2. 키 입력과 등록 경로

실제 API 실행에만 OpenRouter 키가 필요합니다. 다음 코드는 키를 파일에 기록하거나 화면에 출력하지 않고 현재 PowerShell 세션의 환경변수에 설정합니다.

```powershell
$scmSecureKey = Read-Host 'OpenRouter API key' -AsSecureString
$scmCredential = New-Object System.Net.NetworkCredential('', $scmSecureKey)
$env:OPENROUTER_API_KEY = $scmCredential.Password
Remove-Variable scmCredential, scmSecureKey
```

코드에 등록된 요청 경로는 다음과 같습니다.

| 항목 | 값 |
|---|---|
| endpoint | `https://openrouter.ai/api/v1/responses` |
| model | `google/gemini-2.5-flash-lite` |
| provider | `google-ai-studio/flex` |
| service tier | `flex` |
| temperature / 출력 제한 | 0.1 / 300 tokens |

응답에서 등록 모델·provider·Flex 경로를 검증하지 못하면 실험이 중단될 수 있습니다. 현재 서비스 제공 가능 여부는 별도 확인 사항이며, 다른 모델로 바꾸면 같은 연구 조건으로 취급하지 않습니다. 사용 후 현재 세션에서 키를 지우려면 `Remove-Item Env:OPENROUTER_API_KEY`를 실행합니다. `.env` 파일 자동 로드는 구현되어 있지 않습니다.

## 3. 계획 확인과 무료 소프트웨어 점검

`--dry-run`은 조건·seed·목적·안전재고·예상 호출 수를 출력합니다. **API를 호출하거나 결과 폴더를 생성하지 않으며 API 연결 테스트도 아닙니다.** 기존 출력 폴더가 있으면 재개 호환성 검사는 수행합니다.

```powershell
& $scmPython run_final.py --conditions C0M0T2 --seeds 201 --safety-stock 10 --backend openrouter --workers 1 --budget-usd 2 --output results/c0m0t2_seed201 --dry-run

& $scmPython run_final.py --conditions A C0M0T2 C3M3T4 D_cost N0 N0-G0 --seeds 201 --safety-stock 10 --backend mock --evaluation-periods 2 --output results/mock_seed201
```

`mock`은 API 없이 소프트웨어 경로를 점검하는 모의 응답입니다. 2기 평가는 진단 실행이며, 연구 성능이나 100기 결과와 비교하지 않습니다. 동일 명령을 새 실험으로 반복하려면 새 출력 폴더를 사용합니다.

## 4. 단일 조건의 실제 실행

아래 명령은 **유료 API 요청을 발생**시킵니다. 준비기간 30기는 코드 정책으로 처리하고 평가기간 100기에서 LLM을 호출합니다.

```powershell
& $scmPython run_final.py --conditions C0M0T2 --seeds 201 --safety-stock 10 --initial-inventory 0 --evaluation-periods 100 --backend openrouter --workers 1 --budget-usd 2 --output results/c0m0t2_seed201
```

`2`는 이 예시에서 선택한 배치 예산이지 예상 청구액이나 완주 보장이 아닙니다. 예산을 넘길 것으로 판단되면 새 요청을 막고 미완료로 종료합니다. 기록된 과금액과 추정치가 외부 결제액과 정확히 일치하지 않을 수 있습니다.

## 5. 전체 105조건

조건 목록은 `configs/registered_conditions.json`에서 읽습니다. 아래 첫 명령은 계획만 확인합니다.

```powershell
$scmConditions = @((Get-Content ./configs/registered_conditions.json -Raw | ConvertFrom-Json).id)
$scmConditions.Count   # 105

& $scmPython run_final.py --conditions $scmConditions --seeds 201 --safety-stock 10 --initial-inventory 0 --evaluation-periods 100 --backend openrouter --workers 4 --budget-usd 20 --output results/r4_all105_seed201 --dry-run
```

실제 실행은 같은 명령에서 `--dry-run`을 제거합니다. `20`은 예시 내부 예산입니다. `workers`는 동시에 실행할 **조건·seed 에피소드 수**이며 1~16을 지원합니다. 에피소드 안의 소매상→공장 순서는 유지합니다.

전체 조건에서는 `--objective`를 생략합니다. 이 경우 A/CMT/N0/N0-G0는 비용 목적, D_cost는 비용 목적, D_bullwhip은 발주 변동 목적입니다. D의 목적은 조건 이름과 함께 고정되어 있어, 전체 105조건에 `--objective cost`를 강제로 붙이면 D_bullwhip과 충돌합니다.

`run_all_settings.py`의 역사적 배치 구성은 103조건이므로 전체 105조건 실행에는 위 명령을 사용합니다.

## 6. seed 202 완료 후 203을 순차 실행

하나의 명령에 여러 seed와 `workers > 1`을 주면 seed 사이에 실행이 겹칠 수 있습니다. seed별 순서를 보장하려면 **별도 프로세스와 출력 폴더를 순차적으로** 실행합니다. 아래는 실제 API 실행 명령이며, seed당 예시 예산은 20 USD입니다.

```powershell
$scmConditions = @((Get-Content ./configs/registered_conditions.json -Raw | ConvertFrom-Json).id)
foreach ($scmSeed in @(202, 203)) {
    $scmOutput = "results/r4_all105_seed$scmSeed"
    & $scmPython run_final.py --conditions $scmConditions --seeds $scmSeed --safety-stock 10 --initial-inventory 0 --evaluation-periods 100 --backend openrouter --workers 4 --budget-usd 20 --output $scmOutput
    if ($LASTEXITCODE -ne 0) {
        throw "Seed $scmSeed failed; inspect its output before starting the next seed."
    }
}
```

202의 Python 프로세스가 성공 종료된 다음 203을 시작합니다. N0-G0의 의도된 실험적 중단은 배치의 예상된 결과이므로, 다른 실행이 끝나면 다음 seed로 넘어갈 수 있습니다. 배치 오류나 예산 부족에 의한 비정상 종료와 구분하세요. 위 목록에는 204·205가 없으며 실행하지 않습니다.

이미 생성된 결과를 대상으로 이 루프를 새 실행처럼 다시 시작하지 마세요. 미완료 seed의 원래 명령에만 `--resume`을 추가해 재개한 뒤 다음 seed를 진행합니다.

## 7. 진행과 종료 결과 확인

```powershell
& $scmPython status.py results/r4_all105_seed202
Get-Content results/r4_all105_seed202/batch_status.json -Raw
Get-Content results/r4_all105_seed202/execution_outcomes.json -Raw
```

`status.py`는 **종료된 summary만** 읽습니다. 실행 중 에피소드의 API 지출과 진행을 포함하지 않으므로 전체 실시간 사용액으로 해석하지 않습니다. 활성 에피소드의 마지막 저장 위치는 `episodes/<조건>__<목적>__seed-<seed>/progress.json`에 있습니다. `batch_status.json`은 종료 사건마다 갱신되므로 요청 단위의 실시간 화면은 아닙니다.

| 상태 | 뜻 |
|---|---|
| `complete: true` | 계획한 모든 에피소드가 정상 완주 |
| `terminal: true`, `complete: false` | 모두 끝났지만 N0-G0 등의 실험적 중단 포함 가능 |
| 예상치 못한 오류 / 미완료 | `batch_status.json.errors`, 각 `failure.json`을 함께 확인 |

## 8. 중단과 재개

R4 실행기에는 `--stop` 옵션이나 종료 신호 파일 기능이 없습니다. 터미널에서 `Ctrl+C`로 중단을 요청할 수 있지만, ThreadPool과 진행 중 API 요청 때문에 즉시 종료되지 않을 수 있습니다. 자동 종료를 보장하는 기능으로 해석하지 마세요. 강제 종료 시 마지막 완료 에이전트 체크포인트 이후 작업과 일부 배치 요약은 저장되지 않을 수 있습니다.

재개하기 전에 원래 실행 프로세스가 종료됐는지 확인합니다. 출력 폴더의 `.intervention.running.lock`, 에피소드별 `.running.lock`이 남아 있다면 기록된 PID·실행 프로세스를 확인한 후에만 오래된 잠금으로 판단합니다. 실행 중인 프로세스의 잠금을 삭제하거나 같은 폴더에 두 번째 실행을 시작하지 않습니다.

**원래와 같은 명령에 `--resume`을 추가**합니다. 아래는 4절 단일 조건 실행의 예입니다.

```powershell
& $scmPython run_final.py --conditions C0M0T2 --seeds 201 --safety-stock 10 --initial-inventory 0 --evaluation-periods 100 --backend openrouter --workers 1 --budget-usd 2 --output results/c0m0t2_seed201 --resume
```

- 코드·프롬프트·처치·조건 목록·seed·환경·모델 설정은 원래 실행과 같아야 합니다.
- 정상 완료된 에피소드는 다시 호출하지 않습니다. 재개 가능한 미완료 에피소드는 체크포인트와 호출 기록을 사용합니다.
- N0-G0의 `status: aborted`는 최종 결과입니다. `--resume`은 그 에피소드를 재시도하지 않습니다.
- 예산 증액은 지원하며 변경 이력을 남깁니다. 기존 사용액도 같은 배치의 한도에 포함합니다.
- 새 반복은 새 출력 폴더에 저장합니다. 여러 반복의 유리한 구간을 이어 하나의 결과로 만들지 않습니다.

## 9. 결과 파일과 기본 분석

```text
results/<실행명>/
  intervention_manifest.json   최종 진입점·SS·Q_base 문장·소스 서명
  batch_manifest.json          조건·seed·환경·API 설정·예산
  batch_status.json            배치 완료/중단/오류 집계
  results.json                 종료된 에피소드 요약 목록
  execution_outcomes.json      조건별 완료·중단 비율
  execution_outcomes.csv
  failures.json / failures.csv
  warmup/                     seed별 공통 준비기간 상태
  episodes/<조건>__<목적>__seed-<seed>/
    manifest.json
    checkpoint.json / progress.json
    summary.json              정상 완료 지표 또는 중단 결과
    periods.json / periods.csv
    api_calls.jsonl           실제 API 실행의 요청·응답·사용량
```

중단된 에피소드는 `abort.json`, `abort_snapshot.json`, `partial_periods.json` 등 부분 기록을 남기며 완주 지표가 없습니다. 그 부분 비용을 100기 완주 비용과 직접 비교하지 않습니다.

현재 저장된 완주 지표는 PowerShell로 다음과 같이 읽을 수 있습니다. 결과 파일이 아직 생성되지 않은 시점에는 실행하지 않습니다.

```powershell
$scmResults = @(Get-Content results/r4_all105_seed202/results.json -Raw | ConvertFrom-Json)
$scmResults | Where-Object { $_.complete -eq $true } | ForEach-Object {
    [pscustomobject]@{
        Condition = $_.condition
        Seed = $_.seed
        CostPerPeriod = $_.metrics.cost_per_period
        RetailerFillRate = $_.metrics.retailer_immediate_fill_rate
        GlobalBullwhip = $_.metrics.global_bullwhip
    }
} | Format-Table -AutoSize
```

`CostPerPeriod`는 4단계 공급망 비용 합을 평가기간 수로 나눈 값입니다. `RetailerFillRate`는 0~1 비율입니다. `GlobalBullwhip`은 각 단계의 평가기간 발주 CV(표본 표준편차/평균)의 곱이며 주문/고객 수요 분산비가 아닙니다. API 사용액은 별도 USD 필드입니다.

완료 에피소드만 있는 결과 폴더는 기존 기술통계 도구로도 읽을 수 있습니다.

```powershell
# 해당 폴더에 중단 summary가 없어야 함
& $scmPython analyze_seeds.py results/c0m0t2_seed201 --seeds 201
```

`analyze_seeds.py`와 `result_io.py`는 중단 summary가 섞이면 오류로 거부합니다. 따라서 **N0-G0가 중단된 전체 105조건 결과 폴더에 이 명령을 그대로 적용할 수 없습니다.** 원본에서 중단 폴더를 삭제하지 말고 `execution_outcomes.json`의 실패율과 완주 조건의 지표를 분리해서 분석합니다. 기존 `analyze_3seeds.py`는 설정 JSON으로 기준·변형 실행을 비교하는 보조 도구이며, 이번 R4 seed 세 개를 자동으로 논문 표·엑셀·대화형 산점도로 만드는 범용 명령은 아닙니다.

완료 여부뿐 아니라 서로 같은 source/configuration인지 manifest를 확인하고, 같은 조건·seed의 재시도 실행이 두 폴더에 있으면 사용할 실행을 명시합니다. 조건 수나 기간별 행 수를 독립 반복 수로 취급하지 않습니다.

## 10. 주요 옵션 요약

| 옵션 | 의미 / 기본값 |
|---|---|
| `--conditions` | 필수. 하나 이상의 등록 ID |
| `--seeds` | 필수. 하나 이상의 중복 없는 정수 |
| `--backend` | 필수. `mock` 또는 `openrouter` |
| `--safety-stock` | 최종 실행기 필수. 유한한 0 이상 값; R4 분석 실험은 10 |
| `--output` | 필수. 상대 경로는 저장소 루트 기준 |
| `--initial-inventory` | 0 이상 정수, 기본 0 |
| `--evaluation-periods` | 양의 정수, 기본 100; 다른 값은 진단용 |
| `--workers` | 1~16, 기본 1 |
| `--budget-usd` | 양수, 최종 실행기 기본 10; 전체 배치 한도 |
| `--objective` | `cost` 또는 `bullwhip`; D 조건 목적은 고정 |
| `--dry-run` | 계획 검증만, API·결과 생성 없음 |
| `--resume` | 동일 소스·설정·출력 폴더의 재개 |

`python -m scm run`, `run_variant.py`, `run_qmean.py`는 다른 진입점입니다. 같은 파일 트리에서 실행해도 런타임 처치가 같지 않으므로 R4 최종 처치에는 `run_final.py`를 사용합니다.
