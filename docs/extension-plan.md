# 확장 순서와 실패 지점

1. 입력 ingestion: 고정 sampling + 중립 media resolver + per-camera 시간 정렬·track cache·reset,
   candidate_id/sample_id 안정화, 후보 누락 측정. 현재 live ingestion과 모델→repo 자동 연결은 미구현.
2. 실제 local CV: worker로 decode/tracking/pose 실행, 크기 제한, backpressure, worker cancellation.
3. provider adapter: 실제 공식 문서/credential 검증, modality capabilities, structured output, quota, retry budget.
4. 실제 서비스 통합: MAIN이 execute→policy→Incident/Suppressed→repository→snapshot 연결.
   현재 make_incident는 이 seam을 제공하며 데모는 별도의 synthetic 상태를 사용합니다.
5. persistence: repository protocol을 확장하여 DB transaction으로 incident/audit/idempotency/outbox 저장.
   memory와 유사하게 보이기만 하는 SQL 클래스가 아니라 원자성 테스트를 먼저 수행하세요.
6. multi-worker/477 카메라: 공유 broker/outbox, durable states, reconnect snapshots, bounded task queues,
   전체 snapshot 크기·fanout 부하 측정 후 delta+snapshot recovery로 전환. worker 수 증가만으로 해결되지 않습니다.
7. 권한/운영: operator identity, 읽기·ACK·handover authorization, audit retention, demo 분리,
   secrets/log redaction, TLS/인증 후 외부 노출. 현재는 localhost 개발용입니다.
8. multi-camera merge: 시간·공간·관측 association service + merge/split audit, primary/related view 의미 정의.
   얼굴 인식은 추가하지 않습니다. related_cams 필드 존재가 병합 구현을 뜻하지 않습니다.
9. router→VLM: 후보가 놓친 critical까지 포함한 recall, 호출 절감, 전체 latency/cost 검증 후 추가.

실제 CV dependencies는 optional extras로 추가하고 model_engineer가 pyproject를 동시에 수정하지 않습니다.
검증 환경 재현 파일 requirements-tested.txt는 이 키트 테스트 환경의 resolved 버전 기록이며 모든 OS용 lock은 아닙니다.
