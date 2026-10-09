# 데이터 담당자 전달 규격

담당3에게 이 문서를 전달하세요. AI Hub 영상 자체는 이번 키트에 없습니다.
데이터 다운로드 허용 조건/공유 가능 범위는 실제 선택 데이터의 이용 조건을 확인합니다.
원본 제공 train/validation 구성이 있으면 먼저 유지하고, 추가 test 구성 근거를 기록하세요.

납품 폴더: manifest.jsonl, media/, inputs/, asset-map.json, DATA_CARD.md, checksums.
manifest는 평가자 전용 정답을 포함합니다. inputs는 추론 정보만 포함합니다.
inputs 추출은 role1의 CV/ingestion 담당과 협업하고, annotation의 정답으로 feature나 evidence 시점을 만들지 않습니다.
asset-map은 {clip_000001:'media/중립.mp4', frame_000001:'frames/중립.jpg'}처럼 중립 token→local path이며 provider에게 전달하지 않습니다.

manifest JSONL row 예시 (media_sha256은 실제 파일 hash로 교체):
```json
{"sample_id":"s_000001","split":"validation","scenario_group":"scene_001","source_video_id":"source_001",
"video_path":"media/000001.mp4","media_sha256":"실제 SHA256 64자리","input_path":"inputs/000001.json",
"camera_id":"CAM_01","start_ms":0,"end_ms":10000,"event_type":"collapse","critical":true,
"needs_human_review":false,"risk_axes":null}
```

sample_id는 s_ 뒤 중립 영문 소문자/숫자 6자 이상. 정답 이름을 ID에 넣지 않습니다.
동일 원본 영상·같은 사건/촬영군·중복 영상은 하나의 split에만 속해야 합니다.
프레임/잘라낸 clip을 무작위로 나눠 같은 원본이 train/test에 동시에 들어가면 누수입니다.
여러 CCTV가 같은 사건을 찍은 경우 scenario_group을 공유합니다. source_video_id는 원본 영상별 ID입니다.
검사기는 scenario/source/hash 교차 split, 중복 sample, path traversal, media hash, window/input 일치 등을 검사합니다.
카메라/시간/사람의 일반화 실험은 별도 설계하고 near-duplicate 영상 검사는 사람·영상 중복 탐지를 추가해야 합니다.

DATA_CARD: AI Hub dataset 이름/ID/버전, 라이선스·재공유 범위, 전체·클래스·split 개수, 분할 seed/규칙,
원본 그룹 정의, 위험/critical/review/risk_axes 라벨의 정의·주석자·일치도, 제외/중복 처리 기록.
위험축 정답을 AI로 임의 생성해 사람 정답으로 표시하지 마세요. 미주석은 null입니다.

정답 라벨=행동 종류의 사실 주석. 위험성/검토 필요는 별도 기준으로 정의합니다.
모델 출력에 annotation를 넣는 converter는 금지. 텍스트/zone context 안의 정답 누수는 자동 키 검사만으로 보장되지 않습니다.

1. validation 소량 먼저 전달 → 코드/영상/추론 전처리 확인.
2. validation에서 모델·prompt·threshold·sampling 고정.
3. scripts/freeze_dataset.py로 manifest + run config hash 고정.
4. test 명령은 --allow-test + --lock + --run-config 필요. 최종 test 실패 샘플로 다시 튜닝하지 않습니다.

## MP4 + videos/annotations JSON 추가 규격

동봉 JSON의 videos[]는 filename/width/height/date/time/length/cctv metadata/source/view 정보를 가진다.
annotations(event_class/question/caption/cot/answer/evidence의 frame_id/obj_id/obj_bbox/obj_label)는 평가 정답 영역이며
추론 inputs/temporal_state/prompt/frame sampling에 넣지 않는다. 원본 filename의 lo_ 등 라벨 힌트도 provider에 보내지 않는다.
같은 예시 사건 lo_e1015의 c1/c2는 동일 scenario_group으로 동결하고 별도의 source_video_id를 사용한다.
중립 sample_id와 clip/frame token을 생성하고 sampling window/grid는 정답 시작·끝/frame hints와 독립적으로 정한다.
실제 MP4 bytes의 checksum/decoder PTS로 납품 metadata와 추출 frame을 검증한다. annotation frame 번호의 fps를 추정하지 않는다.
한국어 event_class→공통 EventType mapping은 평가자 전용이다. 예시 '특정 구역 내 지속 배회'는 loitering 대상이지만
다른 event class, normal/negative, critical/review/risk 축 주석 규칙은 별도 명시 확인이 필요하다.
예시에 없는 critical/review/risk 정답을 caption/answer에서 임의로 생성하지 않는다. 미주석 위험축 각각은 null이다.
camera id/view 매핑은 납품 규칙으로 정하며 영상별 실제 fps/PTS와 annotation frame numbering 기준도 전달해야 한다.
이 JSON 예시만으로 실제 media 납품·class mapping·분할·주석 합의를 완료 처리하지 않는다.
