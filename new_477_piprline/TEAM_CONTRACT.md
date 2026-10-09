# 팀원 제출·자동 채점 계약 v1

MAIN 확정일: 2026-10-09. 기존 12문제·문제당 총64프레임·원본 프롬프트와 출력 스키마를 그대로 사용한다. 정답은 별도 평가자 영역에 둔다. 팀원 코드가 정답/검수 이미지를 모델에 전달하면 해당 결과는 비교 대상에서 제외한다.

제출 CSV는 UTF-8, 문제당 한 행이다. 컬럼은 `item_id,sources,models,stage_inputs,stage_outputs,latency_ms,cost_usd,status,errors`이다. item_id/status를 제외한 셀은 유효한 JSON이다. 자동 채점 결과 CSV에는 ground_truth와 metrics를 추가한다. 제출자가 작성한 점수는 읽지 않는다.

`stage_outputs`는 yolo/clef/vlm 키를 갖는다. 각 값은 기존 정규화 stage record 자체 또는 `{"record_path":"submissions/my_model/P001/yolo.json"}`이다. 경로는 벤치마크 루트 기준 상대경로이며 루트 밖 파일·심볼릭 링크 우회·원격 URL은 거부한다. record는 `status: ok/error/blocked/skipped`, `executed: true/false`, `model`, `output`, `errors`를 기록한다. 실패한 실제 VLM 출력은 기존 계약처럼 invalid_output에 보존할 수 있다. skipped/미사용 모델 결과는 만들지 않는다. 비용 미확인은 null이며 비용 근거는 api_usage_estimate/invoice_actual/unknown 등으로 명시한다.

YOLO output은 `{"frames":[{"frame_id":"SRC01-F000000","source_id":"SRC01","detections":[{"class_name":"person","bbox":[1,2,30,40],"confidence":0.9}]}]}` 형식이다. 실제 실행했다면 입력64프레임의 빈 탐지도 포함한다. 좌표는 원본 이미지의 xyxy 픽셀이다. 검출과 사건 판단은 별도 점수다.

Clef output은 `{"sources":[{"source_id":"SRC01","invoke_vlm":true}]}`이다. 호출 누락/불필요 호출/판단 불가를 구분한다. Clef 없는 파이프라인은 models.clef=null, Clef record skipped/executed=false/output=null이며 라우팅 점수는 미사용/N/A다. VLM 단독이나 CV+VLM도 최종 사건 점수의 분모는 문제의 모든 source다.

VLM output은 schemas/vlm_output.schema.json의 `assessments`이다. source별로 canonical event_type, event_confidence, risk_axes, evidence_refs, needs_human_review, uncertainty_reason, metadata를 반환한다. VLM record의 active_sources에 실제 요청한 source 목록을 기록한다. Clef가 호출을 막으면 해당 source는 최종 사건 점수에서 누락으로 집계하며, 실행하지 않은 VLM 오답으로 귀속하지 않는다.

입력은 고정 items.json과 data/frames/Pxxx/manifest.json에서 읽는다. 프롬프트는 prompts/pipeline_v1.txt다. 평가기는 benchmark.lock.json 중 실제 프레임/프롬프트/스키마/문제 목록의 해시와 64장 배분·타임스탬프·source 관계를 검사한 뒤 채점한다. models/가중치는 제출 패키지에 불필요하다.

점수는 기존 evaluate_item을 재사용한다. 주 점수는 전체 source 사건 정답률×100이며 검출 precision/recall/mAP@0.5, 라우팅, 출력 형식, 입력 근거 유효성, 사람 검토 정책은 각각 분리한다. 문제 전체 정답률과 source 정답률을 함께 기록한다. 중복 영상 조합은 독립 사건 표본이 아니므로 6개 단독 문제 점수도 따로 보고한다. 합격 판정이나 임의 가중 합산 점수는 만들지 않는다.

정답 품질은 AI 검수 데모 기준이다. 24개 희소 프레임 중18개는 선언한 클래스 범위에서 완전 검수했고6개는 부분 검수/미평가다. 원경/가림 영상은 person만 평가한다. 모든6영상 라우팅 정답이 호출 필요이므로 정상 오경보율·불필요 호출률·Clef의 비용 절감 성능은 측정 불가다. 근거의 사건 시간대 포함 여부는 거친 시각 검수 구간과 비교한 보조 지표이며, 설명 사실성의 전문가 판정을 대신하지 않는다.

팀원이 수정할 수 있는 범위는 자신의 모델·API 설정·추론/변환 코드·submissions/의 출력이다. 입력 이미지/manifest/프롬프트/스키마/평가기/정답/잠금파일은 공통 비교에서 수정하지 않는다. crop·추가 프레임·prompt 변경은 별도 실험으로 결과를 분리한다.
