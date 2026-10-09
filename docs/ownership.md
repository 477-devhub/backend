# 파일 담당과 충돌 예방

MAIN은 별도 TOML 에이전트가 아니라 사용자가 대화 중인 주 에이전트입니다.

| 담당 | 수정 가능 | 수정 금지 |
|---|---|---|
| MAIN | schemas, models/base·execution·registry·media, config.py, main.py, repositories/protocol.py, pyproject, docs, fixtures, scripts, prompts, tests/contracts·integration, .codex, TASKS | 다른 writer 작업 중 해당 영역 |
| explorer | 없음: 읽기만 | 모든 파일 |
| reviewer | 없음: 읽기만 | 모든 파일 |
| model_engineer | app/models/adapters/**, tests/models/** | eval, API, 공통 파일 |
| evaluation_engineer | app/eval/**, tests/eval/** | adapters, API, 공통 파일 |
| backend_engineer | app/api/**, app/services/**, app/repositories/memory.py, tests/backend/** | main/config/protocol/schema/model/eval |

코드에 존재하는 공통 실행기는 MAIN 소유입니다. backend가 실패 처리를 다시 만들거나 evaluator가 다른 래퍼를 만들지 않습니다.
writer가 새 의존성/등록/스키마 변경이 필요하면 handoffs/template.md 형식으로 요청하고 MAIN이 순차 반영합니다.

기본은 writer 한 명씩입니다. 빠르게 하려면 계약 동결 후 backend + model을 두 명만 병렬로 실행할 수 있습니다.
model + eval도 경로가 분리됐지만 동시에 세 명을 시작하지 마세요. 통합 비용을 먼저 확인하세요.
같은 model_engineer 두 명에게 adapters/** 전체를 동시에 주지 않습니다. 반드시 개별 파일로 범위를 더 좁혀야 합니다.

서로 다른 대화도 같은 작업 폴더를 볼 수 있습니다. instructions는 권한 강제 장치가 아닙니다.
MAIN이 diff를 검토하고 tests와 계약 해시를 확인해야 합니다. 별도 worktree를 쓰더라도 공통 스키마 충돌은 남습니다.
실제 팀은 role1 저장소를 공유하고 frontend와 dataset 팀은 별도 저장소/담당 경로에서 작업하세요.
