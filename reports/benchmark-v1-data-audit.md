# Benchmark v1 자료 확인 — 2026-10-07

이번 작업은 모델 선정 전 자료 조사다. 실제 모델 추론, 모델 다운로드, GPU 생성, 유료 API, 학습은 실행하지 않았다. 두 입력 패키지와 기존 구현을 변경하지 않았다.

최종 검토 기록(2026-10-08): reviewer **1단계 PASS**, 독립 focused 22 passed/기존 경고1·계약 match, lock 23/23·영상 hash 6/6 일치. MAIN 최종 전체 **212 passed**/기존 경고1/22.24s·계약 match. 모델 성능 검증이 아니다.

## 확인한 자료와 실제 구성

- `final_candidates_v1/`: README, CHECKSUMS, MP4 6개. 영상 확인·팀 데모용이며 모델 입력 경로로 사용하지 않는다.
- `477_modeling_benchmark_v1/`: README/QUICKSTART/PIPELINE_ASSIGNMENT, docs 3개, prompt/scenarios, public_manifest/PACKAGE_LOCK, schema 2개, Python 코드 5개, submission 안내 및 익명 MP4 6개를 직접 읽었다.
- 벤치마크 regular file 24개, lock 대상 23개. 미리 저장된 JPG/PNG 프레임, 모델 코드/가중치, 정답, 측정 결과는 없다. 프레임은 제공 loader가 실행 시 생성한다.
- lock 검사는 포함된 잠금 파일에 대한 상대 무결성 검사다. 원 배포 ZIP의 외부 SHA256이나 전자서명은 제공받지 않았으며 원출처 인증을 완료했다고 주장하지 않는다.
- 데모 영상 6개의 실제 SHA256은 CHECKSUMS 및 벤치마크 media와 모두 일치한다. 6 unique clips를 재사용하여 7 ITEM/5 scenario를 구성하므로 7개의 독립 사건 표본으로 취급하지 않는다.
- 모든 영상은 1920×1080, 30fps. ASSET_01~04는 35초/1050프레임, ASSET_05는 약30.633초/919프레임, ASSET_06는 약31.833초/955프레임이다. ffprobe 정보는 public_manifest 및 validator와 일치한다.

## 고정 입력

유일한 canonical 시각 입력은 `scripts.load_model_input.iter_model_frames(item_id)`다. 모델에는 RGB 픽셀, generic camera ID, 해당 clip의 상대 시각, 원문 prompt, 해당 task의 response schema만 전달한다. ITEM/asset ID, 경로, descriptive filename, fingerprint는 실행기 내부 정보다.

| ITEM | task | 카메라별 프레임 수 | 실제 선택 프레임 간격 |
|---|---|---|---|
| 01/02/03 | single | CAM_01=64 | 0.533~0.567초 |
| 04 | attention | CAM_01=22, CAM_02=21, CAM_03=21 | CAM_01 1.633~1.667초; 나머지 1.733~1.767초 |
| 05 | single | CAM_01=64 | 0.467~0.500초 |
| 06 | single | CAM_02=64 | 0.500~0.533초 |
| 07 | multi_camera | CAM_01=32, CAM_02=32 | CAM_01 0.967~1.000초; CAM_02 1.000~1.033초 |

카메라별 N개 선택 시 `floor(j*(F-1)/(N-1)+0.5)`를 사용하며, 시각은 선택한 zero-based frame index/30이다. 정확한 카메라 간 동기화는 제공되지 않는다. ITEM_07은 64 total이지 128프레임이 아니다. 원본 MP4 업로드, 추가 프레임, 임의 재샘플링, 정답 근거 프레임 선택은 금지한다. 디코더가 원본을 읽어 canonical을 생성하는 것과 모델이 추가 원본 프레임을 소비하는 것은 구분한다.

64 RGB raw payload는 398,131,200 bytes = 379.6875MiB/ITEM이다. 복사본/디코더/모델 tensor는 별도다. 모델 변환 과정의 resize/letterbox/color/channel/precision/batching과 처리 시간을 추후 runtime_config에 기록해야 한다.

MAIN은 canonical loader로 생성한 448개 프레임을 7개 contact sheet로 확인했다. 넓은 시야, 작은 사람, 차량·담장·나무 가림, 일부 녹색 촬영 배경이 관찰된다. 이는 입력 특성 확인이며 사건별 정답 판정이 아니다. contact sheet는 `reports/benchmark-v1-audit-visuals/ITEM_01.jpg`~`ITEM_07.jpg`에 저장했고 사람 검토용으로만 사용한다. 모델 입력으로 보내지 않는다.

## 출력·평가와 계약 차이

- prediction은 single/attention/multi_camera별 구조이며 event_type은 enum이 아닌 비어 있지 않은 문자열이다. 기존 normal/collapse/conflict/intrusion/loitering/uncertain enum으로 자동 등치하지 않는다.
- attention은 모든 카메라 평가 및 완전한 attention_queue, multi_camera는 same_incident/camera_evidence/cross_camera_summary 등 추가 필드가 필요하다.
- result는 `run_id`, `model_id`, `pipeline`, `runtime_config`, `input_fingerprint`, `prediction`, 측정값, `human_grading` 등을 요구한다. top-level 추가 필드는 금지한다. 세부 단계 시간/메모리/비용 출처는 runtime_config 안에 넣는다.
- P0~P3는 `cv_llm`, P4는 `vlm_only` compatibility envelope를 쓴다. P0에서 LLM을 쓴다는 뜻은 아니며 decision_model=null 및 P0_CV_ONLY를 기록한다.
- public validator는 JSON schema, camera/time 범위, fingerprint를 검사한다. timestamp가 canonical 선택 시각인지까지 증명하지 않으며 모델의 실제 소비 프레임도 증명하지 못한다. 후속 실행기는 입력 추적 로그와 소스 검토가 필요하다.
- `human_grading`은 제출 시 null이어야 한다. 원 validator는 evaluator용 grading object도 허용하므로 제출 정책 검사를 별도로 해야 한다.

| 차이 | 영향과 다음 조치 |
|---|---|
| **risk 4축이 숫자 필수이며 null 불가** | 기존1.1 계약의 미측정=null과 충돌. 현재 HOG/CV처럼 축을 측정하지 못하면 유효한 prediction을 만들 수 없다. 0/0.5 등 임의 대체 금지. benchmark owner의 측정 정의·미측정/실패 제출 정책 결정이 필요하다. 동결 schema는 이번 작업에서 변경하지 않는다. |
| **result.prediction도 null 불가** | 실패를 유효한 성공 submission으로 꾸밀 수 없다. 후속 evaluator는 별도 실패 기록을 남기고 모든 attempt를 분모에 포함해야 한다. owner 확인 전 실패 envelope를 임의로 새로 만들지 않는다. |
| 기존 앱 ModelAssessment와 필드/업무 범위 차이 | 2단계에서 MAIN이 명시적인 bridge/검증 경계를 설계한다. 다중 카메라 출력과 자유 event_type을 손실 없이 처리할 기준이 필요하다. |
| 기존 HOG는 4프레임×640 및 clip 재추출 | 기존 구현을 그대로64 baseline으로 실행하면 프로토콜 위반. 기존 기능은 유지하고 canonical 전용 경로를 별도 구현해야 한다. |
| 데모 README의 `benchmark_v1/...` 경로 | 실제 폴더명은 `477_modeling_benchmark_v1`. 안내 경로가 오래됐다. 실제 작업은 사용자 지정 폴더를 사용하며 원본 문서는 유지했다. |
| 제출 경로의 Clef-Flash/Jev/Clef 명칭 | 과제 배정 이름이며 provider ID가 아니다. 사용자는 Clef를 지정했으므로 P1/P2를 자동 실행하지 않는다. routing을 포함하는 새 실험의 식별/호환 정책은 owner와 확인한다. |

## 정답과 측정 가능 범위

공개 폴더는 의도적으로 private annotations/human references를 제외했다. 별도 authoritative GT, grading rubric, normal/negative clip은 없다. 데모 README의 시나리오 설명이나 project-defined ranking을 정답 파일로 생성하지 않는다.

현재는 파일 무결성·입력 구성·구조 검증을 할 수 있다. 실제 모델 실행 후에는 시간/메모리/usage/스키마 준수·오류를 측정할 수 있다. 사건 precision/recall/F1, 위험축 MAE, ranking correctness, evidence grounding 등 정답 비교 지표는 해당 정답과 정의가 없으면 N/A다. 정상 영상 및 negative labels가 없으므로 오탐률/특이도/AUROC를 주장할 수 없다. 소규모 데모 평가로 한정한다.

## 실제 수행한 검사

| 실행 | 실제 결과 |
|---|---|
| PATH Python3.11.5, package cwd에서 `python -B scripts/validate_package.py` | MAIN 및 explorer 독립 PASS; 7×64=448 canonical RGB frame 검증 |
| 같은 cwd에서 `python -B scripts/inspect_item.py --all` | MAIN 및 explorer PASS; task/camera/frame allocation 확인 |
| MP4 6개의 SHA256 대조 | MAIN 및 explorer 6/6 일치 |
| 기존 `.venv/Scripts/python.exe -B -m pytest -q` | 212 passed, 기존 Starlette deprecation warning1,18.00s |
| `.venv/Scripts/python.exe -B scripts/check_contracts.py` | Frozen contracts match |
| 메모리 내부 synthetic schema/context probe (파일 생성·제출 없음) | null severity는 schema에서 거부,0.123초처럼 noncanonical 시각은 원 context validator가 허용. 추가 입력 근거 검증 필요성을 재현 |
| 실제 모델·GPU·API·학습 | 0회, 사용자 제한에 따라 미실행 |

PATH Python에는 jsonschema/referencing이 있어 설치 없이 validator를 실행했다. 기존 .venv에는 두 라이브러리가 없으며 cv2는 있다. torch/transformers/ultralytics는 설치되지 않았다. nvidia-smi는 발견되지 않아 GPU 유무·VRAM은 미확인이다. 모델 환경은 최종 정보 전달 후 준비한다.

contact sheet 생성은 ITEM마다 1회, 순차 실행했고 decode+색변환+thumbnail+이미지 저장에 2.62~8.96초가 걸렸다. 이는 감사용 생성 시간으로 모델 전처리/추론 latency가 아니다. 모델 최초 실행/재실행은 모두 0회이며 OS 파일 캐시와 동시 감사 부하를 통제하지 않았으므로 성능 비교에 사용하지 않는다.

## 위임과 책임

자료 조사: `/root/benchmark_v1_inventory` (등록 explorer) 읽기 전용, 파일 변경0. MAIN은 결과를 확인하고 validator/무결성/기존 회귀 검사를 직접 재검증했다. 공통 계약·lock·원본 패키지 수정0. 후속 모델 추천 및 reviewer 결과는 `reports/model-selection-v1.md`와 `TASKS.md`에 기록한다.
