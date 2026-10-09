# 06 VLM — BLOCKED

06 파일 직접 읽음. 실제 `/root/stage06_vlm` (model_engineer TOML), 담당
general_vlm.py/helpers/tests/models/test_vlm*.py. 수정 없음.
제공사·모델·SDK·credential·지원 modality/structured output 미확인이다.
.env 없음, VLM_MODEL/OPENAI_API_KEY 미설정, 실제 MP4/asset-map 없음.
OpenAI 또는 특정 local VLM을 임의로 선정하지 않았다.

worker 실제검사:
`python -m pytest -q tests/models/test_execution.py tests/contracts/test_execution_validation.py
tests/contracts/test_schema_v11.py tests/contracts/test_registry_resolver.py`:39 passed/기존경고1.
general_vlm registry→execute: schema1.1/uncertain/confidence0/axesnull/review/
general_vlm/unavailable/nonmock/provider_error. 계약hash match.
실제 API/영상 판단/비용 측정은 미실행이다. 실패는 사람 검토로 보낸다.

필요: 정확한 제공사 공식 문서 URL, 모델ID, SDK, 영상/이미지와 structured-output 지원,
계정/모델 권한과 credential 설정 위치(비밀값 공유 불필요), 실제 MP4와 asset-map.
Clef와 같은 window/sampling의 modality/cost 비교는 양쪽 실제 지원 확인 뒤 가능하다.
MAIN 전체188 passed/기존경고1, contracts match. reviewer 차단 판정 검토 대기.

`/root/stage06_reviewer` 차단 처리PASS: 독립focused39/hash match 및 실제 안전probe확인.
실제VLM/영상/비용/공정성 승인은BLOCK. 최초 probe 경로 오기는 수정 후 PASS.
