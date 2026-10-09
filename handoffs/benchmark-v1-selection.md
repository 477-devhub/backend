# Benchmark v1 — 1단계 인계 (2026-10-07)

## 현재 범위와 자료

사용자는 이번 단계에 자료 확인·추천만 허용했다. 최종 모델·실행 환경을 전달하기 전 모델 다운로드·유료 GPU 생성·유료 추론·학습은 시작하지 않는다. 2·3단계 baseline 구현/실제 모델 평가는 아직 미실행이다.

최종 검토 기록(2026-10-08): **1단계 완료·reviewer PASS**. 실제 baseline·모델 성능 승인은 아니다. 최종 모델·환경과 계약/정답 관련 blocker는 아래와 같다.

- [자료 감사](../reports/benchmark-v1-data-audit.md):6영상/7ITEM/448canonical RGB 검증, 코드/정답/스키마 차이와 실제 검사.
- [모델 선정 보고서](../reports/model-selection-v1.md): 우선/대안, 공식 근거, GPU·양자화·입력 변환·예상 비용·후속 평가 계획.
- `reports/benchmark-v1-audit-visuals/`: MAIN이 canonical448프레임을 확인한 contact sheets7개. 사람 검토용이며 모델 입력이나 GT가 아니다.
- 기존 하네스/공통 계약과 두 원본 패키지를 유지했다. `optional_parallel.txt`는 실행하지 않았다.

## 추천 결정과 미실행

| 역할 | 우선 / 대안 | 확정·미확정 |
|---|---|---|
| Local CV | yolo26s-pose.pt / yolo11s-pose.pt | 공개 체크포인트 확인. tracking+시간누적+규칙 필요. 다운/추론0 |
| VLM | Qwen/Qwen3-VL-4B-Instruct / Qwen/Qwen3-VL-8B-Instruct | 공식 기능 확인. Linux CUDA24GB/48GB는 초기 계획으로 실제peak/속도 미측정 |
| Clef | @cf/cloudflare/clef, bodyselector clef | 사용자 지정·공식확인. env3키 존재만확인, 계정접근/이미지serializer/실응답 미검증 |

Clef는 typed decision이며 자연문 생성 VLM 대체가 아니다. CV의64프레임 특징을 전달하는 경로는 CV+Clef라고 명명하고 CV 비용·시간을 합산한다. 독립 실행기에서 특징 파일만 읽을 수 있더라도 원시영상 단독 이해 성능으로 보고하지 않는다. Clef 이미지 독립 비교가 필요하면 동일64장 분할(REST최대4장)과 고정 집계를 별도 검증해야 한다. 모델별 이미지/feature 입력 예산과 추가 변환 시간을 남긴다.

## 계약·평가 blocker

1. benchmark risk4축은 숫자 필수, prediction null 불가다. 기존1.1은 미측정=null이다. benchmark owner가 측정 정의/지원불가·실패 기록 및 제출 정책을 결정해야 한다. 임의숫자/unknown=0/50/가짜prediction 금지. 이번에 스키마를 변경하지 않았다.
2. 기존4프레임 HOG 경로는 canonical64와 다르므로 baseline으로 바로 재사용할 수 없다. MAIN이 입력 경계/bridge를 담당하며 writer는 공통 파일을 변경하지 않는다.
3. publicGT/normalnegative/reference rubric이 없다. 정확도·위험축MAE·오탐률은 N/A다. 데모 시나리오명/순위 설명을 GT나 튜닝 근거로 사용하지 않는다.
4. 기본 validator는 영상 범위내시각만 검사한다. canonical frame ID/시각 매칭과 실제64장 소비 로그를 추가로 검증해야 한다.
5. Clef-Flash/Jev는 자동 선택하지 않는다. 라우팅 추가실험의식별/compatibility envelope를 owner와 확인한다. 라우팅 누락 사건은 전체pipeline 분모에 포함한다.
6. 다중뷰 precise sync/동일인물 GT는 미제공이다. 동일사람/의도/권한을 단정하지 않고 AB vs best single(A,B)을 비교하며32+32 vs64 budget차이를 밝힌다.

## 다음 작업에 필요한 정보

- 최종 CV/VLM 체크포인트·precision·revision; OS/CPU/GPU모델·VRAM/driver/CUDA, hostRAM/디스크.
- 데모 응답시간 목표, GPU 공급자/허용 예산·할당시간, Clef 실제 추론 시작 시점·실험 요청/비용 범위. 기존 token을 다시 보내지 않는다.
- evaluator GT/annotation/rubric 및 event mapping/risk definition/N/A 정책, negative 영상 여부.
- benchmark owner의 미측정·실패 결과 정책과 라우팅 실험 명명. YOLO 라이선스/배포 조건.

정보가 오면 기존 구현을 유지하며 MAIN bridge·계약 검증→Local CV→Clef→VLM adapter를 별도model_engineer에 순차 위임→evaluation_engineer→MAIN 통합→reviewer 순으로 진행한다. 등록 소유 범위를 지키고 공통 변경은 MAIN이 반영·검사·재동결한다. 현재패키지를 임의 변경하지 않는다.

## 이번 실제 에이전트와 검사

- `/root/benchmark_v1_inventory` (explorer): 자료/코드/스키마/영상·canonical검사, 읽기 전용 종료.
- `/root/benchmark_v1_cv_selection` (model_engineer): Local CV 공식 조사, 읽기 전용 종료.
- `/root/benchmark_v1_vlm_selection` (model_engineer): VLM 공식 조사, 읽기 전용 종료.
- `/root/benchmark_v1_clef_capabilities` (model_engineer): Clef hosted계약 조사, 읽기 전용 종료.
- `/root/benchmark_v1_selection_reviewer` (reviewer): **1단계 PASS**. 독립 focused 22 passed/경고1, 계약 match, lock 23/23 및 영상 6/6 일치. 변경0/모델 실행0.

서브에이전트 파일 변경0, nested delegation0, 순차 실행. 등록TOML의 model/effort/지시문을 적용했으며 OS파일권한 강제성은 별도 인증하지 않았다. MAIN은 문서/TASKS/감사용이미지를 작성했다.

MAIN 및 explorer: packagecwd에서 `python -B scripts/validate_package.py`→448frames PASS, `python -B scripts/inspect_item.py --all`→PASS,6영상checksum일치. PATHPython3.11.5에는jsonschema/referencing이 있어 설치가 필요없었다.

MAIN: `.venv/Scripts/python.exe -B -m pytest -q`→212passed, warning1; `scripts/check_contracts.py`→Frozen contracts match. RAMsyntheticprobe로nullrisk거부/noncanonicaltimestamp허용을재현했고파일제출0. 이 검사는 model 성능/실제baseline PASS를 의미하지 않는다.

MAIN 최종 단계 검사도 **212 passed**, 기존 경고1,22.24s 및 **Frozen contracts match**다. reviewer focused 명령은 `.venv/Scripts/python.exe -B -m pytest -q tests/contracts/test_schema_v11.py tests/eval/test_media_pipeline.py`이며 **22 passed**, 경고1,5.57s다. 두 입력 패키지 파일과 공통 계약은 변경하지 않았다.

모델 추론 반복0, API 요청0, model download0, GPU생성0, 학습0. 실제 정확도/모델latency/peakVRAM/API usage·청구는 미측정이다. 실제 평가에서는 ITEM첫요청과modelcoldstart를구분하고warm5회/concurrency1, 전처리·추론·serialization전체·memory·오류·schema rate·실제/추정비용을기록한다.
