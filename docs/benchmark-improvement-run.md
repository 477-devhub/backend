# 개선 실험 실행 가이드

기존 설치·환경변수·모델 가중치는 `benchmark-baseline-run.md`와 같다.
PowerShell에서 저장소 루트로 이동하고 `.env`의 VLM_API_KEY/VLM_MODEL,
CLEF_API_TOKEN/CLEF_ACCOUNT/CLEF_MODEL을 사용한다. 키 값을 화면에 출력하지 않는다.
기존 입력 패키지·데이터·원본 결과는 수정하지 않는다.

## 실제 실행 명령

```powershell
.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode suite --repeats 1 --cv-profile pose-always --output runs/improved-canonical64
.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode pipeline --repeats 1 --items ITEM_03 ITEM_06 ITEM_02 --cv-profile pose-off --output runs/improved-pose-off
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/improved-canonical64
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/improved-pose-off
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_improvements.py --output runs/improvement-analysis
```

JSON 문법 오류가 난 ITEM_04는 원래 결과를 보존하고 다음 별도 실험을 실행했다.

```powershell
.venv-benchmark/Scripts/python.exe -B scripts/run_benchmark_baseline.py --mode vlm --repeats 1 --items ITEM_04 --vlm-transport deepseek_json_labels_v3 --output runs/improved-json-labels-item04
.venv-benchmark/Scripts/python.exe -B scripts/analyze_benchmark_baseline.py --run runs/improved-json-labels-item04
```

v3는 같은64장/JPEG80/원본prompt/schema에 JSON 형식 프레임 라벨을 붙인다.
출력 상한4096tokens이며 v2의8192와 다르다. 이 1건은 기존7항목 통계에 합치지 않는다.
기존 v2가 기본값이며 성공한 출력만 골라 기존 실패 결과를 바꾸지 않는다.

첫 실행은 동일64프레임 VLM 단독과 전체CV→Clef→VLM 비교, 두 번째는
별도 pose-off 속도 실험이다. 새 전송 형식은 `deepseek_timestamp_copy_v2`로
기록하며 공통 원본 prompt/schema를 바꾸지 않는다. 원본baseline과 변환 차이를
구분해서 비교한다. 새 조건은 항목별1회라 반복3회인 baseline과 통계적으로
동일한 평가가 아니며, 정확도 비회귀 주장은 하지 않는다.

결과폴더가 이미 채워져 있으면 덮어쓰지 않는다. 다른 경로를 지정해야 한다.
원래 원본 결과도 다시 실행/분석으로 변경하지 않는다. 완료 여부는 `summary.json`,
stage별 원본은 `raw/`, 검증/오류는 `diagnostics/`, 공통결과는 `common/`,
원본schema를 통과한 결과만 `submissions/`에 저장된다.

## 비용 및 재실행 주의

모든 유료 실행은 `runs/477-paid-budget.json`의 기존 누적 $5 ledger를 공유한다.
위 두 실험의 추가최대 예약은$1.48047360이며 이전59requests 예약$3.45235968을
더하면$4.93283328이다. 요청실패에도 과금 여부를 모를 수 있으므로 예약은
돌려주지 않는다. 실제청구 확인이 아닌 사용량 기반 비용 추정이다.
캐시미사용·최대토큰 가정의 추가모델요금 계산은$0.74023680이며,
별도로2배 안전예약을 잡는다. 실제사용량 비용과 청구서는 결과 후 구분한다.

위 실행 뒤에는 여유예약이 거의 없어 동일 명령을 다시 실행할 수 없다.
CLI가 계획최대 호출비용을 미리 검사해, 남은 예산보다 크면 API 호출 전에 중단한다.
계속 실행하려고 ledger를 삭제하거나 다른 파일로 바꾸지 않는다.
추가 유료 실험은 별도의 사용자 승인 예산이 필요하다.

실제 실행은 위 두 실험과 v3 단건까지 완료했다. v3의 최대 모델요금 추정은
$0.029376, 안전예약은$0.058752다. 누적예약은 **$4.99158528 / $5**,
87예약 중86건의 토큰사용량 확인분 추정 합계는$0.523827864다.
Clef HTTP429 1건의 사용량이 없어 총비용 추정과 실제청구액은 null이다.
예약잔여$0.00841472로 추가 모델 호출을 진행하지 않는다. 알려진 부분합을
전체 실제비용으로 읽지 않는다. 현재 정확한 집계는 `runs/improvement-analysis/comparison.json`.

## 실패 확인

- `payload_limit`: stage명을 먼저 확인한다. Clef는196608bytebody 보호;
  DeepSeek는48MiBbody/16000bytetext/응답상한 보호다. 모두 사전차단을 구분한다.
- `provider_http_error`: `raw` 및 metadata의 http_status를 확인한다. 키/계정값은
  출력하지 않는다. 실패요청도 비용예약을 유지한다. 무조건 재시도하지 않는다.
- Clef HTTP429/code4006: 이번 ITEM_02 응답은 일일무료10,000Neurons 소진을
  명시했다. 과거의 로컬 byte/token 입력 차단과 다른 원인이다. 계정 대시보드에서
  사용량과 갱신을 확인한다. 코드를 바꿔 공급자 한도를 우회하지 않는다.
- `canonical_evidence=false`: 원본응답의 camera/timestamp와 metadata.images를
  비교한다. 근거시각을 가까운입력으로 바꾸지 않는다. 허용오차는1/30+1e-9.
- CV error/timeout: worker Python/weight files/metadata를 확인한다. 평가에서는
  fallback과 upstream error를 기록하며 VLM 정상출력을 전체단계 성공으로 세지 않는다.
- `budget_exhausted` 또는 CLI planned budget rejection: 누적ledger 확인.
  모델실패와 예산중단을 분리하고 미실행항목도분모에 남긴다.
- uncertain/review: 원본자유형사건명과 공통6종사건계약의 매핑 미확정, CV구역/행동규칙
  또는 위험축 미측정이 원인일 수 있다. 검토표시를 임의로끄지 않는다.

## 외부에서 준비할 것

실제MP4↔중립sample ID에 연결된 사건/정상 정답과 근거채점표, camera ROI와
침입/배회 운영정책, 공통사건6종에 들어가지않는 provider자유형사건명의 분류정책,
필요하다면 GPU실행환경 및 공급자청구내역이 필요하다. 자세분석을끄는속도변화는
넘어짐탐지성능이 유지됐다는 증거가 아니다.
