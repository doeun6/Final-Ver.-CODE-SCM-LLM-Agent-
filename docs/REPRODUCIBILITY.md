# 실행본과 공개 코드의 대응

이 저장소는 **SCM_LLM_Agent_Harness revision 4**의 공개 배포본입니다. R4 seed **201·202·203**에 사용한 동결 코드에서 가져왔습니다. 공개를 위해 README와 설명 문서, 배포 파일 검증 도구를 추가했으며 실험의 Python 소스·설정·테스트·PowerShell 실행기는 변경하지 않았습니다.

## 보존한 실행 식별자

| 항목 | 값 |
|---|---|
| implementation_revision | 4 |
| scm_source_hash | `e6af3433b1badda8040bf4f39669a3eba3b781da60cb7dba32fcc1009fd136c5` |
| runtime_source_hash | `fd3e7d81a74b3bf45463cb9d2d862cebc1cdf6f8d6f25587ff320b42500ba9b2` |
| 진입점 | `run_final.py` |
| 안전재고 | 명시적 실행 인수 `--safety-stock 10` |
| 준비·평가 기간 | 30기·100기 |
| 조건 | CMT 100 + A + D_cost + D_bullwhip + N0 + N0-G0 = 105 |
| 모델 | `google/gemini-2.5-flash-lite` |
| 경로 | OpenRouter Responses API → `google-ai-studio/flex` |

모델 경로와 API 단가는 **해당 실행에 저장된 설정**입니다. 현재 제공 여부나 가격의 보장은 아닙니다. 코드가 성공 응답의 모델·provider·tier를 검사하므로 서비스 경로가 바뀌면 실행이 거절될 수 있습니다. 재현을 위해 경로를 임의로 바꾼 뒤 같은 실험으로 취급하지 마세요.

`runtime_source_hash`는 실행 코드와 intervention을 묶은 식별자이고, Git 커밋이나 공개 문서 전체의 해시가 아닙니다. 파일별 비교와 환경·API 설정은 [R4_EXECUTION_PROVENANCE.json](provenance/R4_EXECUTION_PROVENANCE.json)에 있습니다. 이 파일은 기존 실행 감사에서 경로·API 원문·로컬 실행 제어 정보를 제외한 공개용 기록입니다. 원시 결과 자체를 첨부한 것은 아닙니다.

## 세 seed의 상태

| seed | 완주 | 실험적 중단 | 처리 |
|---|---:|---:|---|
| 201 | 104 | 1 | N0-G0 중단을 실패 결과로 보존 |
| 202 | 104 | 1 | N0-G0 중단을 실패 결과로 보존 |
| 203 | 105 | 0 | 전체 완주 |

Seed 202의 C0M4T1은 HTTP 520 오류로 중단된 시도와 최종 재실행을 구분했습니다. 성과 분석에는 최종 완주 궤적을 사용하며, 중단 시도를 완주 결과와 합치지 않습니다. 204·205는 취소되어 최종 3-seed 분석에 포함되지 않습니다.

수요 seed가 같으면 공통 외생 수요를 재현하지만, 모델 응답의 재현성을 보장하는 LLM seed는 지정하지 않습니다. API 응답, 동시 실행, 재시도, 제공자 변화 때문에 재실행 결과가 기존 값과 완전히 같지 않을 수 있습니다. 새 실행은 새 결과 폴더에 보존하고, 변경한 설정·코드 해시를 함께 기록하세요.

N0-G0의 중단 부분 비용은 100기 완주 비용과 비교하지 않습니다. `--resume`은 실험적으로 중단된 N0-G0를 새로 실행하지 않습니다. 완주 비교와 실패율 보고를 구분해야 합니다.

## 원본과 공개 배포본의 파일 해시

- [원본 release manifest](provenance/R4_ORIGINAL_RELEASE_MANIFEST.json): 공개 문서 갱신 전 64개 파일의 해시입니다. 본 저장소 전체를 검증하는 목록으로 사용하지 않습니다.
- [원본 README 보존본](history/README_R4.txt): 원본 README의 바이트를 그대로 보존한 역사 자료입니다. 내부의 상대 링크와 과거 배포 설명은 당시 위치를 기준으로 합니다.
- [공개 release manifest](../RELEASE_MANIFEST.json): 이 공개 배포본의 파일별 SHA-256입니다. 자기 자신과 `.git`, 생성 결과는 제외합니다.
- `.gitattributes`는 체크아웃 시 개행 자동 변환을 막아 동결 소스의 바이트를 보존합니다.

저장소 루트에서 공개 파일의 무결성을 확인할 수 있습니다. 이 명령은 API를 호출하지 않습니다.

```powershell
python verification/verify_release.py
```

## 소프트웨어 검증

```powershell
# 네트워크 차단·키 제거 상태에서 단위검사와 105조건×2기 mock 실행
python verification/offline_validation.py . work/offline_validation
```

배포 시 검증 요약은 [publication_validation.json](provenance/publication_validation.json)에 있습니다. Mock 검증은 프로그램의 작동 검증이며 실제 LLM 성과 자료가 아닙니다. 본 공개 작업에서는 유료 API 실험을 추가로 실행하지 않았습니다.

기존 `docs/FINAL_RELEASE.md`, `docs/verification/` 등의 파일럿 기록은 **7조건·평가 10기의 과거 점검 자료**를 포함합니다. R4 201·202·203의 105조건·평가 100기 본실험과 혼동하지 마세요. 현재 사용법과 설정은 [USAGE](USAGE.md), [CODE_GUIDE](CODE_GUIDE.md), [EXPERIMENT_DESIGN](EXPERIMENT_DESIGN.md)을 먼저 읽으세요.

API 키, `.env`, 전체 실행 결과, API 호출 원문, 로컬 프로세스 제어 파일은 공개 소스에 포함하지 않습니다. 연구의 실행 코드를 설명하는 배포본이며, 원논문 실험을 그대로 재현했다는 주장은 하지 않습니다.
