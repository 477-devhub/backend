# 03 provider/data 및 독립 전처리 — 2026-10-07

## 실제 순차 담당

`/root/stage03_explorer` (읽기 전용) → MAIN 공유 경계 동결 → `/root/stage03_model_ingestion` (model_engineer).
model_engineer 허용/실제 수정은 `app/models/adapters/ingestion.py`, `tests/models/test_ingestion.py` 두 파일뿐이다.
MAIN은 media/config/main/env/docs/lock 및 tests/contracts/integration을 순차 수정했다.
역할 모델/effort는 등록된 TOML 설정을 사용하며 runtime sandbox 독립 조회의 한계는 기존 기록과 같다.
중첩 위임/병렬 agents/optional_parallel/worker install/git 쓰기 없음.

## Provider / 실제 환경 판정

| 항목 | 확인 결과 |
|---|---|
| Clef 제품·제공사 | 미식별, BLOCKED |
| Clef 공식 문서/API/model/권한/modality/structured output/SDK/제한/비용 | 확인 근거 없음, BLOCKED; 임의 제품/endpoint 선택·호출 없음 |
| Local CV 후보/이벤트 지원 | 실제 media·모델 선택·weights 없음, 미검증 |
| VLM provider/model/access | 미제공, BLOCKED |
| .venv 신경망/CV 패키지 | cv2/torch/torchvision/transformers/numpy/PIL/av/onnxruntime/ultralytics/supervision 없음 |
| FFmpeg | MAIN actual version/filter 조회 성공; N-122625-g17d89757cd-20260203 |
| GPU | nvidia-smi 미발견, GPU 유무 확정하지 않음 |
| 실제 데이터 납품 | media/manifest/inputs/asset-map/DATA_CARD/checksums 없음 |

정확한 Clef 이름·공식 링크·접근 정보와 VLM/데이터/팀 확인을 이미 한 번에 요청했으며 응답을 추정하지 않는다.
실제 validation 자료가 없어 manifest 검사는 수행하지 않았다.

## 독립 전처리 결과

설계는 `handoffs/03_preprocessing_design.md`에 보관한다.
MAIN MediaResolver는 UTF-8 asset-map duplicate/type/path 검사, bounded bytes 및 별도 memory frame cache를 제공한다.
Settings ASSET_MAP/ASSET_ROOT 또는 create_app(media_resolver=...)로 MediaIngestion 생성자에 주입한다.
미설정 시 prepare_model_input은 명시적으로 거부하고 기본 real model은 여전히 UnconfiguredAdapter이다.

`MediaIngestion(resolver, frame_count=4,width=640,height=360,max_clip_bytes=64MiB,max_frame_bytes=2MiB,
timeout_sec=15,ffmpeg='ffmpeg')`의 `await prepare(mi)`는 PreparedMedia를 반환한다.
PreparedMedia: model_input, resolver, clip_sha256, frame_sha256, extractor_version,
ffmpeg_version, profile, preprocessing_ms. profile은 actual count/PTS/quantization/sparse coverage/budgets/threads를 기록한다.
목표 grid는 window와 고정 count만 사용한다. 입력 evidence/annotation/temporal observations는 sampling에 사용하지 않는다.
raw temporal_state는 비운다. 실제 decoded PTS를 nearest-ms로 기록하고 frame bytes와 중립 refs를 연결한다.
source path/파일명/정답을 subprocess/provider input에 담지 않고 pipe protocol로 제한한다.
async bounded pipes, finite total deadline, timeout/cancel kill+await를 구현했다.
원본 clip bytes를 resolver로 읽을 수 있고 새 frame bytes는 memory resolver에 연결한다.
feature classifier/extractor/디스크 feature cache/live ingestion은 아직 없다.

## 실제 테스트 결과

| 실행자 / 명령 | 결과 |
|---|---|
| model_engineer `.venv/Scripts/python.exe -m pytest tests/models/test_ingestion.py -q` | 최종25 passed, 1 warning, 1.99s; skip 없음 |
| MAIN `.venv/Scripts/python.exe -m pytest tests/models/test_ingestion.py tests/contracts/test_media_boundary.py tests/integration/test_media_preparation.py -q` | 35 passed, 1 warning, 2.67s |
| MAIN `.venv/Scripts/python.exe -m pytest -q` | 121 passed, 1 warning, 3.87s |
| MAIN freeze_contracts / check_contracts | 동결 성공 / Frozen contracts match. |

worker 첫 테스트에서 frozen 모델 필드에 직접 대입한 test fixture 오류7개가 있었으며 model_copy로 고친 뒤 위 결과를 확인했다.
actual FFmpeg synthetic MKV: 목표 [0,425,850,1275]ms, 실제 frame [0,667,1000,1333]ms; 실제 JPEG640x360/hash/ref 재현성을 확인했다.
실제 sleeping subprocess timeout/cancel 회수와 event-loop 접근을 검사했다.
MAIN integration은 synthetic video→실제 decoded frame refs→명시 mock_local_cv→UNKNOWN/review 저장을 검사했다.
이를 실제 CCTV/event/model accuracy나 provider 비용 검증으로 표시하지 않는다.

## 완료 경계 / reviewer

독립 전처리 기술 검사 PASS, `/root/stage03_reviewer` 기술 **PASS**. 실제 provider/data 부분 BLOCKED.
reviewer 실제 focused35 passed/0 skipped/1 warning/2.32s 및 hashPASS. 변경 파일 없음.
새 사용자 MP4+annotations 및 각위험축null 요구는 별도 `03_contract_delta.md`로 차이만 반영한다.
실제 validation media/input/provenance를 받은 뒤부터 manifest/decoder coverage/label-free extraction을 확인할 수 있다.
현재 전체 단계의 실제 모델 준비 완료 또는 팀 합의를 선언하지 않는다.
