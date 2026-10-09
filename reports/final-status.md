# 순차 작업 최종 상태 — 2026-10-07

기존 구현을 유지한 채00~09 파일을 직접 읽고 숫자순으로 진행했다.
optional_parallel.txt는 실행하지 않았다. 실제 서브에이전트를 순차 생성했으며
MAIN 공통 계약·통합 작업과 각 writer 소유 경로를 분리했다. 실제 데이터·권한이 필요한 항목은
추정하거나 mock으로 완료하지 않고BLOCK으로 남겼다.

## 완료한 개발 작업

- 공통 ModelInput/ModelAssessment 계약1.1, 축별nullable risk, legacy1.0 완전 출력 호환,
  불완전 축/오류/미측정 UNKNOWN·review, 정확한 백엔드 가중 위험 공식 및 재동결.
- output/nested Pydantic instance 검증 우회 차단, 실제 input evidence refs 검사.
- 독립 real/mock registry slots, trusted MediaResolver/asset-map, 실제 FFmpeg fixed sampling,
  중립 actual frame refs/PTS/SHA/version/budget/전처리 시간 기록.
- 실제 CPU HOG 사람 관측과 IoU 추적:1active+1waiter, timeout/cancel/child 회수/byte budget.
  uncertain·confidence0·모든축null·review이며 mock은 아니다.
- evaluator-only videos[]/annotations 파서와 명시 event_class mapping. 정답 caption/cot/
  answer/bbox/frame_id를 inference input/window/sampling/feature로 만들지 않는다.
- 단일 CLI/batch asset-map 주입, canonical 동일 input SHA와 manifest↔resolved clip SHA 검증,
  failure/partial risk/critical·review·cost coverage, 클래스 support와 phase timing 지표.
- frozen asset-map 생략/추가/불완전pin 우회 수정(회귀 테스트 선행 재현 및 reviewer 재검증).
- 실제 HOG 호출을 repository→WS→ACK/retry/replay/reconnect까지 연결한 합성 영상 기술 검사.

## 미완료·막힌 항목

| 항목 | 상태 및 필요한 자료 |
|---|---|
| Local CV 이벤트 모델 | 사람 관측만 구현. 차량·pose·zone·6-event 분류·위험축 추정 미지원/미검증. 실제 사건별 MP4/GT와 모델/weight 선택 필요 |
| Clef | 제품·제공사·공식API·model·modality·접근 미확인. UnconfiguredAdapter이며 mock 대체 없음 |
| VLM | 제공사·model·SDK·credential·structured-output/modality 미확인. 실제 API 실행 없음 |
| 데이터/validation | 실제 MP4/JSON/manifest/neutral inputs/asset-map/source·scenario split/DATA_CARD·checksum 미납품 |
| annotation 정의 | event mapping/critical·review·risk 정답 또는N/A, fps/PTS/framebase/evidence hint 정합성 담당 확인 필요 |
| frozen test | validation 선택 전이라 실제 run_config/weight·prompt·threshold·cache·code freeze/실test 미실행 |
| frontend/운영 | UNKNOWN·ACK·WS·camera·Idempotency 팀 합의, 실제 프론트·477 연결, auth/DB/운영 성능 미완료 |

실제 validation/test/model API 실행0회. 실제 CCTV accuracy·FPR·recall·위험축 성능·비용은N/A다.
데모/합성/Mock은 기술 검사에만 사용했고 실제 성능으로 승인하지 않았다.
D router→VLM은 A/B/C 및 candidate recall 근거가 없어 필요 여부를 결정하지 않았다.

## 실제 에이전트와 검토

| 단계 | 실제 생성·재사용한 이름 | 결과 |
|---|---|---|
| 00 | /root/stage00_explorer, /root/stage00_reviewer | 감사PASS, 실제 readiness BLOCK |
| 01 MAIN 계약 | /root/stage01_reviewer | P0 검증 수정/57 tests/hash PASS, 팀 합의 BLOCK |
| 02 backend | /root/stage02_backend_engineer, /root/stage02_reviewer | 실제writer/replay 수정, reviewer 재검토PASS/full86 |
| 03 provider/preprocess | /root/stage03_explorer, /root/stage03_model_ingestion, /root/stage03_reviewer | 전처리 기술PASS/full121, provider/data BLOCK |
| 추가 계약 | /root/stage02_backend_engineer 재사용, /root/stage03_delta_evaluation, /root/stage03_delta_reviewer | 부분축/평가 delta PASS/full166/hash |
| 04 | /root/stage04_local_cv, /root/stage04_reviewer | 관측 기술PASS/focused22/full188, 사건 검증BLOCK |
| 05 | /root/stage05_clef, /root/stage05_reviewer | 명시적BLOCK 처리PASS, actual model 승인 없음 |
| 06 | /root/stage06_vlm, /root/stage06_reviewer | 명시적BLOCK 처리PASS, actual model 승인 없음 |
| 07 | /root/stage07_evaluation, /root/stage07_reviewer | 첫 frozen guard BLOCK→실제owner수정→재검토PASS/eval57/full210 |
| 08 MAIN 통합 | /root/stage08_reviewer | 기술PASS/integration+backend51/annotation·dataset37/full212 |
| 09 MAIN 선행 확인 | /root/stage09_reviewer | 차단판정PASS/독립guard7/hash; 실제test BLOCK·미실행 |

각 등록 역할의 model/reasoning은 .codex/agents/*.toml과 일치했고 developer instructions/
소유권/읽기전용을 전달했다. 플랫폼의 effective sandbox 강제 적용을 독립 조회하는 도구는 없어
그 강제 적용까지 인증하지 않는다. 기존 TOML 사용자 변경은 보존했다.
07의 일시 usage-limit 중단 시 새 diff0을 확인하고 같은 실제 agent 재개에 성공했다.
MAIN이 역할 이름만 바꿔 writer 작업을 대신하지 않았다. 중첩/병렬 agent 실행 없음.

## 최종 실제 테스트

- `.venv/Scripts/python.exe -m pytest -q`: **212 passed**, 기존 Starlette TestClient 경고1,20.47s.
- `python scripts/check_contracts.py`: **Frozen contracts match**.
- `python -m pip check`: **No broken requirements found**.
- `git diff --check`: exit0(기존 Windows LF/CRLF 경고만). 기록한 소스 SHA256 8개 일치.
- frozen guard 집중7 passed; 실제 held-out test 실행이 아니다.
- 실제 CLI --help exit0; asset-map 없는 합성 fixture의 A/B/C는 exit2/nonmock/UNKNOWN/review,
  mock_local_cv는exit0/mock/review. inputSHA 전부46f4abc117324924ce55b10a685d16380c65abd3142022526387b745440aa57a.
- 실제 TestClient API /docs/status/cameras/pipeline/stats/suppressed200, 미디어 없는stream503,
  WS snapshot1.1. 실제 HOG integration은 합성 MP4이므로 CCTV 성능으로 해석하지 않는다.

실행환경: Windows/Python3.11.1/OpenCV4.13.0/NumPy2.4.6,
FFmpegN-122625-g17d89757cd-20260203. CPUthreads1/OpenCLdisabled, GPU/CPU모델 미확인.
현재 working tree는 미커밋이며 base GitHEAD10e8768f77db7a677f7383cd1dacf424fb510716만으로
실제 frozen 코드라고 주장하지 않는다. 실제 freeze_dataset은 실행하지 않았다.

## 재개 위치

먼저 위 실제 자료와 제공사/권한을 받아04 사건 모델 및05/06 실제adapter를 완성한다.
07 실제validation에서 설정을 선택·검토한 다음09 실제config/checksum을 동결하고test를 한 번 실행한다.
프롬프트를 처음부터 다시 수행할 필요는 없다. 상세 결과는 TASKS.md와 handoffs/각 단계,
reports/validation.md 및 reports/final-test.md에 보관했다.

독립 CLI 예시(실제 입력/asset-map 납품 후):
`python -m app.eval.runner --adapter local_cv --input data/inputs/s_000001.json --asset-map data/asset-map.json --output outputs/A-single-001.jsonl`
Clef/VLM은 지원 확인·실제구현 후 adapter 이름만 바꿔 동일 중립 입력으로 실행한다.
현재 그 슬롯은 명시 실패/review이며 실모델로 동작한다고 표시하지 않는다.
