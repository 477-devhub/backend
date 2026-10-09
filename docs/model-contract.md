# 모델 계약 1.1

현재 AI 연동 v1: optional RoutingAssessment/evidence_descriptions/metadata.stage_trace 추가.
P1 구간 관측 기반 정상 제외는 frozen gate와 backend risk<20를 모두 통과해야 하며
비어 있는 citation을 만들지 않는다. execute는 실제 입력 프레임이 있는 검증된 P1 normal만
구간 관측 예외로 허용한다. 나머지 risk 측정 결과는 실제 frame citation을 요구한다.
실행 설정·한계는 docs/ai-integration.md 참조.

Local CV registry는 `get_adapter("local_cv", resolver=prepared.resolver)`로 실제 CPU HOG
관측 adapter를 생성한다. `.[local-cv]`가 필요하며 resolver 미주입은 명시 미설정 실패다.
기본4-frame/640x360 sampling의 실제 clip-frame 일치를 재검증한다. 관측과 IoU 추적만
측정하며 pose/zone/6-event classifier는 미지원이다. 판단은 uncertain/confidence0/
각 risk axis=null/review이며 mock은 아니다. CV→provider feature 사용은 별도 실험이다.

전처리 실패는 공통 execution.failure_assessment의 제한된 preprocessing_error 코드로
기록한다. 검증된 프레임이 없으므로 evidence_refs=[]이며 uncertain/null/review/nonmock다.
실행하지 않은 모델의 latency/cost는null이고 전처리 소요 시간은 평가 record의 phase로 기록한다.
provider 예외 원문/자격증명은 failure reason으로 전달하지 않는다.

현재 스키마 소스: app/schemas/model.py. 초안은 계약 해시로 고정되어 있습니다.
MAIN이 변경 영향과 프론트 대응을 확인한 뒤 버전·문서·테스트를 함께 수정할 수 있습니다.

ModelInput: schema_version, 중립 sample_id, camera, window, clip_ref(선택), temporal_state, evidence[].
EvidenceFrame: frame_id, timestamp_ms, media_ref. 로컬 path 필드를 제거했습니다.
clip_ref/media_ref는 중립 token이며 app/models/media.py의 신뢰된 resolver가 실제 bytes로 변환합니다.
원본 경로, manifest, label, split, 파일명, 정답 타임스탬프를 provider request에 보내지 않습니다.
실제 adapter는 resolver를 생성자로 받도록 구현하고 MAIN이 registry에서 연결합니다.
현재 실제 adapter는 미구현이므로 resolver 자동 주입도 후속 과제입니다.
MediaResolver.from_asset_map은 UTF-8 token→path JSON을 읽으며 중복 token/잘못된 mapping을 거부합니다.
ASSET_MAP/ASSET_ROOT는 신뢰된 로컬 lookup용이며 provider에 보내지 않습니다.
read(max_bytes=...)는 원본 bytes budget을 제한하고 root 밖 경로를 거부합니다.
with_assets는 고정 sampling으로 만든 중립 frame bytes를 별도 memory resolver에 연결합니다.
신경망/event 모델 선정·실제 미디어 검증·provider 연결은 아직 완료되지 않았습니다.
MAIN은 선택적으로 create_app(media_resolver=...) 또는 ASSET_MAP에서 MediaIngestion 생성자에 resolver를 주입합니다.
app.state.prepare_model_input은 window 기반 고정 grid에서 실제 FFmpeg PTS/JPEG를 얻고,
실제 bytes에 연결된 ModelInput/resolver와 checksum/profile/preprocessing_ms를 반환합니다.
기존 evidence/temporal 관측으로 sampling하지 않으며 raw 모드 temporal_state는 비웁니다.
prepared 입력은 별도로 ingest_model_input에 넘깁니다. 자동 live ingestion이나 실제 adapter 구현은 아닙니다.
현재 frame cache는 memory bytes이며 feature extractor/디스크 feature cache는 미구현입니다.
개발 backend에는 `create_app(..., adapter=...)`와 `app.state.ingest_model_input(ModelInput)`의 내부 연결이 있습니다.
MAIN이 registry adapter → execute → policy → repository → WS snapshot을 연결합니다.
기본 MODEL_ADAPTER=local_cv는 미설정 real slot을 유지하며 mock은 명시적 mock_* 선택으로만 사용합니다.
MODEL_TIMEOUT_SEC는 양수/유한 값이어야 합니다. 라이브 영상 ingestion·실제 media 주입·provider 검증은 별도 미완료입니다.

ModelAssessment: event_type, event_confidence, risk_axes(각 축 0..1 또는 null), needs_human_review,
uncertainty_reason, evidence_refs, metadata. extra 필드는 거절하고 NaN/Inf는 거절합니다.
기존 Pydantic 인스턴스와 dict 안의 중첩 인스턴스도 실행 경계에서 재검증합니다.
`model_copy`/`model_construct`로 범위를 우회한 출력은 schema_or_contract/null/사람 검토로 처리합니다.
이 검증 강화 자체는 JSON shape를 변경하지 않습니다. 축별 null 확장으로 새 기본 schema_version은 1.1입니다.
operator evidence는 입력 frame_id와 timestamp_ms를 연결합니다. bbox/temporal observations는 추론으로 얻은 자료여야 합니다.
범용 dict 안의 텍스트까지 의미적으로 누수를 막을 수는 없으므로 extractor provenance와 표본 검토가 필수입니다.

모든 호출은 await execute(adapter, model_input, timeout_sec)를 사용합니다.
타임아웃, SDK 오류, 잘못된 스키마, input mutation, 잘못된 frame reference는 uncertain/review로 변환합니다.
실패 risk_axes=null, risk=null, level=UNKNOWN입니다. 이전 4등급에 UNKNOWN을 더한 명시적 프론트 계약 변경입니다.
실패는 실제 위험 0 또는 중간 위험 50이라는 뜻이 아닙니다.
asyncio.wait_for는 이벤트 루프를 차단하는 동기 GPU 연산을 끊지 못합니다. 실제 CV는 bounded process/GPU worker가 필요합니다.
취소 후 provider 요청이 남을 수 있어 retry·비용·worker 회수를 별도로 검증하세요.

mock_local_cv/mock_clef/mock_vlm은 오직 연결 점검용입니다. local_cv/clef_direct/general_vlm은 미설정 상태에서
명확한 provider_error를 반환하고 CLI exit 2가 됩니다. provider를 추정해 만들어 넣지 않습니다.

## 모델 독립성 및 공정성
A: Local CV가 원본 clip/frames로 추론. B: Clef 단독. C: VLM 단독.
공통 ModelInput은 bytes 접근 권한이 같은 고정 샘플이며 모델이 사용할 modality는 실제 capability와 함께 기록합니다.
B/C에 CV features를 함께 주면 결과 이름을 CV→Clef/CV→VLM로 적으세요. 이를 '완전 단독'이라고 표시하지 않습니다.
B/C 공통 feature cache는 label 없이 동일 extractor/version/window로 생성합니다.
연산 시간/비용은 extractor + bytes/frame prep + provider + routing 전체와 provider-only를 구분합니다.
CV가 네 위험축을 측정할 수 없다면 null/review와 지원 범위를 기록하고, 임의로 위험축을 만들어 성능을 비교하지 않습니다.
D: router→VLM은 A/B/C 평가와 candidate missed-event recall 확인 후 추가합니다.

## 2026-10-07 추가 요구 반영

ModelInput 필드 역할은 기존과 같다. 기본 버전은 1.1이며 기존 1.0 입력/완전 측정 출력도 읽을 수 있다.
축별 null 출력은 1.1로 표시한다. risk_axes 전체 null도 계속 허용한다.
각 축의 미측정은 null이다. 하나라도 null이면 합산·가중치 재분배·0 대입을 하지 않고 최종 risk=null/UNKNOWN/review로 유지한다.
완전 측정인 경우 기존 round(100*(.35*S+.30*I+.20*E+.15*P))를 사용하고 confidence를 곱하지 않는다.

MP4와 동봉 JSON의 videos[]는 source descriptor이며 annotations 전체는 평가 전용이다.
annotations.event_class/question/caption/cot/answer/evidence(frame_id/obj_id/obj_bbox/obj_label/evidence_text)를
ModelInput/temporal_state/추론 prompt/evidence sampling에 복사하지 않는다.
lo_e1015_c1.mp4처럼 라벨을 암시하는 원본 filename은 asset-map의 로컬 lookup에만 보관한다.
sample_id/clip_ref/frame refs는 중립화하며 camera metadata도 정답 문구가 없는지 provenance를 검토한다.
동일 사건의 c1/c2는 scenario_group을 공유하고 각 원본 영상은 source_video_id를 따로 갖는다. 같은 scenario는 split을 넘지 않는다.
annotation frame 번호→평가 timestamp 대응에는 실제 영상 fps/PTS 확인이 필요하고 frame 번호를 추론 evidence로 사용하지 않는다.

temporal_state 이동/추적 정보는 실제 CV 추출 결과만 허용한다. 현재 raw sampler는 관측을 비우며 CV extractor는 후속 04 역할 작업이다.
Clef가 features-only이면 지원 capability를 확인한 뒤 label-free extractor를 독립 실행할 수 있게 주입하고
CV→Clef 실험으로 명시한다. VLM도 실제 지원하는 media/feature 입력만 사용한다.
공통 JSON shape만으로 실제 model capability/독립성/fairness를 보장하지 않는다.
