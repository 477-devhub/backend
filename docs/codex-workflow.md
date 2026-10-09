# 작업 운영

현재 공식 custom agent 문서(2026-10-06 확인):
https://developers.openai.com/codex/subagents
https://developers.openai.com/codex/config-reference
원본 standalone .codex/agents/*.toml 형식과 [agents] global 키는 유효했습니다.
최신 공식 문서의 name/description/developer_instructions, sandbox_mode 형식을 유지했습니다.
사용자 PC의 Codex 버전은 확인하지 않았습니다. `codex --version`을 먼저 확인하고 로딩 여부를 점검하세요.
상위 ~/.codex 설정/조직 정책/현재 account model access에 따라 실제 실행이 달라집니다.
모델 pin은 제거하여 현재 계정의 선택 모델을 상속합니다. 임의로 GPT 모델 접근 가능성을 단정하지 않습니다.

기본: 하나의 Codex 대화에서 MAIN이 순서대로 작업을 배정합니다.
explorer/reviewer는 동시 읽기 가능. writer는 기본 순차입니다.
지원하는 환경에서는 이름을 지정해 custom agent를 호출하고, 그 기능이 없는 Kiro/구형 CLI에서는
MAIN이 같은 역할과 허용 파일 규칙을 읽고 단독으로 수행합니다. TOML을 Kiro 네이티브 설정이라고 간주하지 않습니다.

순서: audit → 계약/프론트 합의 → 데모 통합 → 실제 provider/ingestion 확인 → local CV → Clef → VLM
→ validation/evaluator → 최종 통합 리뷰 → frozen test → 필요할 때 router.

prompts/ 파일을 숫자순으로 하나씩 사용합니다. 각 단계가 테스트·리뷰 PASS를 얻기 전 다음 의존 단계로 넘어가지 않습니다.
real provider 접근이 막힌 B만 BLOCKED로 남기고 A/C 및 데이터 작업은 계속할 수 있습니다.
프론트/데이터 팀은 처음부터 각자의 담당 작업을 시작할 수 있지만, API/manifest 계약 확인은 먼저 해야 합니다.

종료 보고 형식: 변경 파일 → 실행 명령/실제 결과 → 실제/mock/미구현 → blocker → 다음 단계.
MAIN이 전체 tests와 계약 해시를 검사하고 Git commit을 남깁니다. writer는 commit하지 않습니다.
환경 차이나 계약 변경 때문에 테스트가 실패하면 이를 고치고 결과를 다시 기록합니다.
