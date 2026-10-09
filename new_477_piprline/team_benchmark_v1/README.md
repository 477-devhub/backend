# 477 팀원 벤치마크: 이미지·CSV·자동 채점

이 폴더의 입력으로 자신의 파이프라인을 실행하고 CSV를 제출하면 `score.py`가 사건·검출·라우팅·출력 품질을 각각 채점합니다. **모델을 실행하는 코드와 API 키는 각 팀원이 준비합니다. 채점기는 모델을 호출하지 않습니다.** YOLO→Clef→VLM, CV+VLM, VLM 단독을 구분해 제출할 수 있습니다.

전달할 때는 **team_benchmark_v1 폴더 전체**를 복사하세요. 입력 PNG는 약1.7GB이며 768개가 이미 준비돼 있습니다. 저장 공간 때문에 기본 생성하는 477_team_tools_v1.zip에는 코드·CSV·manifest만 들어 있고 이미지는 없습니다. 이 보조ZIP만 보내면 완전한 벤치마크 전달이 아닙니다. 별도 평가자 정답ZIP은 채점 담당자에게 전달합니다.

## 바로 시작

Python 3.11 이상에서 이 폴더를 작업 폴더로 사용합니다.

ZIP은 완전히 같은 이미지의 중복만 제거해 저장했습니다. 압축 해제 후 `python restore_inputs.py`를 먼저 실행하면 원본 해시가 같은 768개 입력 경로가 복원됩니다. 해상도·픽셀·샘플링은 바뀌지 않습니다. 압축 파일과 해제 입력을 함께 두려면 약4GB 여유 공간을 권장합니다. 제공된 ready 폴더에서는 이 과정이 이미 완료돼 있습니다. 입력은 읽기 전용으로 취급하세요(로컬 ready 폴더와 원본 NEW 입력 사이에도 같은 파일의 저장 공간을 공유합니다).

```powershell
python restore_inputs.py
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe score.py --create-template --submission my_submission.csv
```

`submission_template.csv` 또는 새로 생성한 CSV의12행을 사용합니다. P001~P006은 영상1개씩64장, P007/P008은2개32장씩, P009는3개22/21/21장, P010은4개16장씩, P011은5개13/13/13/13/12장, P012는6개11/11/11/11/10/10장입니다. **문제 하나당 총64장**이며 서로 다른 영상을 연결해 하나의 사람으로 추적하면 안 됩니다. P008의2개 source는 README상 동일 사건의 다른 시점이나 정확한 동기화는 확보되지 않았습니다.

## 모델에 넣을 입력

- `items.json`: 공통 문제 목록·영상별 프레임 수·같은 사건/독립 영상 관계.
- `data/frames/Pxxx/manifest.json`: 프레임 원본 번호·시간·source_id·image_path·SHA256. 이미지 경로는 이 폴더 기준입니다.
- `data/frames/Pxxx/SRCxx/*.png`: 실제 원본 해상도 이미지. 모델별 크기 변환은 설정과 시간에 기록합니다.
- `prompts/pipeline_v1.txt`: 공통 프롬프트.
- `schemas/vlm_output.schema.json`: source별 결과 JSON 스키마.

자신의 모델에 manifest의64장을 순서대로 읽어 전달하세요. 같은 source 안에서만 시간·추적 상태를 누적합니다. Clef가 실제 받을 수 있는 텍스트/최대4이미지 변환 등은 팀원 파이프라인의 책임이며 변환 내역을 기록하세요. 정답은 입력 파일에 없습니다. **ground_truth/ 및 평가 결과 ground_truth 셀은 모델에 전달하지 않습니다.**

## 실행 결과를 CSV에 넣기

`models`에 모델명/버전/주요 설정/YOLO 장치를 JSON으로 기록합니다. `stage_inputs`는 템플릿의 고정 manifest/prompt 경로·해시를 유지하고, 추가로 실제 요청 파일 경로·전달 frame_id 목록·변환 설정을 기록합니다. 이미지/base64는 CSV에 쓰지 않습니다. API 키가 포함된 헤더·환경변수도 저장하지 않습니다.

`stage_outputs` 셀은 다음처럼 각 단계 파일을 참조합니다. 경로는 벤치마크 폴더 기준이며 제출 파일들도 해당 폴더 아래 submissions/에 저장합니다.

```json
{"yolo":{"record_path":"submissions/my_model/P001/yolo.json"},"clef":{"record_path":"submissions/my_model/P001/clef.json"},"vlm":{"record_path":"submissions/my_model/P001/vlm.json"}}
```

각 파일은 `status`, `executed`, `output`, `errors`, 선택적으로 `metadata/model`, `latency_ms`, `cost_usd`를 갖는 stage record입니다. 실제 원본 응답과 정규화 출력은 별도 파일로 모두 보존하세요. 최소 구조와 라벨 동의어/허용 수정 범위는 [TEAM_CONTRACT.md](TEAM_CONTRACT.md)를 보세요. 셀 안에 record JSON을 직접 넣어도 됩니다.

단계를 쓰지 않았다면 `status=skipped`, `executed=false`, `output=null`입니다. Clef 없는 파이프라인은 models.clef=null로 표시하며 Clef 라우팅 점수는 N/A입니다. Clef가 특정 영상을 막으면 VLM active_sources에 실제 요청한 영상만 넣고 막힌 영상 출력은 만들지 않습니다. 막힌 영상은 전체 사건 정확도의 누락으로 남습니다. unknown 비용/메모리는 null; 비용은 청구 실제값과 사용량×가격 추정값을 구분합니다. 시간은 전처리·추론·전체, 반복 횟수·최초 실행 여부를 기록합니다.

## 자동 채점

평가 담당자에게 받은 `477_evaluator_reference_v1.zip`을 같은 폴더에 풀면 ground_truth/ai_review_v1/sources.json이 생깁니다. 이 파일은 **채점에만** 사용합니다.

```powershell
.venv\Scripts\python.exe score.py --submission my_submission.csv --ground-truth ground_truth/ai_review_v1/sources.json --output scores/my_model
```

결과는 scores/my_model/results.csv(12문제 각1행)와 summary.json입니다. 누락 행도 분모에 포함합니다. 고정 입력이 바뀌거나 경로/정답 계약이 잘못되면 비교를 거부합니다. 점수가 낮으면 errors와 단계별 record의 원본 응답을 먼저 확인하세요. `validated` 또는 스키마 통과는 사건 정답을 의미하지 않습니다.

## 점수의 범위

정답은 독립 RT-DETR-L 후보를 MAIN AI가 직접 이미지로 검수한 **소규모 데모 참고 정답**입니다. 독립 전문가/사람 gold는 아닙니다. 6개 영상의 사건·호출 필요 기준이 있으며, 박스는 희소24프레임39개 중 완전18프레임만 평가합니다. 가림/원경6프레임은 미평가입니다. source별 클래스 범위가 다릅니다(SRC01/04는6개 객체 클래스, 나머지는 person). 범위 밖 클래스와 미검수 프레임은 오경보/미검출로 만들지 않습니다.

주 점수는 전체 source 사건 정답률이며 검출 precision/recall/mAP@0.5, 라우팅 호출 누락, JSON 형식, 입력 근거 유효성, 사람 검토 정책을 별도 확인합니다. 12문제에는 동일 영상이 재사용되므로 독립28사건 성능으로 해석하지 마세요. 6개 단독 문제 결과를 함께 보세요. 정상 대조 영상이 없어 정상 오경보율·불필요 호출률·Clef 절감 효과는 아직 측정할 수 없습니다. 근거 시간대의 거친 포함 여부도 설명 사실성의 전문가 정확도를 대신하지 않습니다.

## 수정 허용 범위

수정 가능: 자신의 모델/API/추론·변환 코드, 모델 설정, submissions/ 출력.

공통 비교에서 수정 금지: items/manifest/64이미지/공통 prompt/schema/평가기/정답/lock. 추가 프레임·crop·다른 prompt는 별도 실험으로 표시합니다. 입력 문제를 다른 영상으로 바꾸면 같은 벤치마크 점수가 아닙니다. API 키는 로컬 환경변수로만 읽고 제출물에 포함하지 마세요.
