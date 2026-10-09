# Frozen test 상태 — 2026-10-07

09 파일 직접 읽음. 실제 frozen test는 **BLOCKED / 미실행**이다.
실제 validation에서 모델/prompt/threshold를 선택하지 못했으며 실제 manifest,
run_config, MP4/JSON, asset-map, 고정 split 및 DATA_CARD가 없다.
data/media/outputs에는 .gitkeep만 있고 기존 reports의 mock/unconfigured 수치는 과거 synthetic 기록이다.

| 후보 | 구현 및 검증 상태 | 실제 test 성능/latency/cost |
|---|---|---|
| A local_cv | 실제 HOG 사람 검출/기하 추적 관측. 6-event 분류·pose·zone·risk 미측정, uncertain/review | N/A — 실제 CCTV/정답 미제공 |
| B clef_direct | provider/API/model/access/modality 미식별. UnconfiguredAdapter/nonmock | N/A — BLOCKED |
| C general_vlm | provider/model/SDK/credential/modality/structured-output 미확인 | N/A — BLOCKED |
| D router→VLM | A/B/C와 candidate recall 근거 부족으로 필요 여부 미결정 | N/A — 제안/구현 미실행 |

## 동결 상태

- 공통 계약1.1: docs/contracts.lock.json checksum 검사PASS.
- 실제 dataset/run-config lock: 만들지 않음. scripts/freeze_dataset.py 실행0회.
- 실제 `--split test --allow-test --lock --run-config` batch: 실행0회.
- 기존 fixtures/run_config.example.json의 REPLACE_BEFORE_FREEZE/UNVERIFIED는 예시다.
  실제 선택 근거 없이 이를 지우거나 실제 config/lock으로 위장하지 않는다.
- 현재 base Git HEAD는10e8768f77db7a677f7383cd1dacf424fb510716이나 작업tree에 미커밋 변경이 있다.
  이것을 실제 실행 code commit 동결 완료로 주장하지 않는다.
- 모델/weights/prompt/threshold/sampler/feature cache/code commit의 실제 선택·checksum이 미완료다.
  pytest 합성 fixture의 frozen guard 실행은 실제 held-out test 열기가 아니다.

## 실제 기술 검사

MAIN `.venv/Scripts/python.exe -m pytest -q tests/eval/test_media_pipeline.py -k frozen`:
7 passed/7 deselected/기존경고1.
MAIN `python -m pytest -q`:212 passed/기존 TestClient 경고1/20.47s.
MAIN `python scripts/check_contracts.py`:Frozen contracts match.
실제 CCTV·provider 비용·분류 accuracy·camera-hour FPR·candidate recall은 N/A다.
실제 test를 보고 tuning하지 않았으며 test 실행 자체가 없었다.

## 재개에 필요한 자료

1. 실제 MP4와 annotation JSON 위치, 중립 input/asset-map, 검증된 media hashes.
2. 동일 사건 c1/c2 scenario grouping 및 source/hash 고정 split, DATA_CARD.
3. event_class mapping, critical/review/risk 주석 또는N/A, fps/PTS/frame 번호 기준 확인.
4. 실제 사건 지원 CV 모델 및 weight/version, Clef/VLM 정확한 provider/model/공식API/
   modality/structured-output/권한/credential 위치. 비밀키 값을 전달하지 않아도 된다.
5. 실제 validation 재현 결과로 선택한 prompt/threshold/sampling/budgets와 비용·품질 coverage.
6. 재현 가능한 code commit/weights/cache checksum을 고정한 실제 run_config 승인.

이 선행 자료와 validation PASS 후 MAIN이 freeze_dataset을 실행하고
출력 경로를 재사용하지 않는 실제 test를 한 번 수행한다. 이후 tuning은 새 프로토콜로 진행한다.

최종 `/root/stage09_reviewer` 차단 판정PASS: 실제 미실행/N/A와 파일 상태 일치,
독립 frozen guard7/hash match. 실제 모델 분류·성능 평가는BLOCK이며 승인하지 않았다.
