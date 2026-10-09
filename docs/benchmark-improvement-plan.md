# Baseline 개선 실험 계획 — 2026-10-08

사용자가 제한 완화, 원인 분석, 속도 개선 및 전체 파이프라인 추가 실험을 승인했다.
기존 baseline 결과를 덮어쓰거나 기준을 소급 수정하지 않는다. benchmark,
final_candidates, data, media는 읽기 전용이다. 정답은 추론에 사용하지 않는다.

## 사전 가설과 구현 범위

1. Clef context는 공식 문서상 65,536 **tokens**이다. 현재 65,536 UTF-8
   **bytes** 검사는 과보수이며 ITEM03/06을 HTTP POST 전에 막았다.
   이 검사만 제거하고 196,608-byte 요청 보호, 응답 크기, 시간 제한, 기존
   호출 예약 $0.03145728 및 누적 $5 보호는 유지한다. provider 오류/토큰 사용량은
   그대로 기록하고 임의 재시도·정답 기반 압축·위험축 채우기를 하지 않는다.
2. VLM은 13건에서 실제 제공된 근거 프레임의 시각을 틀리게 출력했다.
   transport 이미지 라벨에 frame index 및 정확한 시각 복사 안내를 추가한다.
   원본 prompt/schema와 64 RGB 프레임은 유지하고 transport 버전을 기록한다.
   반환 근거를 가까운 프레임으로 사후 이동시키지 않는다. 같은 엄격한
   camera/time 검사를 계속 사용한다.
3. CPU CV의 64프레임 pose 추론 중앙값은 약 17.57초다. 추가 실험으로
   detector+ByteTrack만 사용하는 `pose-off`를 제공한다. posture/넘어짐 정보를
   잃는 실험임을 명시하고 low-posture를 진단이나 정상 근거로 쓰지 않는다.
   기존 `pose-always`와 탐지 해상도960/conf0.10은 보존한다. 측정 없이 GPU,
   더 적은 프레임, detector 해상도 변경을 개선으로 주장하지 않는다.
4. 전체 파이프라인의 CV/Clef 오류 후 VLM fallback, 사람 검토, 세 단계 성공과
   최종 출력 성공을 분리 기록한다. 최종 VLM 출력만 유효한 경우를 전체 단계
   통과로 세지 않는다. 공유 실행기, 안전 리뷰 및 오류 기록을 유지한다.

## 사전 실행·비용 계획

- 기존 누적 59 paid requests / 예약 $3.45235968, 사용량 기반 추정
  $0.286777356. 청구서 실제 비용은 확인할 수 없다. ledger를 초기화하지 않는다.
- 공통64 재평가: 7 ITEM × 1회 × (`vlm_only`, `cv_llm`), 기존 pose-always.
  최대 DeepSeek14 / Clef7 calls. `runs/improved-canonical64`에 저장.
- 별도 속도 실험: ITEM03, ITEM06, ITEM02 × 1회 `cv_llm`, pose-off.
  최대 DeepSeek3 / Clef3 calls. `runs/improved-pose-off`에 저장.
  누적 모델 호출은 서로 순차 실행하며 API 응답 재사용으로 실제 실행을 꾸미지 않는다.
- 추가 최대 예약 = 17×$0.0685824 + 10×$0.03145728 = **$1.48047360**.
  총 최대 예약 **$4.93283328**. 출력 토큰 상한/공식 단가로 보수적 예약을 유지하며
  캐시 미사용·최대입력/출력 가정의 추가 모델요금 계산은
  17×$0.0342912 + 10×$0.01572864 = **$0.74023680**이며 예약은 이 금액의2배다.
  실제 사용량 기반 추가비용은 결과 전 정확히 알 수 없다. 청구서 비용과 구분한다.
  API 실패·timeout에도 예약은 반환하지 않는다. 예상 초과 시 즉시 중단한다.
- 추가 비유료 실험: Clef 큰 입력의 serializer 검사, 잘못된 근거 reject,
  API 실패 fallback/검토 및 CV profile 재현성·소비 프레임 검사.
  테스트 double은 안전 동작 검사용이며 실제 모델 성능으로 집계하지 않는다.

## 결과 전 동결한 평가 기준

- 동일한 원본7 ITEM, 64프레임/카메라/원본prompt/schema/hash 유지.
- JSON structure 및 실제 canonical evidence: 100% 목표. 오차허용은 기존
  ±1/30 + 1e-9 유지. 실패를 사후 보정하거나 분모에서 빼지 않는다.
- 세 단계 모두 호출·성공 + 출력 검증 100% 목표. 실패와 fallback 별도 표시.
- latency: 전체120초 이내 목표. pose-off는 대응 ITEM의 pose-always 대비
  CV 시간 중앙값20% 이상 감소를 탐색 목표로 한다. 1회 비교는 통계적 성능 증명이 아니다.
- API 사용량·비용·RSS·전처리/모델/전체시간, 최초 실행과 반복횟수를 기록.
- GT/normal/semantic rubric이 없으면 사건 정확도, recall, 오경보 및 의미상 근거
  정확성을 N/A로 남긴다. 추적 proxy 변화는 탐지/추적 정확도로 보고하지 않는다.
- full pytest / contracts / 독립 reviewer PASS는 코드·보고 무결성 gate다.
  목표 성능 실패여도 실제 수치와 미완료 항목을 보고하고 통과로 바꾸지 않는다.

## 순차 담당과 소유

- explorer: 읽기 전용 실패 원인/데이터/병목 조사.
- model_engineer: 한 번에 하나씩 Clef, DeepSeek, YOLO adapter 및 tests/models.
- evaluation_engineer: app/eval 및 tests/eval, 전체 단계·변환/profile 측정.
- MAIN: registry/CLI/공통계약/문서/lock/통합/실제 실행 및 결과 검증.
- reviewer: 읽기 전용 계약·누출·예산·검증과 결과 무결성 PASS/BLOCK.

추가로 필요한 외부 작업은 GT/정상영상·camera ROI/구역 정책·사건 분류표·
실제 계정 청구 확인·GPU 환경 제공이며, 현재 값으로 추정하여 채우지 않는다.

공식 근거: [Clef context/가격](https://developers.cloudflare.com/workers-ai/models/clef/),
[DeepSeek 이미지 제한](https://api-docs.deepseek.com/guides/vision/),
[DeepSeek 가격](https://api-docs.deepseek.com/quick_start/pricing/).
DeepSeek peak cache-miss$0.30/M input, $1.20/M output 가정, off-peak/cache절감
미적용. Clef$0.24/M input, context65536tokens; 실제truncation은미확인이다.

## 추가 실패에 대한 별도 후속 계획 — 결과 확인 전 동결

기존 v2 실험의 ITEM04 VLM 단독은 HTTP200/finish_reason=stop이지만,
원본 content의 JSON 위치4145에서 `"timestamp_sec=7.0,`을 반환했다.
입력 시각 라벨의 `=` 문법을 출력 JSON에 섞은 정황이다. 원본 실패를 보존하고
진행 중인 v2 실험과 pose-off3항목 조건은 끝까지 바꾸지 않는다.

이 실패에만 별도 `deepseek_json_labels_v3`를 구현하여 ITEM04 VLM 단독1회를
추가 실행한다. 이미지 라벨을 유효한 JSON 객체로 표현하고 원본64프레임,
JPEG80, prompt/schema 원문, 시각/근거 검사, 응답 무보정은 유지한다.
v3만 출력 budget4096tokens로 제한하며 token truncation은 실패로 기록한다.
기존 v2의8192tokens 및 결과/분모/평가기준은 유지한다.

- v3 최대 모델요금 계산 = (81536×$0.30 +4096×$1.20)/1M = $0.029376.
- v3 2배 안전예약 = **$0.058752**. 새 누적 최대예약 **$4.99158528 < $5**.
  기존 예약을 반환하거나 ledger를 초기화하지 않는다.
- 기준은 동일: JSON 구조/원본schema/canonical evidence100% 목표,
  전체120초 이내, 실제 호출 비용/원본응답 보존. 예산초과는 호출 전중단.
- 결과는 `runs/improved-json-labels-item04`에 별도 저장. 이1건은 원래7항목
  cohort에 합산하지 않는다. targeted 성공으로 v3전체성능을 주장하지 않는다.
- 별도model_engineer 구현·집중검사, MAIN full/contract gate 및 검토 후 실행.
  새 유료 호출은 이1회 외에 추가하지 않는다.
