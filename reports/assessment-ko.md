# 477 하네스 검토와 수정 결과

검토일 2026-10-06. 범위는 사용자 역할1(모델 입출력·독립 비교·백엔드)입니다.
검토 자료: 첨부 AGENTS/README/TASKS/pyproject/.env.example/.gitignore, 첨부 AI 답변,
이전 477-role1-backend-agent-kit.zip의 실제 코드, Figma API 주석 페이지 60:2.
프론트 앱 소스·AI Hub 영상·실제 provider 키·사용자 PC Codex 설치는 제공되지 않아 검증하지 않았습니다.

## 평가

**설계 방향은 타당하지만, 원본은 계약·실행 실패·통합 검증이 부족한 시작용 뼈대였습니다.**
독립 adapter, risk/confidence 분리, read-only reviewer, schema freeze와 manifest 도입은 유지할 가치가 있습니다.
원본의 4개 테스트는 통과하지만 mock 출력 형식과 위험식만 검사했습니다.
실제 모델·실제 상태 전송·안전한 평가 파이프라인이 완성됐다고 해석하면 안 됩니다.

| 항목 | 원본 평가 | v2 조치 | 남은 한계 |
|---|---|---|---|
| 에이전트 구성 | MAIN 통합 역할 암묵적, model과 eval 한 담당 | eval 별도 role, MAIN 책임/파일 명확화 | instruction만으로 쓰기 권한을 강제하지 못함 |
| 모델 비교 | 3 이름이 전부 mock, 실패 경로 없음 | mock_* 분리, real slots 명시 실패, execution wrapper | 실제 모델 미구현 |
| 계약 | extra 허용/시간·evidence 검사 부족 | typed contracts, extra 금지, NaN·창·ref 검증 | temporal dict 의미 검토는 필요 |
| API/WS | ACK 미변경, WS 최초 1회만, demo 무상태 | ACK/audit/idempotency, push/snapshot/reconnect, 6 scenario | durable DB/auth/live ingestion 없음 |
| 평가·데이터 | 문서만, 동일 source 분할 검사 없음 | manifest validator, batch metrics, frozen hash guard | 실제 영상/near duplicates/캐시 자동 주입 없음 |
| 확장 | global memory, 여러 worker 불일치 | app별 store/protocol, one-worker 제한 명시 | DB/outbox/broker와 부하 검증 후 확장 |
| 패키징 | build-system/package 발견 설정 없음 | setuptools 명시 + app package discovery | tested env 외 OS는 추가 검증 |

완성도의 의미를 '개발 시작·통합 가능한 하네스'와 '실제 CCTV AI 서비스'로 나누었습니다.
v2는 전자를 보완했습니다. 후자는 실제 모델·데이터·프론트 통합·운영 저장소 작업이 남았습니다.
숫자 점수보다 위의 작동/미구현 경계로 판단하는 것이 정확합니다.

## 주요 문제와 수정

1. **shared schema freeze만으로 충돌 예방 부족.** registry.py/main.py/config/pyproject/fixtures/tests도
   공유 변경점입니다. MAIN 단독 소유로 바꾸고 model/backend/eval 테스트 경로를 분리했습니다.
2. **실제 독립 비교와 feature 기반 cascade 혼동.** B/C가 local CV features를 받으면 전체 시스템은
   CV→B/C입니다. 동일 JSON 형식만으로 공정성이 보장되지 않습니다. clip_ref와 trusted resolver seam,
   modality/profile/전처리 비용 기록 규칙을 추가했습니다.
3. **Clef capability 미확정.** 원 답변은 이미지를 받는 멀티모달 decision model로 단정했습니다.
   자료만으로 제품/제공사/API를 확정할 수 없습니다. provider 검증 단계와 BLOCKED 대안을 추가했습니다.
4. **실패를 정상/저위험으로 처리할 위험.** timeout/invalid JSON/ref 오류는 unknown/review로 기록합니다.
   위험 축이 없으면 null/UNKNOWN으로 유지해 점수를 지어내지 않습니다. 프론트 계약 확장이 필요합니다.
5. **Figma 산식과 예시 수치 모순.** risk=94와 (.9,.95,.8,.85)는 불일치하며 가중식 결과는 89입니다.
   서버 계산 기준으로 데모와 테스트를 통일했습니다. 위험도×확신도는 하지 않습니다.
6. **ACK 상태·순위·WS 누락.** 실제 변경/audit/key 재시도와 전체 snapshot을 구현했습니다.
   review 카운트는 중복 집계하지 않습니다. ACK 의미는 Figma 미정 사항이라 합의 초안으로 명시했습니다.
7. **suppression 복구 버튼 구현 경로 없음.** 추가 restore API를 만들고 unknown/review로 복구합니다.
8. **경로/라벨 누수와 그룹 분리.** opaque frame/clip refs, inference/ground-truth 분리,
   source/scenario/hash 교차 split 및 media checksum 검사로 보완했습니다. 라벨 text 의미 누수는 추가 점검이 필요합니다.
9. **평가에서 실패 삭제/0 비용 오해.** 모든 실패를 분모에 남기고 불명 비용은 null+coverage로 기록합니다.
   critical event recall과 사람에게 올라간 escalation recall을 분리했습니다.
10. **확장 실패.** memory state와 local WS는 여러 worker에서 공유되지 않습니다. 단일 worker용임을 명시하고
    transaction/outbox/broker/ingestion/worker cancellation 순서의 확장 과제를 문서화했습니다.

## 에이전트 설정 검토

현재 공식 Codex 문서에서 standalone .codex/agents/*.toml 및 [agents] global setting은 유효합니다.
원본 형식이 '무조건 잘못됐다'거나 구형 role registration을 추가해야 한다고 판단하지 않았습니다.
다만 계정에서 특정 model ID에 접근 가능한지는 별개입니다. pins를 제거해 현재 모델 선택을 상속했습니다.
MAIN + explorer/reviewer/model_engineer/evaluation_engineer/backend_engineer 구조입니다.
프로젝트 에이전트 설정이 사용자의 Codex에서 실제 로딩되는지는 단계0에서 확인해야 합니다.
Kiro 네이티브 에이전트 JSON 설정은 이 압축에 포함하지 않았습니다. 역할 prompt는 단독 순차 실행에 사용할 수 있습니다.

공식 출처(2026-10-06 확인):
https://developers.openai.com/codex/subagents
https://developers.openai.com/codex/config-reference
Figma 출처: https://www.figma.com/design/pK7WGcPjkNjP7zaAbK4c13/477?node-id=61-14&m=dev

## 지금 바로 쓰는 순서

시작하기.md의 설치 명령 → prompts/00~01 감사·계약 → 02 데모/프론트 → 03 provider·영상 준비
→ 04 Local CV → 05 Clef → 06 VLM → 07 validation → 08 통합 리뷰 → 09 frozen test.
데이터 담당자는 단계1에서 합의된 전달 규격으로 준비하고, 프론트 담당자는 단계2부터 데모 API로 연결합니다.
단계5 Clef 접근만 막혔다면 그 항목을 BLOCKED로 두고 A/C를 계속합니다.

## 구현 제한

- 실측 데이터·키·모델이 없으며 synthetic 데모는 추론 결과가 아닙니다.
- 데모 사건 일부는 화면 상태 설명용이므로 frame evidence가 비어 있습니다. 실제 모델 결과에는 유효 ref 검사가 적용됩니다.
- 라이브 영상/477대 연결, 실제 crop/bbox timeline, 지속 저장소, 외부 운영 보안은 미구현입니다.
- batch CLI와 hash guards는 개발 규약이며 전체 weight/cache/code 변경을 완전히 막는 보안 장치가 아닙니다.
- 실제 provider와 Python 3.11/Windows 환경, 사용자 Codex 로딩은 이 환경에서 검증하지 않았습니다.

검증 명령/수치와 설치 결과는 reports/verification.md에 별도 기록합니다.
