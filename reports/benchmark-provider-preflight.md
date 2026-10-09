# 실제 공급자·전처리 사전 점검 — 2026-10-08

이 점검은 최종 suite 통계와 별도다. API는 실제 canonical ITEM_01 영상
64장과 그 프레임에서 CV가 추출한 상태를 사용했다. 정답은 사용하지 않았다.

| 항목 | 실제 측정 |
|---|---:|
| CV decode | 3,508 ms |
| CV 실행(모델 import/load 포함) | 49,164 ms |
| CV 탐지 / 추적 / 자세 | 20,669 / 117 / 17,872 ms |
| CV 작업 프로세스 최대 메모리 | 643,706,880 bytes |
| DeepSeek HTTP / 요청 전체 시간 | 200 / 14,116 ms |
| DeepSeek 입력 / 출력 token | 64,793 / 806 |
| Clef HTTP / 요청 전체 시간 | 200 / 17,469 ms |
| Clef 입력 token | 19,228 |
| 두 요청 usage 기반 추정 비용 | $0.02501982 |
| 실제 청구서 비용 | 미확인 |
| 보호 폴더 변경 | 0 |

DeepSeek 조회 잔액은 전후 USD 3.79로 같았다. 소수점 반올림·지연 및 다른
계정 작업 가능성 때문에 이를 두 요청의 실제 청구액 0달러라고 해석하지 않는다.
Clef의 원본 선택은 invoke_vlm, 사건 noul=0.6933이었다. CV 정보 불완전성
때문에 안전 라우팅도 VLM/사람 검토였다. 사건 판단의 정답 여부는 미평가다.

## API 요청 크기에 맞춘 변환 설정

동일 64장·원본 1920×1080·동결 prompt/schema를 유지해 무료 로컬 직렬화만
검사했다. JPEG quality 90은 ITEM_02/03/05에서 공급자 48MiB 요청 상한을
넘었다. 최종 suite 전에 모든 VLM 조건의 고정 변환을 quality 80으로 정한다.
이는 요청 호환성 수정이며 평가 합격 기준이나 정답에 따른 튜닝이 아니다.
모델 담당 에이전트 수정·테스트와 MAIN 검증 후 실행한다.

| ITEM | quality 80 요청 bytes | 상한 검사 |
|---|---:|---|
| ITEM_01 | 28,980,095 | PASS |
| ITEM_02 | 41,218,971 | PASS |
| ITEM_03 | 35,932,607 | PASS |
| ITEM_04 | 25,447,525 | PASS |
| ITEM_05 | 40,663,288 | PASS |
| ITEM_06 | 27,738,737 | PASS |
| ITEM_07 | 33,807,010 | PASS |

64개의 source RGB SHA256과 전송 JPEG SHA256, 압축 시간·품질·바이트 크기를
각 호출 metadata에 기록한다. 해상도 변경·crop·프레임 제외는 없다.

원본: `runs/cv-diagnostic/ITEM_01.json`,
`runs/provider-access-check/results.json`, `runs/477-paid-budget.json`.
