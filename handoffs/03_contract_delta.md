# 03 진행 중 추가 계약 요구 — 2026-10-07

사용자의 MP4 + videos[]/annotations JSON 요구를 기존 구현에 차이만 반영한다. 단계 재시작 없음.
현재 진행 중이던 `/root/stage03_reviewer`에게 내용을 전달했고 기존 전처리 기술 PASS를 받은 후 별도 delta를 진행한다.

## MAIN 계약 변경

- 새 기본 schema_version=1.1. 기존1.0 input/완전 측정 output은 호환 읽기, 축별null output은1.1 필수.
- RiskAxes의 각 severity/imminence/exposure/persistence는 0..1 또는 null; 미지 축은 null default.
- 불완전 risk_axes는 needs_human_review=true 필수. 전체 null도 계속 허용한다.
- 총점은 모든 축을 측정했을 때만 기존 backend 공식으로 계산한다. 부분값 평균/0/50/확신도 보정 금지.
- 공통 schema/docs/tests/lock은 MAIN 담당; 소유권에 따라 backend risk/WS와 evaluator metric 변경은 실제 역할에 순차 위임한다.

## annotation / 독립 실행 경계

사용자 JSON은 앞으로 납품할 형태 예시이며 실제 MP4/JSON 경로가 아직 없다.
annotations 전체는 평가 전용: caption/cot/answer/question/event_class/bbox/frame_id/obj_id/obj_label/evidence_text는 추론에 사용하지 않는다.
영상을 CV/고정 sampling으로 직접 처리하여 evidence/temporal_state를 얻는다. 원본 label-bearing filename은 local asset map에만 있다.
c1/c2 동일 사건은 하나의 scenario_group, 서로 다른 source_video_id. source/scenario/hash split 동결을 유지한다.
평가 frame 번호는 실제 fps/PTS 및 번호 기준 확인 후 정답 검증에만 사용한다.
Local CV/Clef/VLM의 독립 callable slots를 유지하며 실제 지원 modality만 사용한다.
features-only provider는 label-free CV extractor 의존/시간을 기록하고 CV→provider로 구분한다.
현재 실제 provider identity/access와 CV 모델/weights/실제 영상이 없어 완성·실측으로 표시할 수 없다.

## 후속 역할 작업과 게이트

backend_engineer: app/services/risk.py 및 snapshot schema tag/test만 변경, 축 미측정이면 risk=None/UNKNOWN/review.
evaluation_engineer: 부분 위험축 MAE에서 양쪽 측정된 축만 비교하고 축별 pair/coverage를 기록한다.
MAIN 승인 ground-truth 차이: JSON 예시에 없는 critical/needs_human_review는 nullable defaultNone이다.
metrics는 명시 true/false 주석의 coverage를 보고하며 unknown을 false 정답으로 채우지 않는다.
raw-frame 입력의 empty temporal_state는 feature_version=None을 허용하되 관측이 있으면 extractor version이 필요하다.
sampler media_ checksum tokens를 기존 frame_ tokens와 같이 실제 resolver-bound refs로 허용한다.
annotation-specific keys(annotations/caption/cot/answer/question/event_class/obj_bbox 등)는 temporal 관측에서 거부한다.
일반 inferred frame_id/bbox는 합법적 CV 관측이므로 값의 annotation 기원 여부는 trusted provenance/실제 표본 검토로 확인한다.
현재 raw sampler의 frame refs/feature_version과 실제 manifest loader의 입력 제약 차이도 평가 경계에서 검토한다.
MAIN은 공통 regression/문서/freeze/full/hash 검증 및 reviewer delta 판정 후 기존 숫자순 prompts를 계속한다.
actual data/provider BLOCK은 유지하고 annotation 예시를 model input fixture나 mock 정답으로 쓰지 않는다.

## 실제 역할 결과

- `/root/stage02_backend_engineer`: backend32 passed; 부분축 총점None, snapshot1.1.
- `/root/stage03_delta_evaluation` (evaluation_engineer TOML): app/eval/dataset.py,
  metrics.py, tests/eval/test_dataset.py, test_partial_metrics.py만 변경. 집중37 passed,
  기존 TestClient 경고1. 초기 새 테스트 metadata.model 누락6건은 fixture 수정 후 통과.
- risk_axis_pair_count는 완전4축 sample 수, scalar_pair_count는 실제 비교 축 수.
  pair_coverage=complete/n, scalar_coverage=scalar/(4*n), 축별 coverage=count/n.
  critical/review는 명시bool의 annotation coverage 및 positive_count를 보고한다.
- raw empty temporal 허용은 CV feature 존재를 의미하지 않는다. key lint/version 문자열은
  provenance의 증명이 아니며 실제 원본 검증은 계속BLOCK이다.

MAIN 검증: `python -m pytest -q tests/contracts/test_schema_v11.py tests/backend/test_partial_risk.py tests/eval`
53 passed; `python -m pytest -q`166 passed, 기존 경고1; `python scripts/check_contracts.py`match.
실행 python은 `.venv/Scripts/python.exe`. 1.1 공유 계약 lock은 MAIN이 다시 생성했으며 legacy 캡처는 역사로 명시했다.
`/root/stage03_delta_reviewer` 읽기 전용 검토 PASS: 독립 focused53/full166/hash match.
실제 영상/provider/팀 합의는BLOCK이며 독립04 단계 진행을 허용했다.
