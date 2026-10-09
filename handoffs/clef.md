# 05 Clef — BLOCKED

05 프롬프트 직접 읽음. 실제 `/root/stage05_clef` (model_engineer TOML) 순차 수행,
담당 clef_direct.py/helpers/tests/models/test_clef*.py. 변경 파일 없음.
Clef의 exact product/provider/공식API URL/model/modality/access가 미식별이다.
.env 및 CLEF_API_KEY/CLEF_MODEL 미설정. 실제 영상도 없음.

제품/API를 추정해 구현하거나 mock으로 real slot을 대체하지 않았다.
실제 clef_direct는 UnconfiguredAdapter이며 SDK/endpoint/API call 없음.
worker focused `python -m pytest -q tests/models/test_execution.py -k clef`:
2 passed/12 deselected/기존경고1. 실제 get_adapter→execute→decide probe:
nonmock/uncertain/null axes/review/provider_error/null risk/schema1.1 PASS.
초기 probe의 존재하지 않는 risk_score 속성 오기는 risk로 수정 후 PASS.

필요 정보: 제품·제공사, 공식 API 문서 링크, 모델 ID, 지원 입력 방식,
계정/모델 접근 여부와 credential 설정 위치(값을 보고서에 넣지 않음), 실제 MP4/JSON.
이미지/비디오 지원 또는 features-only를 추정하지 않는다. 독립06은 계속할 수 있다.

MAIN: `.venv/Scripts/python.exe -m pytest -q`188 passed, 기존경고1;
`python scripts/check_contracts.py`match. 실제 `/root/stage05_reviewer` 차단 판정 검토 중.

`/root/stage05_reviewer`: blocked 처리 PASS, 독립clef focused2/hash match 및
UnconfiguredAdapter→execute→decide nonmock/null/review 확인. 실제 모델 승인 없음.
