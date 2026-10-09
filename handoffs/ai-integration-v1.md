# AI backend integration v1 — 2026-10-09

Scope: 현재 Cheap CV/P1/P4 이식, registered MP4 분석 job, 기존 사건/WS/근거/ACK/복구 연결.
고도화/모델 튜닝/frozen Test 재평가/배포는 수행하지 않았다.

검증:
- `.venv/Scripts/python.exe -m pytest -q --basetemp=outputs/pytest-ai-delivery5`: **264 passed**, 25.12s.
- `.venv/Scripts/python.exe scripts/check_contracts.py`: Frozen contracts match.
- compileall 및 diff whitespace 검사 성공.
- 독립 reviewer 최초 BLOCK4건을 수정한 뒤 재검토 **PASS**; independent focused28passed.
- 실제 영상 offline: source asset_01의0~10초 →64장 RGB hash 일치 →CV state 생성,2tracks.
  outputs/cascade-offline-smoke.json. API 호출0. 원본 benchmark 전체에 대한 성능/동일성 평가가 아니다.
- 저장된 기존 CV state의 compact 변환이 기존 compact와 일치함을 모델 담당자가 확인.

수정한 리뷰 항목: 실행한 adapter raw/normalized 진단 보존; failed/schemafailed 응답의 usage/retry/requestID 보존;
분석 원본 영상과 동일한 등록 파일만 admission; ported artifacts/가중치 hash 고정.
복구된 P1 정상 제외에서도 실제 원본clip/window를 제공하며 frame citation은 생성하지 않는다.

실제 유료 smoke: 사용자 승인 $2, asset_01의0~10초 64장/CV관측의 api.openai.com 전송,
P1 gpt-6-luna/P4 gpt-6.1-sol 각각1회. 결과는 outputs/ai-live-smoke/report.json과 attempt.json.
smoke 실행은 해당 output 재사용 시 반복 추론을 거절한다.

실제 호출 결과 **PASS**: P1/P4각1회, 예상 API비용 $0.4076997(usage 기준),
collapse/낙상 의심, risk68, 사람검토. 근거6장 HTTP200, 원본clip URL 연결,
ACK200 및 post-ACK active_count0. CPU cold 실행 전처리67.02s/CV76.30s/P1 6.49s/P4 129.10s.
이번 smoke map latency는 미측정null; 이후 실행은 map시간도 측정하도록 수정했다.
동일 영상 재추론하지 않았으며 성능 정확도/운영 처리량을 입증하는 평가가 아니다.

실행/프론트 안내: docs/ai-integration.md. 분석 요청은202 job, 진행은GET;
사건/근거/ACK/restore/WS는 기존 API. 분석 실제 비용·지연은 /api/analysis/stats.

한계: 단일 메모리 worker, 단계마다 CV cold-load, 등록 영상 파일 입력. 영구DB·인증·live input·
자동 다중카메라 사건 병합·477대 throughput은 구현 범위 밖이다.
원본 모델 저장소 변경/새 가중치 다운로드/자동 배포/팀 외부 메시지 전송 없음.
