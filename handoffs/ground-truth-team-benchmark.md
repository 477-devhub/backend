# 2026-10-09 정답 확보·팀원 자동 채점 인계

MAIN이 기존 작업을 이어받았다. 원본 477_modeling_benchmark_v1/final_candidates_v1 및 기존 실제 API 결과는 보존한다.

실제 역할: /root/annotation_detector_resume (model_engineer TOML, 소유 app/models/adapters/annotation_detector.py + tests/models/test_annotation_detector.py), 순차 /root/annotation_readiness_review (reviewer TOML, 읽기 전용).

공식 RT-DETR-L을 YOLO26s와 독립된 박스 초안 도구로 사용했다. 첫 실제 로드는 체크포인트 내부 DetectionModel 구조를 엄격 이름 검사해 실패했다. 실제 RTDETRDecoder head를 검사하도록 수정했고 집중47PASS, 실제로드/24프레임추론 exit0. 가중치 SHA256 6de60b10d4bc566f00cda0f5b4d64afe4b66d48dc9695d2171effb7859d8e73f. 후보1,081개 중 이미지 밖53개도 원본 그대로 표시한다. 후보는 reviewed=false/ground_truth_eligible=false이며 직접 정답으로 쓰지 않는다.

MAIN이 6개 영상 chronology/zoom과24개 박스 오버레이를 직접 확인했다. 후보에서 배경 전봇대 사람 오검출을 제거하고 병합 사람 박스 분리/누락 추가/발 범위를 수정했다. ai_review_v1/box_review_decisions.json에 선택·수정·추가를 명시했다. freeze_visual_truth.py 실행 exit0: 6영상 라벨/라우팅,24프레임39박스, 클래스 범위 내 완전18프레임/부분6프레임. SRC03 원경4프레임·SRC05 가림2프레임은 미평가. SRC01/04는6클래스, 나머지는 person 범위. 실제 검수한 희소 프레임만 평가하며 나머지 입력 프레임 정답을 추정하지 않는다.

정답 품질은 MAIN AI 시각 검수 데모 기준이며 독립 전문가/사람 gold가 아니다. SRC04 staged 맥락, SRC05 occlusion을 명시했다. 라우팅은 사건 이름이 아닌 직접 관찰 이상행동/권한·가림 불확실성 기준이며6개 모두 호출 필요. 정상 오경보·불필요 호출률 측정 불가. 정답 원본 pending 파일은 보존하고 별도 ai_review_v1/sources.json과 해시 lock 사용.

명령(저장소 루트 PowerShell):

```powershell
.venv-benchmark\Scripts\python.exe -B app\models\adapters\annotation_detector.py --weights new_477_piprline\models\rtdetr-l.pt --frames new_477_piprline\ground_truth\ai_review_v1\candidate_frames.json --output new_477_piprline\ground_truth\ai_review_v1\rtdetr_candidates.json
.venv-benchmark\Scripts\python.exe -B new_477_piprline\prepare_annotation.py --mode overlay
.venv-benchmark\Scripts\python.exe -B new_477_piprline\freeze_visual_truth.py
```

후보 출력 경로가 이미 존재하면 재실행은 새 경로를 지정해야 한다. 첫 명령 실제 총46.824초/모델 추론35.116초(CPU640,conf0.08), 유료 API0회. 전체 테스트 최신581PASS82.37초, 기존경고1; check_contracts.py Frozen contracts match. reviewer readiness PASS는 후보 생성 단계 승인이다. 정답 게이트와 팀 채점 구현/통합은 후속 확인 대상이다.

팀 채점 계약은 MAIN TEAM_CONTRACT.md. 고정12문제 입력/프롬프트/64이미지+정답 없는 제출CSV+score.py를 전달한다. 정답은 평가자 영역, 모델 코드/설정/출력만 교체 가능. 기존 실제 결과는 새 정답으로 재채점하되 새로운 추론으로 표시하지 않는다.
