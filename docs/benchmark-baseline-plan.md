# 실행 전 고정 계획 — 2026-10-08

사용자 승인 모델: yolo26s.pt / ByteTrack / 필요 자세 yolo26s-pose.pt, Clef @cf/cloudflare/clef, DeepSeek deepseek-flash(api.deepseek.com). env 키는 VLM_API_KEY 및 기존 Clef 설정을 재사용하며 출력·로그·Git에 넣지 않는다. benchmark/data/final_candidates/media는 읽기만 한다. 구현·weights·결과는 밖에 저장한다.

## 공통 입력과 비교

- 원 loader의 동일64 RGB1920×1080, camera/정확상대시각, 원문prompt/task schema. source/frame/camera allocation 변경0. VLM은 픽셀만 받고 CV track/pose/zone 정보는 받지 않는다.
- 전체pipeline에서 CV-derived64프레임 state를 Clef에 전달한다. 추가원본프레임/crop/GT/외부zone annotation은 사용하지 않는다. 이는 P3 CV feature mode이며 이미지 VLM과 정보형태 차이를 기록한다. 추적정보를 VLM에 추가하는 실험은 실행하지 않는다.
- 7ITEM 각3반복: VLM단독 최대21요청, CV→Clef→VLM 최대21VLM/21Clef요청. 총최대42VLM+21Clef, 자동retry0. 각반복은 별도실제실행이며 모델cold/providercache상태를 기록한다. 최초요청과warm을 혼동하지 않는다.
- ByteTrack 카메라별분리, sparse frame-step 및 실제timestamp 누적, 소실buffer 약5초 환산을 기록. detector imgsz960/conf0.10/person와vehicle COCOclasses 관측, pose는wholecanonicalframes일반설정. GT로규칙튜닝금지.
- 구역이 미제공이므로 침입구역 규칙 지원불가.15초 dwell은 화면내추적후보이지 배회정답이 아니다. 짧은가림/ID변경/자세저품질/구역없음은불확실. Clef routing사전정책: incident probability>=0.35이면VLM, 미확인/오류/불확실이면안전fallback VLM+human review. 명확한no-action confidence>=0.90일때만route skip 가능하며모든skip을전체분모기록. route정책은실행결과본뒤변경하지않는다.

## 가격·상한 ($5 합계)

공식가격조회2026-10-08: DeepSeek最高cache-miss input$0.30/M, output$1.20/M. 이미지<=1024tokens/장.64장=65,536. text/schema<=16,000UTF8bytes(보수token상한16,000), output<=8192tokens, thinking disabled. VLM1요청상한 (81536×.30+8192×1.20)/1M=$0.0342912,42회=$1.4402304. Clef context65,536×.24/M=$0.01572864,21회=$0.33030144. 전체약$1.77053184. 공개가격/최대usage가정이며실측청구가아니다. API별2배예약안전계수로약$3.5411를예약한다. $5를넘는추가호출은시작하지않고예약은실패/timeout에도회수하지않는다. SDKretry0/stream0/이미지추가0/outputcap고정. 가격상한초과·usage불명확은추가호출정지또는예약전액보수집계한다.

공식근거: [DeepSeek가격](https://api-docs.deepseek.com/quick_start/pricing/), [이미지제한](https://api-docs.deepseek.com/guides/vision/), [thinking토글](https://api-docs.deepseek.com/guides/thinking_mode/), [Cloudflare가격](https://developers.cloudflare.com/workers-ai/platform/pricing/).

Usage×공식단가예상, DeepSeek balance delta(조회가능시), invoice실제비용을분리한다. 청구에접근못하면실제비용null이다. Cloudflarefreeallocation을모델요청비용0이라고가정하지않는다. API상한은localcompute/전력비가아니며GPU대여는실행하지않는다.

## 사전 제안 합격 기준 (실행 후 변경 금지)

- 공통입력준수100%, 원본protected파일변경0, credential노출0, 예약예산<=5달러.
- 성공예측의원schema/context/canonical근거일치100%; 전체attempt schema준수목표100%. 실패/skip/timeout/invalid은분모에남기며가짜성공prediction을만들지않는다.
- 데모전체응답시간제안목표<=120초/ITEM. 모델로드/전처리/CV/Clef/VLM/전체를분리측정. CPU에서못맞추면실패를그대로기록한다. 반복수가작은p95는탐색적이다.
- 사건정확도·누락·오경보·근거정확성·위험축MAE: GT/정상negative/reference/rubric없으므로N/A, 합격판정불가. 데모문서시나리오명/순위를GT로쓰지않는다.
- risk축미측정은null. frozenprediction은nullrisk불가이므로실패진단sidecar에기록하고성공submission을생성하지않는다. 모델이실제로산출한4축만검증해성공submission으로저장한다. 원frozen스키마수정금지.
- directVLM과routedpipeline비교에서앞단skip/실패를VLM실패로돌리지않는다. GT없는경우모델간불일치는정답오류확정이아니다. 원인이확인되지않으면불확실로보고한다.

## 소유권·순서

MAIN: 공유types/budget/execution/canonical입력bridge/설정/의존성/CLI/docs/lock/계약검사/원본hash보호/실제API집행.
model_engineer순차: CVadapter+worker/tests → Clefadapter/tests → DeepSeekadapter/tests.
evaluation_engineer: app/eval 및tests/eval의측정/validator/비교/집계.
reviewer읽기전용: 비용/키/입력/실패누락/GT/결과검토. no nested delegation. 매단계 focused→MAIN regression/hash→검토후 다음단계.
# Additional execution boundary clarified before paid tests

Compatibility preflight, before suite evaluation: JPEG quality 90 exceeds the
provider's 48MiB body limit on three ITEMs. Use fixed JPEG quality 80 for all
suite VLM calls, keeping all 64 original-resolution frames and unchanged
prompt/schema. All seven locally serialized bodies pass the size bound.
The earlier quality-90 provider probe remains separately labeled; acceptance
criteria and evidence tolerance are unchanged. See reports/benchmark-provider-preflight.md.

One separate real-media provider-access probe is allowed before the suite:
one VLM request and one Clef request on ITEM_01. These are excluded from suite
performance metrics and included in the same persistent $5 ledger. The total
maximum is therefore 43 VLM and 22 Clef requests: peak-price estimate
$1.82055168, conservative reservations $3.64110336. Criteria remain unchanged.

Canonical evidence timestamps must match a supplied frame of the same camera
within 1/30 second (one source-frame period); original predictions are never
repaired. The stricter check supplements the package validator, which only
checks that observation timestamps are within clip duration. Provider event
labels outside the existing common enumeration are preserved verbatim and map
to uncertain/human review in the backend sidecar. Backend risk calculation
continues to use the existing weighted formula independently of confidence.

