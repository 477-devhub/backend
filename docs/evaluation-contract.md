# 평가 계약

현재 구현: 단일 입력 runner, manifest 검사, JSONL batch runner, 기본 metrics.
실제 adapter·raw-video feature extraction·asset map 자동 주입은 후속 작업입니다.
동일 입력 JSON을 모든 adapter에 deep copy하고 input_sha256를 기록합니다.

| 지표 | 현재 정의 |
|---|---|
| macro F1 | 해당 split의 정답에 존재하는 클래스 평균; 클래스 목록 출력 |
| critical_event_recall | critical 정답 중 event_type 일치 비율; 실패는 miss |
| critical_escalation_recall | critical 정답 중 incident/review로 올린 비율 |
| false_alert_rate_on_normal | normal 정답 중 incident/review 비율 |
| human_review_recall | review 정답 중 review로 보낸 비율 |
| error_rate | timeout/schema/provider_error / 전체 샘플 |
| latency_ms_mean | 실행 래퍼의 벽시계; 전처리 미포함이면 provider 평가로 표시 |
| cost_usd_mean_measured | 측정 가능한 샘플만 평균, coverage 필수 |
| risk_axis_mae_measured | 정답과 예측 둘 다 있는 축 MAE, pair_count 함께 표시 |

분모 0인 지표는 null. 실패 샘플을 전체 결과에서 삭제하지 않습니다.
모든 실패를 review로 보내면 escalation recall은 높지만 event recall은 낮아질 수 있습니다. 둘을 함께 봅니다.
mock은 실제 batch 평가에서 금지합니다. real adapter 미구현은 모든 실패로 기록하고 exit2가 됩니다.
이런 결과를 모델 성능으로 발표하지 않습니다.

추가 과제: p50/p95/p99 latency, 클래스별 recall/support, risk coverage, grouped rank agreement,
후보 생성부터의 end-to-end critical recall, false alarms per camera-hour, 반복 run/CI/seed,
provider retry/cancellation 비용, CV feature/preprocess 시간·장비·sample budgets 기록.
특히 event clip 단위 정상 FPR와 장시간 카메라당 오경보 수는 다른 지표입니다.

B가 features-only면 B/C 모두 같은 관측 feature로 비교한 실험과 raw-frame 비교 실험을 따로 씁니다.
프레임 수/해상도/기간/feature version, provider model/prompt version, token/usage/cost, 코드 commit을 저장하세요.
누락된 risk 정답·비용·rank 시나리오는 N/A로 표시합니다.

## 1.1 부분 주석 / annotation 입력 경계

단일 runner와 batch는 `--asset-map`(선택 `--asset-root`)을 받으며 동일한
app/eval/pipeline.py의 fixed sampling→resolver 주입→execute 경로를 사용한다.
prepared input의 canonical JSON(sort_keys/compact/UTF-8) SHA256을 공통 기록한다.
batch는 resolved clip SHA가 manifest media SHA와 같은지도 확인한다.
전처리 실패는 preprocessing_error/review/null/refs[]로 남기며 모델 latency/cost는null다.

timings.preprocessing_ms는 공통 sampling/hash 확인, execution_wall_ms는 execute 전체,
adapter_cv_preprocessing_ms/worker_ms는 execution 내부 구간이다(총합에 중복 추가하지 않음).
end_to_end_ms는 evaluate_input 전체이며 manifest/입력 파일 읽기·결과 쓰기는 제외한다.
provider_ms는 분리 측정할 수 없어null이다. p50/p95/p99는 nearest-rank이며 count/coverage 필수다.
클래스별 support/TP/FP/FN/recall/F1, normal denominator와 error phase/count도 함께 기록한다.

MP4 companion parser `parse_annotations(document, event_mapping=...)`는 평가 전용이다.
명시 event_class mapping을 받아 GT/video metadata를 반환하며 ModelInput/window/split/group를
생성하지 않는다. caption/cot/answer/bbox/frame hints는 평가 전용 복사본에만 남는다.
실제 fps/PTS/frame 번호 기준과 동일 사건 multiview grouping은 데이터 담당 확인이 필요하다.

test에 실제 asset-map을 사용하려면 frozen config에 asset_map_sha256과
preprocessing_version=ffmpeg-fixed-grid-v1을 추가해야 한다. 이 guard는 code/weights를
동결했다는 뜻이 아니므로 실제 validation 완료 전 test 실행을 승인하지 않는다.

risk_axes 각 축이 null이면 해당 축 MAE 비교에서 제외하고 축별 measured pair count/coverage를 함께 기록한다.
전체 scalar 비교 개수와 완전한 sample pair 개수를 구분하여 일부 축을 4로 나눠 숨기지 않는다.
MP4 동봉 JSON에 없는 critical/needs_human_review 주석은 null이며 false를 기본 정답으로 만들지 않는다.
critical/review recall은 명시 주석의 분모와 annotation coverage를 함께 표시한다.
event_class mapping은 평가자 전용이며 annotation caption/cot/answer/bbox/frame_id는 inference input에 복사하지 않는다.
raw-frame 입력은 빈 temporal_state에서 feature_version이 없을 수 있다. 실제 관측이 있으면 trusted extractor version이 필요하다.
fixed sampler의 중립 frame/media tokens는 resolver의 실제 bytes에 연결되며 annotation refs를 대신 사용하지 않는다.

validation: python -m app.eval.batch --manifest data/manifest.jsonl --adapter local_cv --split validation --output outputs/A-validation-001
test: 같은 명령에 --split test --allow-test --lock data/dataset.lock.json --run-config data/run_config.json
동일 output 경로를 재사용하지 않습니다. frozen run config는 실제 모델 버전/전처리/prompt/코드 기록으로 바꿉니다.
현재 hash guard는 manifest와 config bytes 변경을 막습니다. 코드/weight/cache 전체를 강제 검증하지 않으므로
MAIN이 commit·weight/cache checksum을 별도 보관하고 재현성을 확인해야 합니다.
