# 477 AI — Final Evaluation Videos

이 폴더는 477 AI의 최종 Evaluation 영상 확인 및 데모 공유용입니다.
총 **6개의 unique clip으로 5개의 scenario**를 구성합니다. `clips/`의 MP4를 열어 확인하세요.
모든 영상은 frozen Benchmark media의 동일한 파일 복사본이며 재편집·재인코딩하지 않았습니다.

## Scenario 01 — Fall / Ground Posture
Video: [clips/01_swoon_fall.mp4](clips/01_swoon_fall.mp4) — 35초

정상 이동 → 넘어짐 → 낮은 자세 지속을 시간 흐름으로 이해하는지 평가합니다.
관찰된 행동을 설명하며, 의학적 진단을 뜻하지 않습니다.

## Scenario 02 — Clear Boundary Crossing
Video: [clips/02_clear_wall_crossing.mp4](clips/02_clear_wall_crossing.mp4) — 35초

담장 밖 → 담장 넘기 → 안쪽 이동이라는 명확한 경계 통과를 평가합니다.
출입 권한과 법적 무단침입 여부는 영상만으로 확정하지 않습니다.

## Scenario 03 — Ambiguous Gate Entry
Video: [clips/03_ambiguous_gate_entry.mp4](clips/03_ambiguous_gate_entry.mp4) — 35초

gate 주변 행동 → 바라보기/방향 전환 → 재접근 → gate entry를 관찰합니다.
**authorization unknown / intent unknown**: 출입 권한과 의도는 알 수 없습니다.
실제 진입은 보이지만 AI가 권한이나 의도를 과도하게 단정하지 않는지 평가합니다.

## Scenario 04 — Attention Ranking
- CAM A → [clips/01_swoon_fall.mp4](clips/01_swoon_fall.mp4)
- CAM B → [clips/04_fight.mp4](clips/04_fight.mp4) — 35초, physical conflict
- CAM C → [clips/02_clear_wall_crossing.mp4](clips/02_clear_wall_crossing.mp4)

세 Alert가 동시에 발생했다고 가정할 때 관제 우선순위를 평가합니다.
Project-defined human reference: **CAM A > CAM B > CAM C**

This ranking is a 477 project-defined human reference, not AI Hub ground truth.
기존 clip을 재사용하며 Ranking용 영상 복사본은 추가하지 않습니다.

## Scenario 05 — Multi-camera Reasoning / Fight
- CAM A / Condition A → [clips/05_multiview_fight_cam_a.mp4](clips/05_multiview_fight_cam_a.mp4) — 약 30.633초
- CAM B / Condition B → [clips/06_multiview_fight_cam_b.mp4](clips/06_multiview_fight_cam_b.mp4) — 약 31.833초
- Condition AB → both videos (A+B)

두 영상은 동일 사건의 서로 다른 view입니다. 한 view의 가림을 다른 시점이 보완하는지 평가합니다.
official precise frame synchronization is not provided.
핵심 비교는 **AB vs best single view**입니다. CAM B도 강한 view이므로
`AB > A`만으로 multi-view 성능 향상을 주장할 수 없습니다.

## 사용 범위와 무결성
이 패키지는 사람이 보는 공유용입니다. **TEAM SHARE ≠ MODEL INPUT**.
descriptive filename을 AI 실험 입력에 사용하지 마세요. P0~P4 실험은 프로젝트의
`benchmark_v1/public_manifest.json`, `benchmark_v1/model_input/`,
`benchmark_v1/scripts/load_model_input.py`를 사용합니다.

정답·annotation이 필요한 팀원은 프로젝트 관리자에게 별도 접근을 요청하세요.
프로젝트 내부 경로는 `benchmark_v1/private_ground_truth/` 및 원본 데이터 경로이며,
이 공유 패키지에는 정답·annotation·점수·contact sheet·lock·source ZIP이 없습니다.
`CHECKSUMS.sha256`은 공유 영상 6개의 SHA256입니다. 모든 값은 frozen source와 일치합니다.
