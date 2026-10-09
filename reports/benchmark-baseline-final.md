# 477 실제 baseline 결과 — 2026-10-08

**실제 실행과 분석은 완료했으나, 사전 출력·근거 합격 기준은 미달이다.**
VLM 단독 21회와 CV→Clef→VLM 21회를 실행했다. JSON 구조는 모두 맞았지만
13개 출력의 근거 시각이 제공된 프레임과 어긋났다. Clef 6건은 로컬 입력
상한에서 차단돼 호출하지 못했으며, 해당 건은 VLM·사람 검토로 전달했다.
정답이 없어 사건 정확도·누락·오경보·근거 의미 정확성은 측정하지 않았다.

## 핵심 평가표

| 항목 | VLM 단독 | CV→Clef→VLM |
|---|---:|---:|
| 계획 / 실제 평가 시도 | 21 / 21 | 21 / 21 |
| VLM 실제 API 응답 | 21 / 21 | 21 / 21 |
| JSON prediction schema 통과 | 21 / 21 (100%) | 21 / 21 (100%) |
| 원본 schema·컨텍스트·입력 프레임 근거 모두 통과 | 16 / 21 (76.2%) | 13 / 21 (61.9%) |
| CV·Clef·VLM 모두 정상이고 최종 계약까지 통과 | 해당 없음 | **9 / 21 (42.9%)** |
| 전체 응답시간 p50 / p95 | 16.42 / 22.46초 | 68.22 / 78.45초 |
| 120초 이내 | 21 / 21 | 21 / 21 |
| 실제 API usage의 peak 가격 환산 추정 | $0.161795712 | $0.099961824 |
| 사건 정확도·누락·오경보·의미 근거 정확성 | 미측정 | 미측정 |

파이프라인 13개 계약 통과 결과 중 4개는 Clef 실패 후 VLM 대체 경로의
결과다. 이를 세 모델 전체 성공으로 세지 않았다. Clef까지 실제 호출한
15건의 지연만 보면 p50 69.97초, p95 81.63초다. 속도표의 전체 21건에는
Clef 호출 전 차단 6건이 포함된다. `summary.json`의 `status=incomplete`도 유지했다.

| ITEM | 단독 근거 계약 통과 | 파이프라인 출력 계약 통과 | Clef 실제 호출 | 전 단계·최종 계약 통과 |
|---|---:|---:|---:|---:|
| ITEM_01 | 0/3 | 0/3 | 3/3 | 0/3 |
| ITEM_02 | 2/3 | 0/3 | 3/3 | 0/3 |
| ITEM_03 | 3/3 | 1/3 | 0/3 | 0/3 |
| ITEM_04 | 2/3 | 3/3 | 3/3 | 3/3 |
| ITEM_05 | 3/3 | 3/3 | 3/3 | 3/3 |
| ITEM_06 | 3/3 | 3/3 | 0/3 | 0/3 |
| ITEM_07 | 3/3 | 3/3 | 3/3 | 3/3 |

## 실제 실행 조건과 비용

6개 고유 MP4를 재사용하는 7 ITEM의 소규모 데모 평가다. 조건별 3회,
매번 원본 loader의 64장을 다시 읽었다. 서로 대응하는 두 조건의 입력
digest·fingerprint를 비교하며, VLM에는 CV 정보나 정답을 전달하지 않았다.
추가 프레임·crop·contact sheet를 모델에 보내지 않았다. 벤치마크,
final_candidates_v1, data, media의 전후 파일 SHA256·크기·목록은 일치했다.

- CV: yolo26s.pt, ByteTrack, yolo26s-pose.pt, CPU, imgsz 960, conf 0.10.
  Ultralytics 8.4.174, torch 2.9.1+cpu. 모든 21회에 동일 64장을 탐지·자세
  분석했다. 매 실행 새 작업 프로세스이므로 모델 최초 로드를 포함한다.
- VLM: 요청·응답 ID deepseek-flash, API base https://api.deepseek.com,
  thinking disabled, max_tokens 8192, temperature 0, 고정 JPEG quality 80.
  64장 모두 1920×1080이며 서버의 자동 리사이즈는 별도 기록했다.
- Clef: @cf/cloudflare/clef, selector clef. 64장의 CV 파생 상태를 structured
  state로 전달하며 64장 이미지를 전달한 모델로 취급하지 않았다.
- 반복의 첫 호출 표시와 실제 cache usage를 저장했다. API 내부 checkpoint,
  GPU/VRAM, 양자화 및 공급자 cold start는 미확인이다.

suite는 DeepSeek 42회, Clef 15회 실제 호출했다. 별도 접근 점검 각각 1회를
포함해 유료 요청 ledger는 총 **59회: DeepSeek 43회, Clef 16회**다.
예약액 $3.45235968은 실패 가능 청구를 포함하는 가드이며 실제 지출이 아니다.
전체 usage 기반 보수적 peak 환산은 **$0.286777356**이다. 그중 DeepSeek
$0.214396956, Clef $0.0723804다. 별도 접근 점검 $0.02501982는 suite 통계에서 제외했다.

DeepSeek 계정 조회 잔액은 suite 전 USD 3.78, 후 USD 3.69였다. 표시 잔액
차이 $0.09는 반올림·반영 지연·동시 계정 사용 가능성이 있어 요청별 청구서
비용으로 확정하지 않는다. Cloudflare 청구서도 확인하지 못해 **실제 청구액은
미확인**으로 남긴다. 사용 가격은 [DeepSeek 공식 가격표](https://api-docs.deepseek.com/quick_start/pricing/),
[Clef 공식 모델 문서](https://developers.cloudflare.com/workers-ai/models/clef/)에 근거한다.

실제 계정 조회는 [DeepSeek balance API](https://api-docs.deepseek.com/api/get-user-balance/)다.
실제 비용·peak 환산·off-peak 추정은 결과 metadata에서 구분했다.
파이프라인 비용이 낮게 나온 데는 단독 호출 뒤 실행한 공급자 캐시와
Clef 미호출 6건이 영향을 준다. **라우팅이 비용을 절감했다고 해석하지 않는다.**
원 summary의 파이프라인 총 비용은 미호출 단계의 usage가 없어 null이다.
위 표는 실제 호출된 모든 단계의 usage를 합산해 ledger와 대조한 추정치다.

## 시간과 메모리

| 실제 측정 구간 | 중앙값 |
|---|---:|
| canonical decode·원본 로더 준비 | 약 3.81초 |
| CV 전체 모델 호출 경계 | 47.60초 |
| CV 라이브러리 import / 모델 load | 4.92 / 0.46초 |
| CV 탐지 / 추적 / 자세 | 19.52 / 0.17 / 17.57초 |
| Clef 정상 호출 15건 전체 / HTTP 구간 | 4.83 / 3.88초 |
| VLM JPEG 등 전처리 / HTTP 구간 | 1.86 / 8.66초 |

전체 응답시간은 decode 시작부터 모델·계약 검사까지며 파일 저장 시간은
별도 기록했다. 각 구간 중앙값의 합은 전체 중앙값과 같지 않을 수 있다.
42개 실제 측정 지연 합계는 약 29.95분이다.
주 프로세스 샘플링 최대 RSS는 951,525,376 bytes, CV 작업 프로세스 OS 최대
RSS는 647,053,312 bytes였다. 서로 다른 프로세스의 최댓값이므로 합해서
전체 피크라고 부르지 않는다. API 서버 VRAM은 미측정이다.
실제 산점도: `runs/baseline-final/latency.png`.

## 실패 원인과 해석

**확인된 VLM 근거 시각 실패: 13건.** 예를 들어 ITEM_01에서 출력 34.9초는
가장 가까운 실제 입력 34.9666667초와 0.0666667초 차이여서 사전 기준
±1/30초를 넘었다. ITEM_02도 같은 끝 시각, ITEM_03은 출력 31.0초와 입력
31.0666667초, ITEM_04는 20.9초와 20.9666667초가 어긋났다. 클라이언트는
실제 시각을 6자리 소수로 전달했다. 모델이 시각을 낮은 정밀도로 출력한
문제가 확인됐으며 결과를 가까운 프레임으로 고쳐서 통과시키지 않았다.
장면 해석 자체가 오답인지는 정답이 없어 확정할 수 없다.

**확인된 Clef 변환 경계 실패: ITEM_03/06 각각 3건.** 실제 직렬화 길이는
85,573 / 67,683 UTF-8 bytes로 로컬 보수적 token 상한 65,536 bytes를 넘었다.
이것은 Cloudflare가 거절한 HTTP 응답이 아니다. 코드가 호출 전에 차단해
API를 실행하지 않았으며, 두 샘플의 CV→Clef 단계 변환 문제로 분류한다.
VLM에는 동일 64장을 전달했고 이 상위 단계 문제를 VLM 책임으로 돌리지 않았다.

**CV의 객체·추적 품질: 실제 관측 신호는 있지만 정확도는 불확실.**
첫 반복 ITEM_03은 탐지 1,102개 중 untracked 365개, ITEM_05는 206개 중
103개였다. ITEM_02의 38/64프레임에서 사람 탐지가 없었지만 사람의 실제
존재 여부 정답이 없어 탐지 누락률이라고 부르지 않는다. 희소한 프레임의
ByteTrack Kalman step은 샘플 단위이고 연속 영상 추적과 같지 않다. 관측
범위·짧은 track·posture 후보는 확인했으나 ID switch·탐지 FN은 미측정이다.

**구역·시간·자세 한계.** 침입 구역 polygon이 없어 침입을 확정하지 못한다.
15초 화면 체류는 배회 후보이며 허가 여부·제한 구역 체류 판정이 아니다.
낮은 자세는 쓰러짐 진단이 아니다. CV는 사건 분류기·위험축을 측정하지 않아
위험축 null, backend risk UNKNOWN, 사람 검토로 출력한다.

**Clef 라우팅.** 정상 응답 15건 중 제안은 invoke_vlm 3건, human_review
12건이었다. no_action 생략 제안은 없었다. 불완전 CV 상태와 실패 6건을
포함해 실제 21건 모두 VLM으로 전달했으므로 라우팅 단계에서 제외한 입력
샘플은 0건이다. 정답 사건 누락률 자체는 측정 불가다. 현재 구성의 Clef gate는
VLM 호출 수를 줄이지 못하고 지연·비용을 추가한다.

**공통 사건 enum 호환 한계.** 동결 benchmark schema는 자유로운 event_type
문자열을 허용하지만 기존 공통 계약은 6종 enum이다. 실제 자유형 문자열을
임의 의미 추정으로 바꾸지 않아 VLM 공통 assessment 52개 모두 uncertain /
사람 검토가 됐다(attention은 카메라별 결과 포함). 원래 사건 표현은 보존했다.
정규화 부재와 프레임 근거 오류를 구분해야 하며, 공통 JSON이 유효하다는
이유만으로 사건 판단이 완료됐다고 볼 수 없다.

## 개선 우선순위와 필요한 정보

1. Clef 전처리: 64프레임 식별자·시간·관측 총계는 유지하면서 CV 파생 상태의
   중복·장황한 표기를 줄이고 실제 token budget을 검증한다. 상한 제거·조용한
   truncate 대신 별도 변환 버전 실험으로 원 baseline과 비교한다.
2. VLM 근거: 입력 프레임 ID/정확한 시각을 강제할 수 있는 공급자 기능과
   변환을 검증한다. 원 prompt/schema 변경이 필요하면 MAIN이 별도 계약
   변경으로 기록하고 재동결한다. 현재 실패를 후처리로 고치지 않는다.
3. 공통 사건 ontology: free-form label과 6종 enum 사이의 명시적·버전 관리
   매핑을 MAIN이 검토한다. 벽을 넘었다는 사실로 무단 침입을 단정하지 않는다.
4. CV 규칙: 카메라별 제한 구역 polygon, 출입 허가 기준, 체류 시간·이동 규칙이
   필요하다. 추적 ID와 자세 후보를 실제 영상·주석에 대조한다. 더 촘촘한
   입력·crop·GPU/warm 실행은 common64 결과와 별도 실험으로 둔다.
5. 평가 정답: sample↔event label, 정상/음성 영상, 기준 사건 시각·근거 프레임,
   필요한 위험축 rubric과 camera/source/scenario group이 필요하다. 현재
   6개 영상 결과를 전체 CCTV 성능으로 일반화할 수 없다.

기준은 결과를 보고 유리하게 변경하지 않았다. schema+근거 100% 목표는 FAIL,
전체 120초 목표·입력 보존·$5 호출 예산 가드는 PASS다. 정확도는 N/A다.

## 재현과 산출물

실행 가이드: `docs/benchmark-baseline-run.md`.

```powershell
.\.venv-benchmark\Scripts\python.exe -B scripts\run_benchmark_baseline.py --mode suite --repeats 3 --output runs/new-run
.\.venv-benchmark\Scripts\python.exe -B scripts\analyze_benchmark_baseline.py --run runs/new-run
```

기존 ledger를 유지하므로 추가 호출도 남은 $5 한도에서만 진행된다. 결과
폴더 덮어쓰기는 금지하며 원본 benchmark/submissions 폴더를 수정하지 않는다.
현재 예약액 $3.45235968이 유지되므로 같은 전체 suite를 다시 실행하면
남은 예약 예산에서 중단될 수 있다. 재실행을 위해 ledger를 삭제하지 않는다.
이번 실제 실행 영역은 독립 benchmark CLI다. 기존 ASGI의 일반 adapter
설정과 신규 benchmark factory를 구분하며 서비스 연결은 별도 통합 항목이다.

`runs/baseline-final`에 raw 모델 응답, 42개 diagnostics·common 결과,
29개 유효 frozen submissions, evaluation.csv, failures.json, analysis.json,
raw-label-comparison.csv, latency.png, execution_metadata.json과 전후 보호
snapshot이 있다. 29개 제출 중 Clef 대체 경로 4개는 전체 단계 성공이 아니다.
실제 요청 budget ledger는 `runs/477-paid-budget.json`이다. 키 값은 저장하지 않았다.

순차 담당 에이전트: /root/baseline_run_preflight(explorer),
/root/baseline_yolo26_bytetrack(model_engineer),
/root/baseline_clef_adapter(model_engineer),
/root/baseline_deepseek_adapter(model_engineer),
/root/baseline_evaluation_runner(evaluation_engineer),
/root/baseline_execution_reviewer(reviewer). 공유 계약·통합·실제 실행·문서는 MAIN이 담당했다.
실행 전 MAIN 전체 326 tests PASS, 계약 PASS, 독립 reviewer 준비 상태 PASS.
최종 MAIN 검증도 전체326 tests PASS(기존 warning1), 계약 PASS다.
독립 reviewer의 실제 결과·보고서 정합성 검토는 PASS이며 모델 성능 합격은
아니다. reviewer는 42개 시도·59개 요청·비용·21쌍 동일 입력·보호 snapshot을
별도로 대조했고 생성 파일209개에서 인증 값 노출0건을 확인했다.
작업 상태와 미완료 항목은 TASKS.md, handoffs/benchmark-baseline-results.md에 기록했다.
