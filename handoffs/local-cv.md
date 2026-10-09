# 04 Local CV — 진행 기록

실제 담당 `/root/stage04_local_cv` (model_engineer TOML), MAIN은 dependencies/registry만 담당.
실제 MP4가 없어 이벤트 모델 성능은BLOCK이다. HOG 내장 person detector와 단순 추적의
CV 관측만 구현한다. pose/zone/6-event 분류는 검증되지 않아 uncertain/confidence0/
각 risk axis=null/review 출력이며 normal 또는 supported event 성능을 주장하지 않는다.

공식 OpenCV HOG: https://raw.githubusercontent.com/opencv/opencv/4.x/modules/objdetect/include/opencv2/objdetect.hpp
SVM 거리 점수는 event confidence가 아니다. 패키지 버전은 공식 PyPI metadata에서
4.13.0.92 Windows wheel을 확인했다: https://pypi.org/project/opencv-python-headless/4.13.0.92/
MAIN optional extra `local-cv`에 OpenCV4.13.0.92/numpy>=2,<3를 등록한다.

생성자 LocalCVAdapter(resolver, timeout_sec=15, max_clip_bytes=64MiB,
max_frame_bytes=2MiB, max_frames=16, max_waiters=1).
고정 sampling 후 PreparedMedia.resolver의 실제 JPEG bytes를 child process에 전달한다.
clip bytes/hash 확인, 입력 temporal_state는 무시, 실제 evidence refs만 사용한다.
1 CPU child + bounded waiting, timeout/cancel kill/await; extractor 결과와 시간을 별도 진단으로 보관한다.
MAIN registry는 resolver 주입이 있으면 실제 adapter, 없으면 명시 configuration failure를 반환한다.
추론에는 annotation/manifest/원본 경로를 전달하지 않는다.

## 실제 결과와 한계

worker 변경: local_cv.py, local_cv_worker.py, tests/models/test_local_cv.py만.
focused21 passed/0skip; 초기 실패4는 fallback evidence 보존을 잘못 기대한 테스트를 수정했다.
MAIN registry resolver 주입/contract test 추가 후 focused22 passed, 전체188 passed,
`scripts/check_contracts.py`match. 각각 기존 경고1. reviewer 검토 대기.

`/root/stage04_reviewer` 실제 독립 focused22/full188/hash match, skip0; 기술PASS.
승인 범위는 CV 관측/안전 경계이며 사건 분류·실제 성능은BLOCK으로 유지했다.

별도 합성 MP4 실행: black640x360/4fps/2s,4462bytes,
clipSHA256=605d237a381b734647e4862ffcca1008fc5c5ba9120d82108fc431e4a0c5a296,
PTS=[0,500,1000,1500]. 최초 sampling123.54ms, adapter 재추출107.70ms,
HOG worker1490.72ms, execute1599.16ms. 합성 blank의 person_count0은 관측일 뿐 normal 판단이 아니다.
실제 출력 uncertain/confidence0/각axis=null/review/nonmock/cost=null.
Python3.11.1/OpenCV4.13.0/NumPy2.4.6/FFmpegN-122625-g17d89757cd-20260203,
Windows10.0.26200, CPU/OpenCVthreads1/OpenCLdisabled. CPU 모델/GPU는 미확인.
이 숫자는 단일 합성 실행 시간이며 CCTV 정확도/실서비스 지연으로 해석하지 않는다.

입력은 기본4-frame/640x360 sampler의 실제 bytes/PTS와 일치해야 한다(subset허용).
다른 profile은 명시 실패/review. 전체 재추출까지1active+1waiter 제한.
시간초과/취소/출력초과 child kill+reap 검증. 차량검출/pose/zone/6eventclassifier 미지원.
실제 MP4/JSON 및 지원범위별 사건 검증은BLOCK, 모델 선택/threshold 성능 결정은 미완료.
