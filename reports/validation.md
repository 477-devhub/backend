# Validation 상태 — 2026-10-07

실제 validation은 **BLOCKED / 미실행**이다. 실제 MP4/JSON, manifest, 중립 input,
asset-map, source/scenario grouping, DATA_CARD가 제공되지 않았다.
A는 HOG 관측 전용이고6-event classifier/risk 측정 미지원, B/C provider/model/access 미확정이다.
F1/recall/FPR/risk-MAE/실영상 지연/비용/공정성은 전부N/A이며 mock 성능을 발표하지 않는다.
실제 validation run0, 실제 test 열기0, 실제 API call0.

## 기술 하네스 결과

실제 `/root/stage07_evaluation`이 app/eval/**, tests/eval/**를 소유했다.
평가 전용 videos[]/annotations 파서, 공통 asset-map/fixed sampling/execute,
canonical hash/clip SHA 검증, phase timings, 실패 분모와 annotation/cost/risk coverage 구현.
명시 mapping 예: 데이터 담당이 승인하면 특정 구역 내 지속 배회→loitering.
parser는 추론 입력·분석 창·split·group를 만들지 않으며 GT로 sampling을 정하지 않는다.

worker 집중52 passed/0skip, 기존 경고1. 합성 MP4/실제 FFmpeg/실제 HOG worker로
동일 prepared input을 A/B/C에 공급하는 기술 경로를 검사했다. B/C는 provider_error로 남았다.
MAIN 전체205 passed/기존경고1, 계약hash match. 실제 CCTV 성능 검증이 아니다.
reviewer 기술 검토 대기.

최종07 reviewer는 frozen asset-map 생략 우회를BLOCK으로 발견했다.
실제 evaluator가 수정하여 평가57/full210/hash PASS, reviewer frozen regression7/hash PASS.
07 기술하네스PASS이며 실제validation BLOCK/N/A는 유지한다.

## 재개 자료

실제 MP4+annotation JSON 경로, 중립 input/asset-map, validation/test manifest와
고정 source/scenario/중복 hash 분할, DATA_CARD 및 체크섬이 필요하다.
event_class mapping, critical/review/risk 주석 또는N/A, fps/framebase/evidence hint 정합성,
Clef/VLM 공식 provider/model/modality/접근 권한도 필요하다. 키 값 공유는 불필요하다.
validation으로만 모델·prompt·threshold를 결정하고 승인 후 freeze/test로 간다.

실자료 납품 후 사용할 명령(아직 미실행):
`python -m app.eval.batch --manifest data/manifest.jsonl --adapter local_cv --split validation --asset-map data/asset-map.json --output outputs/A-validation-001`
B/C는 실제 adapter/access 확인 후 같은 manifest/window/fixed sampling으로 별도 실행한다.
