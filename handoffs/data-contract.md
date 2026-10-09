# 데이터 담당자 계약 확인 요청

기준: `docs/dataset-handoff.md`, `docs/model-contract.md`, `docs/evaluation-contract.md`.
이 안내는 전달 자료이며 직접 전송하지 않았다. 실제 데이터 납품·담당자 확인은 아직 없다.

필요 납품: manifest.jsonl, 실제 media/, 추론 전용 inputs/, asset-map.json, DATA_CARD.md, checksums.
validation 소량을 먼저 받고, validation으로 설정을 고정한 다음 test를 한 번 실행합니다.

MP4 companion videos[]/annotations JSON 파서는 app/eval/annotations.py에 있습니다.
event_class mapping을 명시해야 하며 parser는 window/input/split/group를 만들지 않습니다.
caption/cot/answer/bbox/frame_id는 평가 전용으로 보존하고 CV sampling/feature에 복사하지 않습니다.
같은 c1/c2 사건은 같은 scenario group이며 실제 fps/PTS/framebase/hint 정합성 확인이 필요합니다.
현재 예시에 없는 critical/review/risk 정답은None이며 임의false/0/50을 생성하지 않습니다.

- 원본 source_video_id·사건 scenario_group·중복 media hash는 하나의 split에만 둡니다.
- inputs는 중립 sample_id/clip_ref/media_ref와 입력 창 안의 실제 frame_id/timestamp를 사용합니다.
  provider에게 경로·파일명·manifest·split·정답·정답 timestamp를 보내지 않습니다.
- 고정 sampling/extractor는 정답 없이 만들고 version/window/provenance/time를 기록합니다.
  자유 텍스트에 정답을 담는 의미상 누수는 key 검사만으로 안전하다고 할 수 없습니다.
- event_type/critical/review 정답 정의·주석자·불일치 처리 기준이 필요합니다.
  미주석 risk_axes는 null로 전달하며 AI가 지어낸 축을 사람 정답으로 표시하지 않습니다.
- DATA_CARD에 데이터셋 이름/ID/버전, 허용 이용·재공유 범위, 클래스/split 개수,
  source/scenario 정의, 분할 seed/규칙, 제외/중복 처리, checksum을 기록합니다.

회신에는 수용 여부, 납품 경로, annotation 및 group 규칙과 미납품 항목을 기록해 주세요.
현재 저장소의 .gitkeep 또는 fixtures는 실제 데이터 납품으로 인정하지 않습니다.
