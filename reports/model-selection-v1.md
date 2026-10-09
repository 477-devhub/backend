# 477 모델 선정과 baseline 평가 준비 — 2026-10-07

**1단계 완료, reviewer PASS** (최종 검증 기록: 2026-10-08). baseline 구현과 모델 실행은 사용자의 최종 모델·실행 환경 전달을 기다린다. 모델 다운로드·유료 GPU 생성·유료 추론·학습은 시작하지 않았다. 기존 구현과 두 동결 입력 패키지는 유지했다. 자료 조사 및 실제 검사 상세는 [자료 감사](benchmark-v1-data-audit.md)를 참고한다. 추천·공식 자료·가격 조회 기준일은 2026-10-07이다.

## 우선 추천과 대안

| 역할 | 우선 추천 | 대안 | 선택 이유와 실제 확인 범위 |
|---|---|---|---|
| Local CV | **`yolo26s-pose.pt`** | **`yolo11s-pose.pt`** | 사람 박스와17관절점을 같은 모델에서 추출해 자세 변화·지속시간 관측에 활용. 공식 체크포인트/문서 확인; 477 추론·정확도·속도는 미측정 |
| VLM | **`Qwen/Qwen3-VL-4B-Instruct`** | **`Qwen/Qwen3-VL-8B-Instruct`** | 데모 시작은 비교적 작은 Instruct 모델, 대안은 동일 입력 변환을 유지하는 큰 모델. 이미지·복수 이미지·영상 기능 확인; 64프레임 실행은 미측정 |
| 중간 결정/라우팅 | 사용자 지정 **`@cf/cloudflare/clef`**, body selector **`clef`** | 자동 대체 없음 | 정확한 제품/모델 ID/공식 API 확인. `clef-flash`는 별개 모델이며 사용자 선택을 바꾸지 않음. 계정 접근·실제 추론은 미검증 |

추천은 실제 성능 승자를 선정한 결과가 아니다. 입력 특성·공식 기능·실행 난이도에 따른 첫 실험 후보 선정이다. 모델/precision/threshold/pixel budget을 사전 확정하고 평가 결과를 본 뒤 바꾼 조건은 별도 실험으로 남긴다.

## Local CV 구성과 한계

공식 COCO640 pose 표에서 YOLO26s-pose는 AP63.0, CPU ONNX85.3ms, T4 TensorRT10 2.7ms, 약10.4M parameters다. YOLO11s-pose는 AP58.9, CPU90.5ms, T4 TensorRT10 2.6ms, 약9.9M이다. 이 값은 외부 공개 측정값으로 477 성능이 아니다. YOLO26이 모든 GPU에서 더 빠르다고 결론 내릴 수 없다. [YOLO26 공식 pose 표](https://raw.githubusercontent.com/ultralytics/ultralytics/main/docs/macros/yolo-pose-perf.md), [YOLO11 공식 문서](https://docs.ultralytics.com/models/yolo11/), [YOLO26 원논문](https://arxiv.org/abs/2606.03748)

두 pose 체크포인트는 사람 한 클래스와 관절점을 제공한다. 차량 탐지, 사건 분류, 위험축, 출입 권한 판별을 제공하지 않는다. 최신 YOLO26 pose 기능 및 동일 도구 계열이라는 점을 우선 추천 근거로 삼았으며, YOLO11을 낮은 전환 비용의 대안으로 둔다. 실제 비교에서는 같은 변환·tracking·rules를 유지한다. [공식 pose 설명](https://docs.ultralytics.com/tasks/pose/)

후속 baseline의 구성 제안:

1. canonical RGB64프레임을 모두 받아 고정 letterbox/색상 변환 후 pose 모델에 입력한다. 초기 `imgsz=960`, batch1~4 제안이며 최종 환경에서 사전 확정한다. PIL RGB/tensor 또는 명시적 RGB→BGR 변환을 사용하고 채널 해석을 검사한다.
2. 카메라별 time-aware IoU/Kalman 추적을 분리한다. 실제 timestamp 차이 `dt`, 소실 허용시간(초), 추적 품질을 기록한다. 카메라 간 ID 공유·동일 인물·정확 동기화를 가정하지 않는다.
3. 관측된 자세 변화, 이동 거리, 멈춤, 시간 누적, 사람 간 근접 등을 일반 규칙으로 집계한다. threshold는 별도 개발 자료/공개 기본값/사전 선언에 근거한다.
4. 근거가 없는 사건·위험축·다중 카메라 관계는 불확실/지원 불가로 처리하고 사람이 검토하게 한다. 부족한 축을0이나0.5로 채우지 않는다.

ByteTrack은 보조 비교 후보다. 원 구현의 프레임 카운터와30fps 기반 buffer를1초 안팎의 희소 입력에 그대로 쓰면 추적 의미가 달라진다. 실제 dt/소실시간 변환을 명시하거나 시간 기반 추적을 사용한다. 더 촘촘한 CV 영상 입력은 별도 실험이며 공식64프레임 결과와 섞지 않는다. [ByteTrack 원논문](https://arxiv.org/abs/2110.06864), [원 구현](https://github.com/ifzhang/ByteTrack/blob/main/yolox/tracker/byte_tracker.py)

낮은 자세 전환·지속은 의학적 실신 진단이 아니다. 근접·관절 변화만으로 싸움이나 의도를 확정할 수 없다. 담장 부근의 이동은 법적 무단침입 근거가 아니며, 영상 픽셀만으로 경계를 확인하지 못하면 경계 통과도 지원 불가다. 정답 bbox/ROI/근거 프레임·시나리오별 정답을 규칙에 넣지 않는다. 30~35초 자료로 장시간 배회를 일반화할 수 없다. pose 규칙만으로 풍부한 자연문 근거·attention·multi_camera 출력을 완성했다고 주장하지 않는다.

Windows CPU/PyTorch/ONNX는 기술적으로 시작할 수 있지만 실제 의존성 호환은 미검증이다. 데모용 CUDA FP16, imgsz960/batch1~4는 GPU8GB 이상,16GB 여유를 계획한다. **실제 필요 VRAM은 미측정**이다. CPU는 FP32부터 확인하고, INT8 calibration에 동결 ITEM을 쓰지 않는다. 양자화는 별도 조건이며 체크포인트·export 호환·정확도 검사가 필요하다. [Ultralytics export](https://docs.ultralytics.com/modes/export/)

YOLO 계열은 AGPL-3.0/Enterprise 조건을 확인해야 한다. 배포 방식에 따른 선택을 최종 모델 정보와 함께 확정한다. ByteTrack 원 저장소는 MIT다. 이번 조사에서 라이선스 계약을 체결하거나 배포하지 않았다. [Ultralytics license](https://www.ultralytics.com/license), [ByteTrack license](https://github.com/ifzhang/ByteTrack/blob/main/LICENSE)

## VLM의64프레임 처리와 실행 환경

Qwen3-VL은 복수 이미지·영상·시간 이해 기능을 제공한다. 본 비교는 긴 Thinking 출력 대신 Instruct 모델을 선택하고, 4B를 데모 첫 후보,8B를 품질 대안으로 둔다. 더 큰 모델의 정확도 우위나 더 작은 모델의 지연 우위는 이번 데이터에서 검증하지 않았다. [4B 공식 카드](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), [8B 공식 카드](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct), [Qwen3-VL 원논문](https://arxiv.org/abs/2511.21631)

Qwen3.5-4B도 검토했다. 복수 이미지·영상과 비추론 모드가 있지만 이번64프레임에서 우위를 확인하지 않았다. 공통 processor와 모델 크기 비교를 유지하기 쉬운 Qwen3-VL4B/8B를 우선한다. [Qwen3.5 공식 카드](https://huggingface.co/Qwen/Qwen3.5-4B)

- 기본은 **64장 복수 이미지 입력**이다. loader 순서·카메라·정확 상대 시각을 각 이미지에 대응시킨다. prompt 원문/task별 schema를 유지하며 모델별 chat template 변환만 기록한다.
- MP4 업로드, 자동 FPS 재샘플링, 프레임 누락, contact sheet 대체는 금지한다. 영상 tensor 경로는 실제 타임스탬프/추가 선택 여부를 검증한 경우에만 별도 사용한다.
- 초기 변환 후보는 `max_pixels=512*32*32`다. 약512 visual tokens/frame의 상한을 계획하며 전체64장을 유지한다. 실제 변환 크기와 토큰은 processor 출력에서 측정한다. 원거리 인물 손실을 확인하되 정답을 본 뒤 ITEM별 크기를 바꾸지 않는다.
- 초기 동시 요청은1개다. vLLM 사용 시 복수 이미지 허용량64를 설정한다. JSON structured output은 원래 schema의 문법 지원과 validator 통과를 실제 확인해야 한다. Transformer의 prompt만으로 JSON 준수가 보장되는 것은 아니다.
- 분할이 필요하면 같은64장만 나눠 사용하고 camera/time 대응, 고정 집계 방식, 모든 batch·집계의 추가 시간/입출력 토큰/오류를 기록한다. 주 비교는 가능한 한 단일64장 요청을 우선한다.

근거: [Transformers Qwen3-VL](https://huggingface.co/docs/transformers/en/model_doc/qwen3_vl), [공식 구현](https://github.com/QwenLM/Qwen3-VL), [vLLM multimodal](https://docs.vllm.ai/en/stable/features/multimodal_inputs/), [vLLM JSON output](https://docs.vllm.ai/en/stable/features/structured_outputs/)

| 항목 | 4B 우선 | 8B 대안 | 수치 성격 |
|---|---|---|---|
| 전체 파라미터 | 약4.438B | 약8.767B | 공식 저장소 metadata |
| BF16 가중치만 | 약8.27GiB | 약16.33GiB | params×2bytes 계산; 실제 VRAM 아님 |
| FP8 이상적 가중치 하한 | 약4.13GiB | 약8.17GiB | scale/비양자화 계층 제외 |
| 4bit 이상적 가중치 하한 | 약2.07GiB | 약4.08GiB | vision 계층·scale·cache 별도 |
| 초기 GPU 계획 | RTX4090 24GB | A40/L40 48GB | 실행 적합성 미검증 |
| 초기 precision | BF16 | BF16 | 양자화는 별도 비교 조건 |

MAIN이 공식 config/API metadata를 독립 확인했다. 조사 당시4B revision은 `ebb281ec70b05090aa6165b016eac8ec08e71b17`,8B는 `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`이었다. 이는 조회 시점 기록이며 실제 baseline 다운로드/동결을 수행한 것이 아니다. 최종 선택 후 사용 revision을 다시 확인해 고정한다. [4B config](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct/blob/main/config.json), [8B config](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/blob/main/config.json)

두 config는 patch16/merge2, text36layers/8KVheads/head_dim128이다. 원해상도64장은 약130,560 visual tokens로 계산되고 BF16 KV만 약17.93GiB다. pixel budget에서 최대32,768 visual tokens라면 KV 약4.5GiB이며 텍스트/출력 토큰도 추가된다. 모델 가중치·vision activations·workspace를 더해야 하므로 **4B라도24GB 안전 실행을 아직 보증할 수 없다**. 실제 peak memory/OOM을 측정하고 부족하면 사전 선언한 낮은 pixel budget 또는48GB 조건으로 구분한다.

공식 FP8 변형은 존재하지만 이번 실행은0회다. 양자화는 가중치만 줄이며64장 전체의 vision/KV 메모리를 없애지 않는다. 공식 variant 또는4bit 설정·비양자화 모듈·backend를 기록하고 동일64프레임으로 따로 비교한다. [4B FP8](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-FP8), [8B FP8](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-FP8)

vLLM은 Linux 환경을 권장한다. 최초1회 실행에는 PyTorch/Transformers+SDPA 경로도 검토하고, guided JSON/서빙이 필요하면 Linux vLLM으로 검증한다. card의 오래된 설치 주석을 그대로 pin하지 않는다. 조사에서 최신 Transformers5.19.0/vLLM0.31.0 release를 확인했지만 최종 GPU에서 검증할 버전 조합은 미확정이다. [vLLM GPU 설치](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/), [Transformers release](https://github.com/huggingface/transformers/releases/tag/v5.19.0), [vLLM release](https://github.com/vllm-project/vllm/releases/tag/v0.31.0)

실제 응답 시간은 미측정이며 몇 초라고 보장하지 않는다. 데모 목표 응답시간을 최종 정보에서 받고,64장·JSON 출력 길이·전처리·첫 실행과 warm 실행을 포함해 충족 여부를 확인한다.

## Clef 확인 사항

- 정확한 hosted ID는 `@cf/cloudflare/clef`, REST endpoint는 Cloudflare 계정의 `/ai/run/@cf/cloudflare/clef`, body `model`은 `clef`다. 사용자가 제공한 정보와 공식 문서가 일치한다.
- state는 문자열 또는 JSON 구조이고 질문은 `noul`/`choice`/`score`다. 출력은 질문별 확률/선택/점수다. 자유문 생성 모델이 아니므로 observations/temporal_summary/reason을 자연스럽게 생성하는 VLM과 동일시하지 않는다.
- hosted 문서의 context는65,536 tokens, 질문 수는1~64다. 긴 state는 잘릴 수 있어 실제 token/누락을 확인해야 한다.
- hosted schema의 embedded images는 최대4장, PNG/JPEG/WebP, 이미지당4MiB/16MP, 합계 decoded8MiB, request13MiB 제한이며 remote URL은 불가다. 일반 모델 카드가 영상 기능을 언급하더라도 이 REST schema에서64프레임/MP4 입력 지원을 추정하지 않는다.

근거: [Cloudflare Clef](https://developers.cloudflare.com/workers-ai/models/clef/), [공식 Clef 모델 카드](https://huggingface.co/Cloudflare/clef)

루팅용 기본 제안은 canonical64프레임에서 실제 CV가 만든 box/pose/track/시간 특징을 state로 전달하는 것이다. 이 경로는 **CV+Clef** 조합이므로 Clef가 직접64장을 봤다고 쓰지 않는다. 이미지로 독립 Clef를 비교하려면 같은64장을 최대4장씩 최소16회 분할하고 고정 집계·추가 비용·시간·시간 문맥 손실을 기록해야 한다. 최대4장만 골라64장 동등 입력이라고 주장하지 않는다. 구체적인 이미지 embedded 표현은 공식 serializer schema/실제 요청 검증 후 확정하며 추정 코드를 작성하지 않았다.

`noul`의 yes probability나 choice confidence는 사건 confidence이지 위험축 측정값과 같지 않다. score는 level index의 확률 가중 기대값이며 축으로 변환하려면 level 정의/legend와 정규화 근거를 명시해야 한다. 여러 위험축·라우팅 질문을 설계하더라도 측정하지 못한 축은 채우지 않는다. 형식 변환 과정에서 공통 prompt의 근거·불확실성 의미를 유지해야 한다.

MAIN은 `.env`의 CLEF_API_TOKEN/CLEF_ACCOUNT/CLEF_MODEL 존재·nonempty 및 selector=clef만 확인했다. 값은 출력하지 않았다. 새 자격 증명을 요구하거나 교체하지 않는다. 계정 권한·모델 접근·quota·실제 응답·이미지 직렬화·provider 버전 안정성은 API를 호출하지 않아 미검증이다. 사용자 지정 변수는 후속 adapter에서 token/account/selector로 직접 매핑할 수 있으며 표준 예시 변수명으로 강제 변경할 필요가 없다. [Cloudflare REST 시작 안내](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)

## 예상 비용과 실제 비용

아래는2026-10-07 확인한 공개 가격으로 계산한 예시다. 예약 시점 견적·실제 청구·477 실행시간이 아니다. GPU 비용은 전체 할당 시간(설치·다운로드·idle 포함)×시급+storage 등이고, 모델 실행만의 비용과 총 프로젝트 비용을 구분한다. [Runpod 공식 가격](https://www.runpod.io/pricing)

| 환경 | 공개 표시 시급 | 3시간 할당 가정 | ITEM당60초 실행 가정의 compute 몫 |
|---|---:|---:|---:|
| RTX4090 24GB | $0.74 | $2.22 | 약$0.0123 |
| A40 48GB | $0.49 | $1.47 | 약$0.0082 |
| L40 48GB | $0.82 | $2.46 | 약$0.0137 |

60초는 계산용 가정이며 예상 지연 측정값이 아니다. storage/세금/전송/부가요금은 위 계산에서 제외했다. 42attempts(7ITEM×6회)가 각60초인 경우4090의 실행 compute만 약$0.518이며 실제 할당·준비·idle 비용은 별도다. 계정/지역/가용 자원별 가격을 실행 전에 다시 확인한다.

Clef 공개 가격은 input1M tokens당$0.24다. 가령 실제 usage가10,000 input tokens이면$0.0024이며, 같은 usage의16요청이면$0.0384다. 이 역시 usage를 가정한 예시로 실제64프레임 비용이 아니다. 토큰을 측정하지 않았으므로 benchmark result의 token/cost는 작성하지 않았다. flash의$0.09/M은 사용자 Clef 설정의 가격으로 사용하지 않는다. [Cloudflare 가격](https://developers.cloudflare.com/workers-ai/platform/pricing/)

본 작업에서 model/API inference 요청·GPU resource 생성은0회다. 관련 실제 사용/청구 비용은 측정하지 않았으며 기존 계정 전체 비용이0이라고 주장하지 않는다.

## 후속 baseline 및 평가 계획

최종 모델·환경 전달 후 아래 순서로 진행한다. 이번 단계에서는 baseline 코드를 작성하지 않았다.

1. MAIN이 frozen64/prompt/schema 유지와 기존1.1 bridge 경계를 확정한다. 미측정 risk/null prediction 불가 및 실패 제출 정책은 benchmark owner 확인이 필요하다. 필요하더라도 owner 승인 없는 패키지 변경·숫자 대체는 하지 않는다.
2. Local CV, Clef, VLM 구현은 각기 별도 등록 model_engineer에게 순차 위임한다. 설치·실행·출력 저장·오류 확인 가이드는 검증한 환경과 실제 명령으로 작성한다. provider serializer는 adapters에만 두며 모델 호출은 공통 execution 경계를 사용한다.
3. 독립 실행 결과와 **CV→Clef→선택적 VLM** 전체 파이프라인 결과를 분리한다. Clef threshold/라우팅 정책은 사전 선언한다. uncertainty/error는 사람 검토 경로로 보내며 임의 normal 처리하지 않는다.
4. 라우팅에서 VLM에 보내지 않은 사건도 전체 attempt/정답 사건 분모에 포함한다. router recall/누락률, conditional VLM 결과, 최종 pipeline recall/latency/cost를 각각 기록한다. 독립 VLM64장 평가와 라우팅된 부분 입력을 받은 VLM 평가를 동일 실험으로 취급하지 않는다.
5. 기본 반복 계획은 ITEM별 첫 요청1회+warm5회, concurrency1이다. ITEM 첫 요청과 프로세스/모델 cold start는 다르므로 `item_first_run`, `model_cold_start`, 모델 로드 시간, decoder/feature/provider cache 상태를 각각 기록한다. canonical decode부터 result serialization까지의 전체 시간을 측정한다. decode/변환/CV/aggregation/Clef upload·wait/VLM/parse/serialization 및 retries의 시간 정의를 기록한다. 단계가 겹치면 시간을 중복 합산하지 않는다.
6. host RSS/peak GPU allocated·reserved/NVML의 측정 범위, 모델/checkpoint/precision/seed/batch/pixel budget, input fingerprint, frame 소비 로그, 성공·오류·schema rate를 저장한다. 실제 API usage·청구·가격 기반 추정 비용을 구분한다.
7. valid JSON/원schema+context validator+추가 canonical evidence 검증 통과율은 전체 attempts를 분모로 계산한다. schema error/timeout/OOM/provider failure/라우팅 누락을 제거하지 않는다. 삭제·잘라내기·허구 근거로 JSON을 성공 처리하지 않는다.
8. 정답이 제공되면 사건 지표/위험축/ranking/근거·과도한 단정/다중뷰 평가를 수행한다. event_type 자유문 매핑, human grading rubric, 위험축의 정답 또는N/A 정책을 먼저 확인한다. AB는 best single(A,B)과 비교하고32+32 vs64의 자원 차이를 함께 적는다.

7ITEM은6영상 재사용을 포함한 소규모 데모다. 반복 실행은 지연 안정성 표본을 늘릴 뿐 독립 사건 수를 늘리지 않는다. 적은 warm 반복의 p95는 탐색적 지표이며 신뢰할 만한 운영 tail latency로 일반화하지 않는다. normal/negative GT가 없어 오탐률·특이도/AUROC는 N/A다. private GT가 없으면 사건 정답 비교도 N/A다.

## 다음 단계에 필요한 정보

- 최종 CV/VLM exact checkpoint와 사용할 precision, 모델 다운로드가 가능한 실행 환경(OS/CPU/GPU·VRAM/CUDA/driver, 디스크/메모리).
- 데모 목표 응답시간, GPU 예산/공급자/허용 운영 시간, Clef API 실행 허용 시점·요청/비용 범위. token을 채팅으로 다시 보내지 않는다.
- GT/원 annotation 또는 evaluator 접근, event mapping/human rubric/위험축 정답·N/A, normal/negative 데이터 여부. 현재 두 패키지에는 없다.
- benchmark owner의 nullable risk/실패 attempt 제출 정책, 기존 앱 bridge 및 routing 실험 식별 규칙. 정확 카메라 동기화·동일 인물 GT가 없으면 관계는 불확실로 평가한다.
- YOLO 라이선스/배포 조건. 최종 환경이 정해지면 검증한 의존성 조합을 pin한다.

## 실행·검토 기록

| 담당 | 실제 에이전트 | 작업/실제 검사 |
|---|---|---|
| 자료 조사 | `/root/benchmark_v1_inventory` | 원본 자료 직접 읽기, package validator448frames PASS, metadata inspection PASS,6영상 hash 일치; 변경0 |
| CV 후보 조사 | `/root/benchmark_v1_cv_selection` | 공식 체크포인트·문서·원논문 조사; 모델 테스트0/변경0 |
| VLM 후보 조사 | `/root/benchmark_v1_vlm_selection` | 공식 카드·논문·config/기능·메모리 계산; 모델 테스트0/변경0 |
| Clef 기능 조사 | `/root/benchmark_v1_clef_capabilities` | 공식 hosted 계약/형식/적합성 조사; 인증·추론0/변경0 |
| 공통 자료 확인·문서·통합 | MAIN |6hash 재검증,448canonical 검사PASS,212tests PASS(경고1),기존 계약match; download/API/GPU0 |
| 평가·계약 검토 | `/root/benchmark_v1_selection_reviewer` | **1단계 PASS**. 독립 focused 22 passed/경고1/5.57s, 계약 match, lock 23/23·데모 영상 6/6 일치. 변경0/모델 테스트0 |

MAIN 최종 단계 검사: `.venv/Scripts/python.exe -B -m pytest -q` → **212 passed**, 기존 경고1,22.24s; `scripts/check_contracts.py` → **Frozen contracts match**. 실제 측정 `run_ITEM*.json` 생성·제출0. 이 검사는 기존 하네스 회귀 결과이며 신규 모델의 정확도·지연·메모리·접근 검증이 아니다.

모든 하위 에이전트는 등록 TOML의 model/effort와 지시문을 적용했고 순차 실행한다. 파일 권한의 OS 강제 sandbox 인증은 별도로 하지 않았다. optional_parallel는 실행하지 않았다. 정답을 추론에 넣거나 mock을 실제 모델로 완료 처리하지 않았다.
