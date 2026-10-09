# 백엔드 벤치마크 제거 — 2026-10-09

사용자 요청에 따라 백엔드와 별개인 벤치마크 패키지 및 기능을 제거했습니다.

- 삭제: new_477_piprline, 477_modeling_benchmark_v1, final_candidates_v1.
- 삭제: 벤치마크 전용 어댑터/worker, annotation_detector, 평가기, budget, 스키마,
  CLI, 전용 테스트, 실험 문서 및 보고서.
- 변경: execution/registry의 벤치마크 전용 진입점 제거, benchmark extra 제거,
  계약 동결 목록 및 실행 안내 갱신.
- 보존: HTTP/WS API, scripted demo, media resolver/ingestion, local_cv 및 mocks,
  일반 데이터 검증/평가 유틸리티, Git 이력, 다른 프로젝트 폴더.
- 삭제 전: 전체 파일 합계 6,810,326,734 bytes.
- 삭제 직후: 전체 파일 합계 2,106,005,913 bytes. 약 4.38 GiB 확보.
- 잔여 대부분은 .git의 과거 파일 이력입니다. 이력 재작성은 수행하지 않았습니다.

## 검증

- Python 3.12.6 임시 환경에서 `.[dev,local-cv]` 설치 후 전체 회귀 테스트:
  `python -B -m pytest -q -p no:cacheprovider --basetemp=D:\projects\477-backend\.cleanup-verified-tmp`
  → 231 passed, 1 warning, 19.82초.
- 기존 FFmpeg/FFprobe 경로를 테스트 프로세스 PATH에 지정했습니다.
- Windows 샌드박스의 tmp_path 생성 오류 및 asyncio 초기화 정지를 확인한 뒤,
  작업 폴더 내부 basetemp와 일반 실행 환경에서 검증했습니다.
- `python -B scripts/check_contracts.py` → Frozen contracts match.
- `git -c core.fsmonitor=false diff --check` → PASS.
- app/tests/scripts/pyproject에서 삭제한 벤치마크 모듈 참조 없음.
- 임시 가상환경·다운로드 캐시·테스트 산출물은 검증 후 삭제합니다.
- 실제 provider 호출, Git commit/push 및 이력 재작성 없음.
