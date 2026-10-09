# 03 독립 전처리 설계 — 2026-10-07

## 확인된 환경 / 선택 근거

실제 explorer `/root/stage03_explorer`: Clef 제품/제공사/공식 문서/API/model/access/modality 미식별 **BLOCKED**.
로컬 .venv Python3.11.1에 cv2/torch/torchvision/transformers/numpy/PIL/av/onnxruntime/ultralytics/supervision 없음.
ffmpeg 실행 파일은 존재하며 MAIN이 version 및 select/scale/showinfo filter를 직접 확인했다.
version: N-122625-g17d89757cd-20260203. nvidia-smi 미발견이며 GPU 유무를 확정하지 않는다.
실제 영상과 이벤트 모델 지원 범위가 없어 Local CV/VLM 후보를 검증/선정하지 않았다.

공식 근거: [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html),
[FFmpeg pipe](https://ffmpeg.org/ffmpeg-protocols.html#pipe).
FFmpeg는 decoder/전처리 도구이며 학습된 이벤트 모델이 아니다.

## MAIN 공유 경계

MAIN: `app/models/media.py`, `app/config.py`, `app/main.py`, 공통 tests/contracts/integration, docs/lock.
MediaResolver.from_asset_map(asset_map, root=None), read(ref, max_bytes=None), with_assets(token_to_bytes)를 제공한다.
중복/형식 오류·root 이탈·원본 byte budget 초과를 거부하고 원본 path를 provider로 보내지 않는다.
Settings ASSET_MAP/ASSET_ROOT는 선택 설정이며 미설정 시 resolver를 만들거나 실미디어를 꾸미지 않는다.
worker 완료 후 MAIN이 create_app의 optional resolver 및 MediaIngestion 생성자 주입을 연결한다.
실제 모델 슬롯은 계속 UnconfiguredAdapter이며 ingestion을 모델 성능이라고 표시하지 않는다.

## model_engineer 지정 파일 / 완료 기준

writer는 `app/models/adapters/ingestion.py`와 해당 `tests/models/test_ingestion.py`만 수정한다.
provider/model SDK나 event classifier는 만들지 않고 의존성 설치·registry/shared 수정은 하지 않는다.

독립 구현 방향은 subprocess FFmpeg이다. cv2 신규 설치 및 thread 내 blocking decoder와 비교하여,
기존 executable을 사용하고 timeout/cancellation 때 process를 종료/회수할 수 있다는 이유로 선택한다.

- 생성자에 trusted MediaResolver를 받는다. clip_ref가 없거나 mapping/media가 잘못되면 명시 실패한다.
- 프레임 목표 시각은 window와 사전 고정 frame_count만 사용한 균등 grid로 결정한다.
  기존 evidence/annotation/event/정답 시각/temporal observations로 sampling하지 않는다.
- 원본 bytes를 stdin에 보내고 로컬 source filename을 decoder/provider 요청에 담지 않는다.
  pipe protocol을 제한하며 network/file playlist를 따라가지 않는다.
- 실제 decoded PTS를 showinfo 등으로 확인하여 입력 window에 속하는 실제 frame/timestamp ID를 만든다.
  target timestamp를 실제 decoded timestamp라고 지어내지 않는다. 범위 내 frame이 없으면 실패한다.
- raw-frame 모드에서는 supplied temporal_state를 feature로 재사용하지 않고 빈 관측으로 재구성한다.
- 고정 resize/frame_count/clip bytes/frame bytes/process timeout을 profile에 기록한다.
  기본 예산 제안: 4 frames, 640x360, clip64MiB/frame2MiB, subprocess 유한 timeout.
  count<=16 등 상한 및 전체 timeout도 명시하고 wall preprocessing 시간을 측정한다.
- async subprocess로 event loop를 차단하지 않고 timeout/cancel 시 child를 종료/await한다.
- PreparedMedia에는 재구성한 ModelInput, 실제 frame bytes에 연결된 새 resolver,
  clip/frame checksums, extractor/FFmpeg version, sampling profile 및 preprocessing_ms를 둔다.
  이 provenance는 evaluator sidecar이며 provider에 ground truth/path를 직렬화하지 않는다.
- label-free frame cache는 memory asset 경계로 제공한다. feature extractor/디스크 cache는 아직 미구현이다.

완료 기준은 합성으로 명시된 작은 encoded video bytes로 grid/실제 PTS/resize/ref 재현성,
원본 clip bytes 읽기, invalid media/budget/window/path 오류, timeout/cancel 및 event loop 접근 테스트 PASS다.
실제 validation media/manifest 검사 및 공정성/이벤트 성능은 외부 자료가 없어 완료 처리하지 않는다.

## 외부 자료 대기

정확한 Clef 이름/공식 링크/접근 정보, VLM provider/model, 실제 영상/manifest/inputs/asset-map/DATA_CARD/checksums,
frontend/data team 확인을 이미 한 번에 요청했다. 응답 없는 값을 추정하지 않는다.
전처리 독립 기술 작업은 진행하지만 실제 provider/data 부분은 BLOCKED다.
