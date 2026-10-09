# 새 전체 파이프라인 벤치마크 계약 v1

이 문서는 실행 전 고정한 설계이다. 기존 두 자료 폴더와 이전 결과는 변경하지 않는다.

대표 문제 12개: P001~P006 = SRC01~SRC06 단독; P007 = SRC01+SRC02;
P008 = SRC05+SRC06; P009 = SRC01+SRC03+SRC05; P010 = SRC01~SRC04;
P011 = SRC01~SRC05; P012 = SRC01~SRC06. 총 768 입력 슬롯이며 독립 영상 수는 6이다.
SRC05/06만 README상 같은 사건의 다른 시점이다. 나머지 조합은 다른 사건 묶음이다.
동기화·동일 사람 ID는 추정하지 않는다. 각 영상 총 프레임수 F에서
round-half-up(j*(F-1)/(n-1))로 n장 균등 선택한다. 64를 영상 수로 나누고
나머지를 목록 앞부터 배분한다. 원본 0 기반 frame_number와 실제 fps 기반 timestamp를 보존한다.

실행 입력: item_id(로컬 관리), sources(중립 ID), frames 64개
{frame_id,source_id,frame_number,timestamp_sec,width,height,image_path,sha256},
prompt, output_schema, active_sources(VLM에서 실제 호출 대상).
정답, 설명형 파일명, 관계 정답, 후보 라벨, 정답 박스는 모델에 전달하지 않는다.

YOLO 정규화 출력: frames [{frame_id,source_id,detections:[{class_name,bbox,confidence,track_id}]}],
tracks (source별 독립), limitations, model metadata. 사람/자전거/자동차/오토바이/버스/트럭
6 COCO 클래스만 기존 CV와 동일하게 측정하며 정답도 이 범위로 명시한다.
검출은 행동 분류가 아니다. 자세·추가 crop·추가 프레임은 기본 실험에 사용하지 않는다.

Clef: CV에서 추출한 중립 관찰만 state로 보내며 영상별 incident.SRCxx(noul)와
route.SRCxx(choice: invoke_vlm/no_action/human_review)를 질문한다. 기존 계약의
confidence>=.90, incident_probability<.35, CV 불확실성 없음 조건에서만 no_action을
호출 생략으로 변환한다. human_review는 VLM 호출+사람 검토이다. CV의 구역·행동·위험축이
없으면 안전상 불확실로 처리한다. no_action은 알림 자동 억제 권한이 아니다.
실패 기본 경로는 중단이며 선택한 fallback 경로는 별도 기록한다.

VLM: 하나의 요청에 고정 64이미지와 중립 프레임 목록을 보낸다. active_sources별
독립 assessment를 반환한다. 호출 생략 영상은 결과를 만들지 않는다. 같은 사건이라는
정답 정보는 입력하지 않는다. 라벨은 normal/fall_ground_posture/boundary_crossing/
gate_entry_authorization_unknown/physical_conflict/loitering/uncertain이다.
boundary_crossing은 법적 침입 판정이 아니다. 증거는 같은 source의 실제 frame_id만 허용한다.
측정하지 못한 risk_axes는 null, 최종 위험도 계산은 백엔드 몫이다.

정답 파일: source별 yolo.frames [{frame_number,complete,objects:[{class_name,bbox}]}],
clef {invoke_vlm:null|bool,reviewed:bool,rationale},
vlm {label:null|string,reviewed:bool,reference_label:null|string,reference_note}.
누락은 null/미평가이다. 일부 객체만 표시된 프레임은 complete=false로 두고 mAP/precision에
사용하지 않는다. 검수자·검수일·근거 파일을 함께 저장한다. 모델 입력과 별도 로드한다.

평가 전 고정: YOLO IoU=.5, 클래스별 confidence 정렬/1:1 매칭, 101 point AP;
precision/recall는 설정 conf 이상 검출 기준. 정답 없는 클래스 AP는 null이다.
Clef는 영상별 실제 invoke_vlm bool을 정답과 비교하고 FN(놓친 호출)/FP(불필요 호출) 기록.
VLM은 동의어표를 선고정하고 검수 완료 정답만 정확도 분모에 포함한다.
형식/입력 근거 참조 유효성과 사건 정답은 별도 지표이다. 근거 내용 정확성은 추가 검수 필요.
VLM skipped/blocked/error는 사건 정답이 있는 경우 전체 파이프라인의 미완성/누락으로 포함한다.

제안 기술 합격 기준: 문제마다 64, 추적 가능한 프레임 100%, 정답 누출 0,
CSV 12행, JSON 셀 100% 파싱, 평가 코드 정답/오답/누락/생략 자기검증 통과.
의미 성능 기준은 검수 정답과 정상 음성 표본 부족으로 설정·통과 주장 불가.
최초 CPU 실행 1회, 속도는 디코딩/모델/전체로 분리한다. 반복 성능 비교로 일반화하지 않는다.

소유 범위: MAIN은 new_477_piprline 공통 계약·실행·README·문제·통합·배포 복사;
evaluation_engineer는 app/eval/new_pipeline_metrics.py와 tests/eval 관련 테스트;
model_engineer는 한 번에 app/models/adapters/new_pipeline_{cv,clef,vlm}.py 한 파일과
tests/models 관련 테스트; reviewer는 읽기 전용이다. MAIN이 검증된 소스의 독립 실행 사본을
새 폴더 pipeline477/에 동결 배포한다. 원본 자료 폴더와 기존 계약은 불변이다.
