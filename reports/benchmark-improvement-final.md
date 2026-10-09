# 파이프라인 개선 결과 — 2026-10-08

입력 크기 제한의 오류와 근거 시각 표현을 수정하고 실제 CV·Clef·VLM 실험을
완료했다. 개선 후 공통64프레임 전체 파이프라인7/7이 모든 단계 실행 및 출력
검사를 통과했다. 별도 pose-off 실험에서는 CV 시간 중앙값이34.5% 감소했다.
**이는 실행·출력 검증 결과이며 사건 정확도가 아니다.** 실제 정답과 정상 영상
구분이 없어 사건 정확도·누락·오경보·의미상 근거 정확성은 측정하지 못했다.

## 실제 실행 결과

| 조건 | 실행 수 | JSON/입력 근거 모두 통과 | 전체3단계 및 최종출력 통과 | 전체 시간 중앙값 |
|---|---:|---:|---:|---:|
| 기존 VLM 단독 |21|16/21|해당 없음|16.42초|
| 기존 CV→Clef→VLM |21|13/21|9/21|68.22초|
| 개선 v2 VLM 단독 |7|6/7|해당 없음|17.49초|
| 개선 v2 CV→Clef→VLM |7|7/7|7/7|71.34초|
| 별도 pose-off 전체 파이프라인 |3|3/3|2/3|49.92초, Clef 실패 fallback 1건 포함|
| 별도 v3 JSON 라벨 ITEM_04 VLM 단독 |1|1/1|해당 없음|24.92초|

이번 추가 실행은18attempts, 실제 CV10회·Clef10회·DeepSeek18회다.
CV10회 성공, Clef9회 성공/1회HTTP429, DeepSeek18회HTTP200 중1회JSON 문법
오류가 있었다. 기존 결과를 덮어쓰거나 실패를 새 성공 결과로 대체하지 않았다.
기존은 항목당3회, 새 공통 실험은1회다. 모집단·반복 수 차이를 고려해야 한다.
새 공통 파이프라인은 더 빨라진 결과가 아니다. 지연 개선은 별도 pose-off 비교에서 확인했다.

공개7ITEM은 영상6개를 재사용한 소규모 데모다. `477_modeling_benchmark_v1`,
`final_candidates_v1`, `data`, `media`를 수정하지 않았다. 기존206결과파일 해시와
보호37파일 스냅샷을 보존했다. 모든 새 조건은 동일 원본64프레임·공통prompt·schema를
사용하며, 변환 변경은 profile과 해시로 기록한다. 추론에 정답을 사용하지 않았다.

## 수정한 부분과 확인한 원인

| 문제 | 근거와 조치 | 결과 및 남은 한계 |
|---|---|---|
| Clef 로컬 입력 차단 |65,536 token 상한을 UTF-8 byte로 취급하던 조건 제거.196,608byte 요청본문·응답·timeout·비용 보호 유지|기존 차단 ITEM_03/06 실제HTTP200. 본문85,573/67,683bytes, 공급자 input_tokens35,375/27,382. 공급자 내부 truncation은 확인 불가|
| VLM 근거 시각 불일치 |기존 34.9와 입력34.9666667 등의 차이가 허용오차를 넘음. v2는 원래 float 시각을 exact-copy 라벨로 전송|새7+7회에서 잘못된 입력 근거 시각0건. 출력 보정·허용오차 완화 없음. 정확한 내부 실패 원인을 전부 입증한 것은 아님|
| VLM JSON 문법 실패 |개선 단독 ITEM_04 raw의 `timestamp_sec=7.0` 등 잘못된 key/구분자 발견. v3는 별도 JSON 라벨·JSON 구문 지시 적용|같은64RGB/JPEG·prompt/schema로 단건 성공. 원래6/7 통계 유지. 한 번의 확률적 출력으로 일반적인 오류 제거를 보장하지 않음|
| CPU CV 지연 |매 호출 모델 import/load, 탐지, 자세 분석 수행. ByteTrack 시간은 상대적으로 작음|별도 pose-off에서 탐지/추적 관측값은 대응3항목 모두 같음. 자세 단서는 제거되므로 행동 정확도 비회귀는 미확인|
| 실패한 Clef 뒤 VLM 성공을 전체 성공으로 집계 |`whole_pipeline_validated`, upstream 오류·미확인 비용·stage별 호출 기록 추가|속도 실험2/3 전체 성공,1/3 fallback 성공으로 분리. 상위 실패를 VLM 사건 판단 실패로 분류하지 않음|
| Clef 라우팅의 속도 이득 부재 |CV 출력은 검증된 정상 사건 판단이 아님. 라우팅 score만으로 normal+고신뢰를 확정하지 않음|이번 전체10건 모두 VLM 호출, 생략0. 정상·사건 정답 확보 전 자동 억제를 적용하지 않음|

공통6종사건과 provider의 자유형 사건명 매핑은 미확정이다. CV·Clef는 검증된
사건 assessment를 만들지 못한 경우 uncertain/검토·위험축null이다. VLM의 자유형
사건명도 임의로 normal이나 특정 사건으로 매핑하지 않는다. 따라서 원본schema
검사를 통과했다고 운영용 사건 분류가 완성된 것은 아니다. 위험도는 백엔드 공식으로
계산하고, 미측정 축·실패의 위험도는 null/UNKNOWN으로 둔다.

## 속도와 메모리

개선 공통 전체 파이프라인 중앙값: 영상 디코드3.79초, CV48.36초,
Clef5.22초, VLM12.68초, 전체71.34초(p95 81.49초). 각 중앙값의 합은
전체 중앙값과 같지 않으며 IPC·변환·검증·저장 시간도 있다.
VLM 단독은 디코드3.88초/모델stage12.46초/전체17.49초(p95 25.55초).
실험 전 정한 전체120초 목표는 추가18attempts 모두 통과했다.

CV의 ITEM_03 실제 내부 측정은 import5.02초, model-load0.43초,
탐지19.31초, 자세17.35초, 추적0.25초다. 주요 병목은 CPU 탐지와 자세 분석이다.
모든 CV 호출은 별도 worker의 cold import/load를 포함한다. API 서버의 cold/cache
상태는 보장하지 않으며 실행순서·first invocation 정보는 metadata에 기록했다.

| 대응 ITEM | pose-on CV→pose-off CV | pose-on 전체→pose-off 전체 | 전체 단계 성공 여부 |
|---|---|---|---|
|03|47.20→32.27초|71.34→56.74초|양쪽 성공|
|06|46.53→30.88초|66.09→49.92초|양쪽 성공|
|02|47.18→30.41초|69.28→48.91초|pose-off Clef429: 정상 전체 지연 비교에서 제외|

대응3항목 CV 중앙값 감소34.54%로 사전 제안20% 개선 목표를 통과했다.
전체 단계가 성공한 대응2항목의 전체 중앙값은68.71→53.33초,22.39% 감소했다.
표본이 작고 항목당1회이며 API 변동이 있다. 넘어짐 등 자세가 중요한 사건의
성능이 유지됐다는 근거는 없으므로 pose-off를 운영 기본값으로 바꾸지 않았다.

CV worker OS peak RSS는 pose-on 약634~642MB, pose-off 약504~509MB였다.
부모 프로세스의20ms 샘플 peak RSS는 공통 실험527~602MB, pose-off531~557MB다.
별도 프로세스 최고값을 합산한 동시 전체 메모리 측정은 아니다. CPU PyTorch로
실행했고 공급자GPU/VRAM은 측정 불가(null), GPU를 대여하지 않았다.

v3 단건은 디코드9.33초, JPEG/직렬화 전처리2.04초, API 요청11.13초,
VLM stage14.09초, 전체24.92초였다. 출력 상한4096,실제출력1489tokens,
finish_reason=stop. v2의8192와 다른 예산 조건이므로 단건 품질·속도를 전체
v2와 동일 조건의 성능 개선이라고 비교하지 않는다.
gjt
## Clef 한도와 비용

**과거의6건 차단은 로컬 코드의 입력 보호 오류였다.** 반면 이번 별도 속도 실험
ITEM_02는 실제 Cloudflare HTTP429/code4006으로 일일무료10,000Neurons 소진을
명시했다. 서로 다른 원인이다. 무료 할당량은00:00UTC(한국09:00)에 갱신되고
계정 전체 사용량 확인이 필요하다. Paid 플랜 전환·공급자 한도 우회·자동 재시도는
수행하지 않았다. [Cloudflare 공식 정책](https://developers.cloudflare.com/workers-ai/platform/pricing/).

| 비용 항목 | 금액/상태 |
|---|---|
| 처음 두 실험 추가 최대 모델 요금 추정 |$0.74023680, cache miss·최대출력 가정|
| 처음 두 실험 추가 안전예약 |$1.48047360, 모델 추정의2배|
| v3 단건 최대 모델 요금 / 안전예약 |$0.029376 / $0.058752|
| 기존 포함 누적 안전예약 |**$4.99158528 / $5**,87건|
| 남은 안전예약 한도 |$0.00841472: 추가 모델 호출 중단|
| 기존 포함 확인된86건 토큰비용 추정 부분합 |$0.523827864|
| 이번18attempts의 확인된 토큰비용 추정 부분합 |$0.237050508|
| 미확인 |Clef429 1건 usage 없음; 과금0으로 가정하지 않고 예약 유지|
| 전체 토큰비용 추정 / 실제 청구액 |둘 다null, 완전한 비용 확인 불가|

공통 개선 실행의 확인된 사용량 추정은$0.197098968, pose-off는 확인된 부분
$0.018999792, v3는$0.020951748다. 이는 실제 청구서 금액이 아니다.
DeepSeek 잔액 변화도 반올림·동시 사용 영향을 받아 청구액으로 처리하지 않는다.
실패 요청의 예약을 돌려주거나 기존 ledger를 초기화하지 않았다.
공급자 요금 근거: [Clef](https://developers.cloudflare.com/workers-ai/models/clef/),
[DeepSeek 가격](https://api-docs.deepseek.com/quick_start/pricing/),
[DeepSeek 이미지 입력](https://api-docs.deepseek.com/guides/vision/).

## 합격·실패·미완료 구분

- 코드/계약: MAIN 전체pytest **386통과**, warning1(FastAPI TestClient 의존성 경고),
  frozen contracts 일치. 역할별25/38/20/94/67 집중 테스트 및 CLI/registry 검사 통과.
- 실행 후 무결성 검사: 원본206파일 digest 일치, 보호37파일 스냅샷 일치,
  계약 재검사 통과. 코드·문서·새 결과264파일에서 실제 credential 값 검출0건,
  실제 `.env` Git 추적 없음. 확인 범위 밖의 시스템 로그까지 검증했다는 뜻은 아니다.
- 최종 독립 reviewer **PASS**: 저장된18건 진단을 원본응답·schema·context·실제
  입력 근거와 재대조해 모두 일치. 대응 속도·ledger·206/37파일 해시 확인,
  별도333파일 인증값 검출0건·계약 검사 통과. pytest386건은 MAIN 실행 기록이며
  reviewer가 재실행했다고 보고하지 않는다. 사건 정확도 승인은 아니다.
- 공통7항목 전체 파이프라인: 사전 제안100% schema/근거/전체 실행 기준 통과.
  VLM 단독6/7은100% 목표 실패. 문법 오류 원본을 남겼다.
- 별도 속도 실험: CV20% 감소 목표 통과, 전체3/3 실행 성공 목표 실패(Clef quota).
  fallback 출력3/3을 전체3/3 성공으로 세지 않는다.
- v3: 사전 분리한 단건 목표 통과. 기존 단독7항목 전체 목표를 통과로 바꾸지 않는다.
- 사건별 정확도·누락·오경보, 의미상 근거 채점, 위험도 정답 비교: 정답·정상 구분
  부재로 미측정. 목표를 결과 후 변경하지 않았다. 테스트의 MockTransport는
  코드·실패 경로 확인용이며 실제 모델 성능 근거로 쓰지 않는다.
- 서비스 ASGI의 실제 Clef/VLM 슬롯 연결, 촘촘한 추적, 새로운 영상 평가,
  warm-worker/GPU 실험·학습: 미수행. 이번 개선은 실제 benchmark CLI 경로다.

## 다음 작업과 사용자가 준비할 것

1. **실제 정답·정상 영상과 중립ID 매핑**: 모델의 사건 실패 원인을 채점해야 한다.
   탐지 누락/추적실패/자세판단 오류를 현재 관측값만으로 확정하지 않는다.
2. **카메라 구역·침입 허용·배회 시간 정책과 사건명 매핑**: CV 규칙과 공통6종
   분류를 확정해야 한다. GT에서 구역/시간을 역산하거나 자유형 사건을 임의 변환하지 않는다.
3. **Clef 대시보드 사용량·갱신과 청구서 확인**: 공급자 무료 할당량과 이번 누적
   실험예산은 별개다. 새 예산을 명시하기 전 추가 유료 실험을 진행하지 않는다.
4. 정답 확보 후 pose-on/off의 넘어짐 누락을 먼저 비교한다. 그다음 필요한
   경우만 자세 분석, 지속 worker, GPU 실행을 별도 실험으로 측정한다.
5. 정상 검증이 가능해진 뒤 Clef가 생략한 사건도 분모에 포함하여 라우팅을 평가한다.
   현재는 전체 입력을 VLM과 사람 검토로 보내므로 라우팅 비용 절감은 없다.

## 결과 파일과 재현

- [실행 명령·환경·실패 확인](../docs/benchmark-improvement-run.md)
- [외부에서 준비할 항목](benchmark-improvement-next-actions.md)
- [사전 계획과 분리 실험 기준](../docs/benchmark-improvement-plan.md)
- [원본 대비 비교 JSON](../runs/improvement-analysis/comparison.json),
  [대응 결과 CSV](../runs/improvement-analysis/paired-output.csv),
  [속도 CSV](../runs/improvement-analysis/pose-speed.csv),
  [속도 그림](../runs/improvement-analysis/pipeline-speed.png)
- 공통 개선: `runs/improved-canonical64/{raw,common,diagnostics,submissions}`,
  [평가표](../runs/improved-canonical64/evaluation.csv),
  [실패 목록](../runs/improved-canonical64/failures.json).
- 별도 속도: `runs/improved-pose-off/`, 별도 JSON 라벨: `runs/improved-json-labels-item04/`.
- 누적 비용: `runs/477-paid-budget.json`. API 키/계정값은 결과에 저장하지 않는다.

실제 순차 에이전트는 `/root/improvement_audit`(자료·원인 조사),
`/root/improvement_clef`(Clef), `/root/improvement_vlm_grounding`(VLM 시각),
`/root/improvement_cv_profile`(CV), `/root/improvement_pipeline_evaluation`(평가),
`/root/improvement_readiness_review`(독립 검토), `/root/improvement_vlm_json_labels`(v3)다.
등록 explorer/model_engineer/evaluation_engineer/reviewer 설정을 적용했고 공통CLI·
registry·계약동결·통합검사·실제 실행·문서는 MAIN이 수행했다.
