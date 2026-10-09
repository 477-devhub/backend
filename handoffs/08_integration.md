# 08 MAIN 통합 — 2026-10-07

08 파일 직접 읽음. MAIN이 app/main.py, tests/integration/test_real_cv_backend.py,
TASKS/프론트·데이터 handoffs를 수정했다. 역할 파일을 MAIN이 대신 구현하지 않았다.
default adapter를 asset-map/resolver 해석 후 생성하여 실제 LocalCVAdapter에 주입한다.
actual frame assets를 포함한 PreparedMedia.resolver로 create_app을 구성한 뒤
ingest_model_input(prepared.model_input)을 호출한다. CLI는 이 준비/주입을 자동 수행한다.
prepare_model_input 반환 resolver는 별도 객체이며 앱의 resolver를 암묵적으로 변경하지 않는다.
실시간 clip 수집/프론트 연결은 아직 별도 미완료다.

## 실제 검사

- focused integration/backend49 passed, 전체212 passed, 기존 TestClient 경고1.
  focused 명령은 `pytest -q tests/integration/test_real_cv_backend.py tests/integration/test_model_ingestion.py tests/backend`다.
- 신규 검사2: SYNTHETIC MP4→실제 FFmpeg sampling→실제 HOG CPU child→execute→
  repository→WS/GET→ACK/retry/cache→WS 재연결; asset-map 누락 영상→UNKNOWN/review.
- 첫 실행2fail/47pass는 MAIN의 테스트가 flat Incident에 assessment 중첩을 가정한 오류였다.
  기존 flat API를 그대로 읽고 실제 model output을 capture하도록 테스트를 수정한 후 통과.
- 기존 contract fixtures/synthetic adapter로 timeout/invalid JSON·schema/고위험저확신,
  동시 input/replay/ACK/순위/복원/reconnect 검증. 실제 provider timeout/실CCTV 가림 성능은 미검증.
- `python scripts/check_contracts.py`:match.
- `python -m pip check`:No broken requirements found. CLI --help exit0.
- 실제 subprocess runner: local_cv/clef_direct/general_vlm은 assetmap없는 synthetic fixture에서
  exit2/nonmock/provider_error/uncertain/null/review. mock_local_cv는exit0/mock/uncertain/null/review.
  모두 inputSHA=46f4abc117324924ce55b10a685d16380c65abd3142022526387b745440aa57a.
- TestClient API smoke: /docs,status,cameras,pipeline/stats,suppressed200;
  /stream/CAM_08=503(실제 영상 없음), WS snapshot1.1. exit0.

실제 영상/API 검증·477 연결·인증·영속DB·frontend/dataset 담당 합의는BLOCK이다.
운영 배포 완료로 표시하지 않는다. reviewer 기술 검토 대기.

`/root/stage08_reviewer` 기술PASS: 독립 tests/integration+tests/backend51 passed,
dataset+annotation37 passed, hash match. 각기존경고1. focus49와51은 경로 범위 차이다.
실제 영상/API/사건 모델/운영 readiness는 계속BLOCK이다.
