# 477: YOLO → Clef → VLM 벤치마크

실제 실행 요약은 [RESULTS.md](RESULTS.md), 최종 보기용 12행 표는
[results_readable.csv](results/full_pipeline_v2/results_readable.csv)입니다.
YOLO/Clef/VLM 실제 실행은 각각 12/12이며 사건 정확도는 검수 정답 부족으로 평가 불가입니다.

이 폴더 전체를 팀원에게 전달하면 원본 저장소 없이 실행할 수 있습니다. 이 README만
따라 설치·모델 설정·검사·실행하면 됩니다. **README 파일 하나만 전달하면 영상과 코드가 없어 실행할 수 없습니다.**
실제 영상·가중치·고정 프레임·실행 코드와 함께 폴더 전체를 전달하세요. API 키와 `.env`는 전달하지 마세요.

하나의 문제에 총 64장, 문제당 CSV 한 행입니다. YOLO 검출, Clef 라우팅, VLM 사건 정답을
각각 구분합니다. 형식 검사를 통과한 것과 사건을 맞힌 것은 별개의 결과입니다.

현재 정답 상태: 제공된 두 자료 폴더에 실제 객체 정답 박스와 검수된 사건·라우팅 정답이 없습니다.
`ground_truth/sources.json`에 참고 사건 설명과 **검수 대기**를 기록했습니다.
박스·호출 정답은 임의로 만들지 않았습니다. 사용자는 2026-10-08 추가 지시로 이번
DeepSeek/Clef 실행의 이전 $5 제한을 해제했습니다. `paid_authorization.json`에 승인 범위를 기록했습니다.
최종 실행 결과는 `RESULTS.md`와 `results/full_pipeline_v2/results.csv`를 확인하세요.
`full_pipeline_v1`은 연결 코드 오류로 중단한 최초 실행의 보존 자료입니다.

## 1. 설치

Python 3.11 권장, ffmpeg/ffprobe를 PATH에 설치하세요. Windows PowerShell 예시:

```powershell
cd C:\path\to\new_477_piprline
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests
```

CUDA를 쓰려면 PyTorch 공식 설치 안내에 맞는 GPU 버전을 설치하고 `config/models.json`의
`yolo.device`를 `"0"`으로 바꾸세요. GPU 실측 결과는 CPU 결과와 별도 실행 폴더에 저장하세요.
배포에는 `models/yolo26s.pt`가 있습니다. YOLO 라이선스와 모델·영상 공유 권한은 팀에서 확인하세요.

## 2. 먼저 검사하고 무료 로컬 실행

```powershell
.\.venv\Scripts\python.exe -B run.py --check-only --output results/check_01
.\.venv\Scripts\python.exe -B run.py --output results/my_local_01
.\.venv\Scripts\python.exe -B summarize.py --output results/my_local_01
```

`--check-only`는 고정 입력 해시, 12문제×64장, 원본 프레임/시각 매핑, 정답 형식,
정답/오답/미실행 평가 자기검증을 검사합니다. 실제 모델을 호출하지 않습니다.
기본 실행은 실제 YOLO만 실행하고 API는 `blocked`로 기록합니다. 유료 실행 플래그가 없으면
Clef/VLM에 네트워크 요청을 보내지 않습니다. 이미 결과가 있는 폴더는 덮어쓰지 않습니다.

## 3. 자기 모델 넣는 방법

동일 YOLO 계열은 `config/models.json`의 모델·weights·device·imgsz·conf를 수정합니다.
새 가중치는 `models/my_model.pt`처럼 다른 파일로 추가하고 weights 경로를 바꾸세요.
잠긴 `models/yolo26s.pt`를 덮어쓰면 고정 입력 검사가 실패합니다.
COCO 클래스 ID가 다른 모델은 변환 플러그인을 작성하세요. 검출 대상은 person/bicycle/car/
motorcycle/bus/truck이며 클래스 범위가 달라지면 새 실험 버전으로 분리해야 합니다.

Clef/VLM 모델명과 환경변수는 다음처럼 설정합니다. 실제 값은 로컬 `.env`에만 두세요.

```dotenv
VLM_MODEL=deepseek-flash
VLM_API_KEY=YOUR_LOCAL_SECRET
CLEF_MODEL=clef
CLEF_ACCOUNT=YOUR_ACCOUNT_ID
CLEF_API_TOKEN=YOUR_LOCAL_SECRET
```

`config/models.json`의 모델명/엔드포인트/가격/출력 한도도 실제 제공자에 맞춰 확인하세요.
VLM은 64이미지를 지원해야 합니다. 다른 제공자가 이 입력을 지원하지 않으면 unsupported로
표시하고 임의로 프레임 수를 줄이지 마세요. 영상 입력·crop·추가 프레임은 별도 실험입니다.

완전히 다른 모델은 `pipeline477/adapters/my_model.py`를 만들어 `plugin`을
`"pipeline477.adapters.my_model:Adapter"`로 지정하면 됩니다. `Adapter(config)`가
`async run(model_input, context) -> stage_record`를 구현합니다. 자세한 입출력은 `DESIGN.md`와
기본 어댑터 파일을 참고하세요. SDK·HTTP·이미지 변환은 어댑터 안에만 두고 모든 호출은
`pipeline477/execution.py` 경계를 사용하세요. CPU 작업은 `asyncio.to_thread`나 자식 프로세스로 실행합니다.

stage_record의 필수 값:

```json
{"status":"ok","executed":true,"output":{},"metadata":{},"errors":[],
 "cost_usd":{"value":null,"basis":"unknown","invoice_usd":null}}
```

YOLO `output.frames`는 frame_id/source_id와 detections의 class_name/픽셀 xyxy bbox/
confidence/track_id를 반환합니다. 추적 ID는 영상별로 독립입니다.
Clef `output.sources`는 source_id별 invoke_vlm bool, proposed_route, route_confidence,
incident_probability, cv_uncertain 등을 반환합니다.
VLM `output.assessments`는 `schemas/vlm_output.schema.json`을 따릅니다.
라벨 정답/정답 박스/정답 근거는 어댑터나 입력에 넣지 마세요.

실제 요청은 `<stage>.request.json`, 원본 응답은 `<stage>.response.json`에 저장하세요.
인증 헤더/키는 저장하지 않습니다. VLM 요청 파일에는 전송한 이미지 base64가 있을 수 있으나
CSV에는 넣지 않습니다. 변환 후 결과는 `<stage>.normalized.json`로 별도 보존합니다.
모델 교체 결과의 비교는 같은 `benchmark.lock.json`과 `ground_truth` 해시일 때만 직접 비교합니다.
환경변수와 config에 서로 다른 모델명이 있으면 실제 런타임 메타데이터를 먼저 확인하세요.

## 4. 실제 API 실행과 예산

**이 배포는 이전 누적 $5 원장을 보존하며 이번 실제 호출에 대한 추가 승인을 별도로 기록합니다.**
준비 시 예약액 $4.99158528, 남은 금액 $0.00841472입니다. 이는 결제 영수증이 아니라
과금 불명확 요청까지 보수적으로 유지하는 예약 원장입니다. 사용자가 이번 12문제의 DeepSeek/Clef
실행에 대해 비용 제한을 풀었으므로 `paid_authorization.json`의 승인 범위에서는 기존 $5로 차단하지 않습니다.
이전 예약을 삭제·취소하지 않습니다. 팀원의 계정·다른 프로젝트 과금 승인을 뜻하지 않으며
팀원은 자기 계정의 예산 소유자 승인을 확인하세요. 승인 파일이 없으면 기존 한도로 차단됩니다.

한 문제 Clef 1요청+VLM 1요청을 모두 실행한다고 가정한 예약 상한은
$0.03145728+$0.058752=$0.09020928, 12문제는 **$1.08251136**입니다.
이는 실제 예상 청구액이 아니라 이전 제공자 토큰 상한을 이용한 보수적 실행 예약입니다.
실제 입력 토큰·가격·지원 한도가 달라지면 다시 계산해야 합니다.
2026-10-08 UTC 공식 문서 확인: [Clef](https://developers.cloudflare.com/workers-ai/models/clef/)는
입력 백만 토큰당 $0.24, [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing)의
deepseek-flash는 비혼잡 시간에 입력 미캐시 $0.15/캐시 $0.003/출력 $0.60입니다.
혼잡 시간은 각각 $0.30/$0.006/$1.20이며 평일 UTC 01–04시와 06–10시입니다.
이번 v2 실행 시간은 이 구간 밖이므로 `full_pipeline.json`에 비혼잡 단가를 기록했습니다.
재실행 전 시각·최신 단가를 다시 확인하세요. API 사용량×단가는 청구 영수증과 구분합니다.
이번 작업에서 DeepSeek 가격 페이지 재조회는 실패했습니다. 가격 변경을 임의로 추정하지 않았습니다.

예산이 충분히 승인되어 있고 해당 원장에 반영된 경우의 명령:

```powershell
.\.venv\Scripts\python.exe -B run.py --env-file .env --allow-paid --output results/my_paid_01
```

추가 승인 파일이 있어도 `--allow-paid`를 생략하면 API는 호출하지 않습니다.
실제로 실행된 요청 수와 비용은 RESULTS.md 및 새 원장의 사용량 기록을 확인하세요.
Cloudflare 무료 Neurons 일일 제한은 이 로컬 달러 원장과 별개입니다.
단일 프로세스·순차 실행만 지원하며 같은 예산 원장을 동시에 여러 프로세스가 수정하면 안 됩니다.
이번 실제 실행은 `--config config/full_pipeline.json`을 지정합니다. 이 프로필은 Clef 실행
오류·미완료 시 VLM으로 대체 진행하고 상위 실패를 보존합니다. 상위 YOLO 실패로 Clef를
실행하지 못한 경우도 포함합니다. 대체 실행을 전체 파이프라인 성공으로 처리하지 않습니다.
기본 `config/models.json`은 상위 실패 시 중단하는 대조 설정입니다.
실제 Clef 판단이 정상적으로 호출을 생략하면 두 설정 모두 VLM을 skipped로 기록합니다.

`python -B audit.py --output results/my_paid_01 --env-file .env`로 고정 파일 해시,
CSV 행 수, 실제 요청의 64이미지와 JPEG 해시, 원본 응답과 변환 출력의 일치,
알려진 비공개 정답 필드와 환경변수 키의 유출 여부를 검사할 수 있습니다.
키 값은 출력하지 않으며 결과는 `audit.json`에 저장합니다. 사건 정답률 검사는 아닙니다.

보기용 CSV는 `python -B compact_csv.py --output results/my_paid_01`로 만듭니다.
`results_readable.csv`도 문제당 한 행이며 수치·사건 출력은 같습니다. 긴 YOLO 박스 목록과
64이미지 상세 해시만 실제 normalized 파일 링크로 대체합니다. 원본 CSV/JSON은 유지합니다.
Python CSV를 직접 읽는 경우 `csv.field_size_limit(32 * 1024 * 1024)`를 먼저 설정하세요.

## 5. 문제 목록

| 문제 | 원본 ID | 장수 | 구성 의미 |
|---|---|---|---|
| P001~P006 | 각각 SRC01~SRC06 | 64 | 단일 원본 대조군 6문제 |
| P007 | SRC01,SRC02 | 32,32 | 서로 다른 사건 묶음 |
| P008 | SRC05,SRC06 | 32,32 | README상 같은 사건의 다른 view, 정밀 동기화 미제공 |
| P009 | SRC01,SRC03,SRC05 | 22,21,21 | 서로 다른 사건 묶음 |
| P010 | SRC01~SRC04 | 16씩 | 서로 다른 사건 묶음 |
| P011 | SRC01~SRC05 | 13,13,13,13,12 | 서로 다른 사건 묶음 |
| P012 | SRC01~SRC06 | 11,11,11,11,10,10 | 독립 묶음에 같은 사건 view 쌍도 포함 |

총 12문제, 768 프레임 슬롯, 고유 원본 6개입니다. 원본이 문제 사이에 반복되므로 독립 표본
768개가 아닙니다. 4~6영상 구성은 새 입력 부하·영상별 판별 실험이며 기존 공식 attention ranking
과제가 아닙니다. 새 문제의 성능을 이전 ITEM_01~07과 직접 합산하지 않습니다.

원본별로 0 기반 프레임 번호를 균등 선택하고 내부 순서를 유지합니다.
`data/frames/Pxxx/manifest.json`의 frame_number/timestamp_sec/sha256으로 추적하세요.
frame_id는 `SRC01-F000000` 형식입니다. 모델별 이미지 resize/letterbox/JPEG 변환은
메타데이터와 변환 시간에 기록합니다. canonical 프레임 자체는 교체하지 않습니다.
현재 VLM은 이 64이미지와 Clef가 선택한 active_sources를 입력으로 받습니다.
CV 트랙을 VLM 설명에 추가하는 별도 실험은 기본 결과와 합치지 마세요. 이 기본 파이프라인의
CV·Clef 역할은 라우팅이고, VLM의 시각 입력 자체를 더 풍부하게 만들었다는 의미는 아닙니다.

## 6. 정답 검수와 측정 가능 범위

`ground_truth/sources.json`은 평가 전용입니다. `reference_label`은 후보 README 설명으로
만든 참고용이며 점수에 쓰지 않습니다. 검수자가 영상과 원본 어노테이션을 확인한 다음
`vlm.label`, `reviewed`, reviewer/reviewed_at을 채우세요.
fall_ground_posture는 관찰된 넘어짐/낮은 자세이며 의학적 collapse 확정이 아닙니다.
boundary_crossing은 경계 통과이며 무단 침입 확정이 아닙니다.
gate_entry_authorization_unknown은 진입 관찰과 권한 불확실성을 유지합니다.

YOLO는 선택된 원본 frame_number에 완전한 객체 박스를 작성해야 해당 프레임의 검출
precision/recall/mAP@.5를 계산할 수 있습니다. 일부 객체만 표시했다면 complete=false로
두세요. 그 프레임을 정상 음성이나 오검출 계산에 사용하지 않습니다. `objects=[]`와
complete=true는 해당 평가 클래스 객체가 실제 없음을 사람이 확인했다는 뜻입니다.
미주석 프레임을 빈 정답으로 만들지 마세요. 평가 프레임·정답 객체 수도 지표에 포함합니다.

```json
{"frame_number":0,"complete":true,
 "objects":[{"class_name":"person","bbox":[100,200,180,400]}]}
```

위 박스는 형식 예시일 뿐 실제 정답이 아닙니다. IoU=.5, confidence 정렬, 클래스별 1:1
매칭, 101점 AP를 사용합니다. 정답 없는 클래스의 AP는 null입니다. 박스는 원본 해상도의 xyxy입니다.
ByteTrack ID·행동 판정의 정답은 현재 없으므로 추적/배회/침입 성능으로 일반화하지 않습니다.

Clef 정답은 사건 이름으로 정하지 않습니다. CV 관찰만으로 정상이라고 확정하기 어렵거나,
행동·시간·권한을 해석해야 하거나 탐지 품질이 부족해 영상 검토가 필요한 상황은 호출 후보입니다.
호출 불필요 정답은 사전에 정의된 정상 운영 조건과 충분한 관찰 증거를 사람이 확인한 경우에만
작성합니다. 평가 전 영상별 invoke_vlm bool과 rationale를 검수하고 고정하세요.
현재 CV에는 확정 행동·구역·위험축 판단기가 없어 기본 Clef 입력은 불확실 상태입니다.
그렇다고 정답을 자동으로 전부 True로 채우지 않습니다. 실제 영상/정책의 검수가 필요합니다.

라우팅은 invoke_vlm/no_action/human_review를 제안합니다. no_action은 높은 확신과 충분한
CV 정보 조건에서만 호출 생략으로 적용됩니다. human_review는 VLM 호출과 사람 검토로 갑니다.
호출 생략은 알림 자동 억제가 아닙니다. 상위 실패 기본 경로는 중단입니다.
`fallback=invoke_vlm`에서는 Clef가 정상 완료하지 못한 모든 경우에 VLM을 호출하고,
상위 실패와 대체 경로를 함께 기록합니다. API 오류뿐 아니라 출력 변환 오류와
YOLO 실패로 Clef를 실행하지 못한 경우도 포함합니다. 정상 완료한 Clef의
`no_action` 결정은 유지하며 VLM을 실행하지 않습니다.
Clef가 막은 사건도 전체 파이프라인 평가 분모에 남고 VLM 책임으로 돌리지 않습니다.

VLM 허용 동의어: fall/collapse/ground posture→fall_ground_posture,
fight/conflict→physical_conflict, boundary crossing→boundary_crossing,
gate entry→gate_entry_authorization_unknown. 법적 intrusion을 경계 통과 정답으로 자동 치환하지 않습니다.
반환 스키마는 canonical 라벨을 요구하므로 동의어는 의미 평가에서만 허용되며 형식 유효성은
별도로 확인합니다. 충분한 사건 증거가 없으면 uncertain과 사람 검토를 반환해야 합니다.
정답 uncertain은 출력 품질 실패의 만능 대체 정답이 아닙니다. 실제 검수 근거가 필요합니다.

현재 사건 정확도, 호출 FN/FP, 검출 mAP, 근거 내용 정확성, 정상 영상 오경보율은 미측정입니다.
입력 프레임 참조의 유효성은 근거 내용의 정확성이 아닙니다. 후자는 사람 검수/정답 근거 구간이 필요합니다.
정상 대조 영상이 없어 전체 CCTV 오경보율을 주장할 수 없습니다. 최종 위험도는 백엔드에서 계산합니다.

## 7. CSV 읽는 법

`results/<run>/results.csv`를 Excel의 UTF-8 CSV 가져오기로 열거나 Python csv 모듈로 읽으세요.
문제당 한 행이며 stage 값은 JSON 셀입니다. JSON 안의 쉼표 때문에 줄을 수동 split하지 마세요.

| 컬럼 | 확인할 내용 |
|---|---|
| item_id | P001~P012 |
| sources | 원본 ID, 영상별 장수, 같은 사건 관계와 묶음 의미 |
| models | 모델·설정·실행 장치·계약/정답 해시·실행 횟수 |
| ground_truth | 단계별 검수 정답, 참고 라벨, 미확정/null |
| stage_inputs | 실제 프레임 목록, 요청·프롬프트·응답 파일 경로, 실제 실행 여부 |
| stage_outputs | 원본/정규화 파일 경로, 영상별 결과, skipped/blocked, fallback |
| metrics | 검출 지표, 호출 누락/불필요 호출, 사건 정확도, 별도 형식·근거 참조 검사 |
| latency_ms | 단계 시간, 입력 생성 디코딩 시간, 현재 실행 wall, 최초 사용 total |
| cost_usd | 사용량 기반 추정/미호출/unknown과 실제 영수증 값 구분 |
| status | completed/model_error/benchmark_error/execution_blocked_or_error/evaluation_unavailable |
| errors | 실패 단계·원인 분류·구체적 코드; 여러 실패가 동시에 보존됨 |

null은 알 수 없음/미평가입니다. 0은 실제 0을 확인했거나 API를 전혀 호출하지 않았음을 뜻합니다.
`current_run_wall`은 저장된 64장의 검증·모델·API·평가를 포함한 문제 실행 시간입니다.
`total_first_use`는 여기에 최초 프레임 추출 디코딩/PNG 생성 시간을 더한 값이며,
배포용 영상 복사·전역 잠금 생성은 포함하지 않습니다. 전체 사전 검사와 12문제 실행 wall 시간은
summary.json에 따로 기록합니다. 최초 CPU 모델 로드가 매 문제 포함됩니다.
서버 사용량×가격 값도 실제 결제 영수증과는 다릅니다. CPU/GPU 전기료·임대료는 별도입니다.
정답 없는 상태에서 형식만 유효한 결과를 성공 사건 판단으로 읽으면 안 됩니다.

## 8. 실패 확인

먼저 preflight.json을 확인하세요. 입력/해시/매핑/정답 형식 오류는 API 전에 차단합니다.
모델 파일·검출 출력은 `<item>/yolo.response.json`, 실제 API 상태/원본은
clef.response.json 또는 vlm.response.json, 변환 후 값은 *.normalized.json입니다.
API 미호출이면 응답 파일이 없을 수 있으며 결과는 blocked/skipped입니다.
인증·요금·용량·타임아웃은 execution 오류입니다. 유효한 요청에 대한 틀린 사건/잘못된
근거/스키마 불이행은 model 오류입니다. 변환기 오류인지 확인할 수 없으면 evaluation_unavailable로 남깁니다.

스키마 검사 실패, 원본과 변환 후 차이, 부분 정답 누락을 함께 확인하세요.
미실행 모델의 사건 결과를 만들거나 상위 라우팅 누락을 VLM 오답으로 집계하지 마세요.

## 9. 수정 허용 범위와 비교 규칙

**같은 벤치마크에서 수정 가능:** config/models.json의 모델·장치·추론 설정·가격·플러그인,
자기 모델 adapters, 새 결과 폴더, 로컬 환경변수. 모델별 변환과 시간을 기록해야 합니다.

**검수 후 수정 가능:** ground_truth/sources.json만 검수자·일자·근거와 함께 채웁니다.
이후 정답 해시를 고정하고 모든 비교 모델을 같은 정답으로 재평가하세요. 결과를 본 뒤 유리한
정답으로 바꾸지 마세요. 영상 관계를 수정할 필요가 있으면 새 벤치마크 버전입니다.

**같은 비교에서 수정 금지:** items.json, benchmark.lock.json, 원본 영상, 64프레임/manifest,
공통 prompt와 schema, 평가 수식·동의어·기준, 이전 결과, 예산 원장. 기능 변경은 새 버전/실험으로
분리하고 모든 모델을 같은 조건에서 실행하세요. 어댑터가 고정 입력을 바꾸지 못하도록 preflight와
실행 경계가 검사합니다. 네트워크 제공자가 실제로 어떤 내부 픽셀을 썼는지까지 증명하지는 못합니다.
추가 과금 승인은 예산 소유자 지시에 따라 MAIN이 paid_authorization.json에 기록하며,
모델 비교 담당자가 이를 임의로 만들어 한도를 해제하면 안 됩니다.

`prepare.py`는 MAIN의 최초 배포용입니다. 팀원은 다시 실행할 필요가 없고 기존 고정 입력을
재생성하면 안 됩니다. `source_export.json`은 개발 저장소에서 가져온 검증 소스의 출처입니다.
`evaluation.lock.json`은 공통 평가 코드·실행 경계·정답 스키마의 해시입니다.
모델 어댑터·config는 교체 가능하지만 같은 실험의 평가 코드는 이 잠금과 일치해야 합니다.
배포 후 모델별 어댑터 수정은 가능하지만 계약·평가 변경은 별도 버전으로 관리하세요.

공식 참고: [Clef 입력·질문·가격](https://developers.cloudflare.com/workers-ai/models/clef/),
[DeepSeek 가격](https://api-docs.deepseek.com/quick_start/pricing),
[YOLO 검출 평가](https://docs.ultralytics.com/modes/val/),
[ByteTrack 논문](https://arxiv.org/abs/2110.06864).
