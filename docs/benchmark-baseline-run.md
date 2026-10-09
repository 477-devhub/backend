# 477 실제 baseline 실행

기준 입력은 변경하지 않은 `477_modeling_benchmark_v1`의 로더·프롬프트·스키마다.
벤치마크, final_candidates_v1, data, media에는 출력이나 pycache를 만들지 않는다.
현재 패키지는 정답이 없는 소규모 데모이며 정확도·오경보율을 산출할 수 없다.
사전 기준과 예산 계산은 `benchmark-baseline-plan.md`에 있다.

## 설치

프로젝트 루트 PowerShell에서 실행한다. Python 3.11 CPU 환경 기준이다.

```powershell
py -3.11 -m venv .venv-benchmark
.\.venv-benchmark\Scripts\python.exe -m pip install --upgrade pip
.\.venv-benchmark\Scripts\python.exe -m pip install torch==2.9.1+cpu torchvision==0.24.1+cpu --extra-index-url https://download.pytorch.org/whl/cpu
.\.venv-benchmark\Scripts\python.exe -m pip install -e ".[dev,benchmark]"
```

기존 `.env`를 사용한다. VLM_API_KEY, VLM_MODEL=deepseek-flash,
CLEF_API_TOKEN, CLEF_ACCOUNT, CLEF_MODEL=clef가 필요하다. 키 값을 출력하지 않는다.
VLM은 DeepSeek API, Clef는 Cloudflare Workers AI다. CV는 CPU 로컬 추론이다.

공식 Ultralytics assets v8.4.0에서 받은 가중치는 `artifacts/models`에 보관한다.
탐지 SHA256: `646f8bc3fe0a656803d95c294f7852321748cb29d13466a1af8862e2db384a1b`.
자세 SHA256: `a083adb42303728ae14c4bd6bd56d80da46f82fb2564dbd6f31dcc92ea321646`.

## 독립 CV 점검

```powershell
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_cv.py --item ITEM_01
```

결과는 `runs/cv-diagnostic/ITEM_01.json`에 저장된다. 64장 전체를 탐지·추적하고
동일 프레임에 자세 분석을 수행한다. 탐지 confidence는 사건 확률이 아니다.
구역이 정의되지 않아 침입은 판단 불가이고, dwell/자세는 관측 후보다.
위험축은 미측정 `null`, 위험점수 UNKNOWN, 사람 검토 대상으로 남긴다.

## 실패 확인

오류 코드는 `credentials_missing`, `provider_http_error`, `payload_limit`,
`timeout`, `worker_error`, `budget_exhausted` 등이다. 공급자 원본 응답은
자격정보를 제거한 뒤 별도 저장하며, 실패를 정상 prediction으로 변환하지 않는다.
예산 ledger의 실패·취소 요청 예약액은 재실행 때도 유지한다. 청구가 확인되지
않은 비용은 실제 비용이라고 부르지 않고 usage 기반 추정으로 기록한다.

## 전체 비교 및 독립 실행

```powershell
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_baseline.py --mode suite --repeats 3 --output runs/baseline-final
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_baseline.py --mode local_cv --items ITEM_01 --repeats 1
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_baseline.py --mode clef --items ITEM_01 --repeats 1
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_baseline.py --mode vlm --items ITEM_01 --repeats 1
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_baseline.py --mode pipeline --items ITEM_01 --repeats 1
```

suite는 VLM 단독과 CV→Clef→VLM을 각각 실행한다. clef 모드는 동일 64장에서
CV 상태를 추출한 뒤 Clef만 평가하며 VLM으로 연결하지 않는다. 로컬 CV는
독립 결과를 저장하되 행동 판단을 완료했다고 표시하지 않는다.

유료 요청은 모든 명령에서 `runs/477-paid-budget.json`의 동일 $5 한도를 공유한다.
실패·취소 예약도 남는다. 기존 결과 폴더 덮어쓰기를 거부한다.
결과 폴더의 summary.json, evaluation.csv, failures.json, 모델 원본 응답,
공통 assessment, 유효한 frozen 제출 결과를 확인한다. provider probe와 CV
diagnostic은 suite 성능 통계에서 제외하지만 비용 ledger에는 probe를 포함한다.

모든 시간은 실제 측정이며 decode, 모델 전처리, 추론, 전체를 구분한다.
로컬 CV는 매 실행 새 subprocess로 모델을 로드하므로 최초 로드가 포함된다.
API 공급자 내부 캐시·cold start·GPU 메모리는 확인되지 않으면 미측정이다.

최종 suite의 VLM 직렬화는 원본 해상도 JPEG 품질 80으로 고정한다. 품질 90
사전 점검은 세 ITEM에서 48MiB 상한을 넘었으며 별도 기록으로 유지한다.
숫자 시각 비교의 허용 범위는 ±1/30초이고 이진 부동소수점 계산 오차를
처리하는 1e-9초 여유만 추가한다. 프레임이나 원본 prediction을 수정하지 않는다.

로컬 가중치와 패키지 버전은 동결하지만 API 공급자의 내부 체크포인트는
고정할 수 없다. 요청 모델과 응답 모델 ID, 실행 시각·사용량·가격 기준을
남기고 내부 버전을 확인하지 못하면 미확인으로 표시한다.
