# 프론트 API 실제 응답 예제 — 2026-10-07

이 문서의 캡처는 계약1.0 당시 이력이다. 현재 snapshot 기본 태그는1.1이며
부분 risk_axes의 미측정 축은null, 총 risk=null/level=UNKNOWN/review다.
최신 계약은 docs/api-contract.md와 handoffs/03_contract_delta.md를 따른다.

프로젝트 .venv의 FastAPI TestClient로 직접 캡처한 개발 데모 응답입니다.
모든 사건은 synthetic이며 실제 영상·모델 추론 결과가 아닙니다. timestamp는 캡처 시각입니다.
실제 MP4가 없어 stream은 503, clip.available=false입니다. 팀 합의는 아직 확인 대기입니다.
카메라 배열과 WS 전체 snapshot을 그대로 보관합니다. 각 POST 재시도에는 같은 key를 사용합니다.

## WS /ws/attention 최초 snapshot (초기 빈 상태)

HTTP/status: 101

```json
{
  "event_type": "snapshot",
  "schema_version": "1.0",
  "revision": 0,
  "active_count": 0,
  "total_cameras": 477,
  "configured_cameras": 9,
  "suppressed_count": 0,
  "level_counts": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0,
    "review": 0,
    "unknown": 0
  },
  "incidents": [],
  "cameras": [
    {
      "id": "CAM_01",
      "name": "CAM 01",
      "location": "demo",
      "stream_url": "/stream/CAM_01",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_02",
      "name": "CAM 02",
      "location": "demo",
      "stream_url": "/stream/CAM_02",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_03",
      "name": "CAM 03",
      "location": "demo",
      "stream_url": "/stream/CAM_03",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_04",
      "name": "CAM 04",
      "location": "demo",
      "stream_url": "/stream/CAM_04",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_05",
      "name": "CAM 05",
      "location": "demo",
      "stream_url": "/stream/CAM_05",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_06",
      "name": "CAM 06",
      "location": "demo",
      "stream_url": "/stream/CAM_06",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_07",
      "name": "CAM 07",
      "location": "demo",
      "stream_url": "/stream/CAM_07",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_08",
      "name": "CAM 08",
      "location": "demo",
      "stream_url": "/stream/CAM_08",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_09",
      "name": "CAM 09",
      "location": "demo",
      "stream_url": "/stream/CAM_09",
      "status": "normal",
      "bbox": []
    }
  ]
}
```

## GET /api/status

HTTP/status: 200

```json
{
  "ok": true,
  "mode": "demo",
  "system_status": "demo",
  "timestamp": "2026-10-06T16:01:07.006970+00:00",
  "active_count": 0,
  "total_cameras": 477,
  "configured_cameras": 9,
  "revision": 0
}
```

## GET /api/cameras

HTTP/status: 200

```json
[
  {
    "id": "CAM_01",
    "name": "CAM 01",
    "location": "demo",
    "stream_url": "/stream/CAM_01",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_02",
    "name": "CAM 02",
    "location": "demo",
    "stream_url": "/stream/CAM_02",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_03",
    "name": "CAM 03",
    "location": "demo",
    "stream_url": "/stream/CAM_03",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_04",
    "name": "CAM 04",
    "location": "demo",
    "stream_url": "/stream/CAM_04",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_05",
    "name": "CAM 05",
    "location": "demo",
    "stream_url": "/stream/CAM_05",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_06",
    "name": "CAM 06",
    "location": "demo",
    "stream_url": "/stream/CAM_06",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_07",
    "name": "CAM 07",
    "location": "demo",
    "stream_url": "/stream/CAM_07",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_08",
    "name": "CAM 08",
    "location": "demo",
    "stream_url": "/stream/CAM_08",
    "status": "normal",
    "bbox": []
  },
  {
    "id": "CAM_09",
    "name": "CAM 09",
    "location": "demo",
    "stream_url": "/stream/CAM_09",
    "status": "normal",
    "bbox": []
  }
]
```

## GET /api/pipeline/stats

HTTP/status: 200

```json
{
  "total": 477,
  "configured_cameras": 9,
  "candidates": 0,
  "reasoned": 0,
  "incidents": 0,
  "suppressed": 0,
  "needs_review": 0,
  "avg_latency_sec": null,
  "total_latency_sec": null,
  "stage_trace": [],
  "today_summary": {
    "incidents": 0,
    "suppressed": 0,
    "avg_latency_sec": null
  },
  "measurement_scope": "demo_snapshot"
}
```

## POST /api/demo/step

요청: `{"step":2}`

Idempotency-Key: `example-demo-2`

HTTP/status: 200

```json
{
  "ok": true,
  "step": 2,
  "revision": 1
}
```

## GET /api/suppressed

HTTP/status: 200

```json
[
  {
    "id": "SUP-001",
    "cam_id": "CAM_04",
    "stage1_label": "Possible fall",
    "ai_verdict": "normal",
    "reason": "데모: 자세를 낮춘 뒤 다시 걸음",
    "risk": 8,
    "resumed_walking": true,
    "restored": false
  }
]
```

## POST /api/suppressed/SUP-001/restore

Idempotency-Key: `example-restore`

HTTP/status: 200

```json
{
  "ok": true,
  "revision": 2
}
```

## GET /api/incidents/RESTORED-SUP-001

HTTP/status: 200

```json
{
  "id": "RESTORED-SUP-001",
  "sample_id": "restore-SUP-001",
  "type": "uncertain",
  "title": "제외 알림 재검토",
  "primary_cam": "CAM_04",
  "related_cams": [],
  "location": null,
  "risk": null,
  "level": "UNKNOWN",
  "risk_axes": null,
  "confidence": 0,
  "needs_human_review": true,
  "uncertainty_reason": "operator_restored",
  "rank": 1,
  "rank_reason": "위험도 미측정: 사람 검토 우선",
  "timeline": [],
  "evidence": [],
  "related_views": [],
  "ai_opinion": null,
  "recommended_actions": [],
  "next_incident_id": null,
  "created_at": "2026-10-06T16:01:07.022887Z",
  "status": "open",
  "dispatch_requested": false,
  "assigned_operator": null,
  "revision": 1
}
```

## POST /api/demo/step

요청: `{"step":3}`

Idempotency-Key: `example-demo-3`

HTTP/status: 200

```json
{
  "ok": true,
  "step": 3,
  "revision": 3
}
```

## GET /api/incidents/INC-032

HTTP/status: 200

```json
{
  "id": "INC-032",
  "sample_id": "demo-INC-032",
  "type": "collapse",
  "title": "데모: collapse",
  "primary_cam": "CAM_08",
  "related_cams": [],
  "location": null,
  "risk": 89,
  "level": "CRITICAL",
  "risk_axes": {
    "severity": 0.9,
    "imminence": 0.95,
    "exposure": 0.8,
    "persistence": 0.85
  },
  "confidence": 0.92,
  "needs_human_review": false,
  "uncertainty_reason": null,
  "rank": 1,
  "rank_reason": "서버 위험도 내림차순",
  "timeline": [],
  "evidence": [],
  "related_views": [],
  "ai_opinion": null,
  "recommended_actions": [],
  "next_incident_id": null,
  "created_at": "2026-10-06T16:01:07.028407Z",
  "status": "open",
  "dispatch_requested": false,
  "assigned_operator": null,
  "revision": 1
}
```

## GET /api/incidents/INC-032/clip

HTTP/status: 200

```json
{
  "clip_url": "/stream/CAM_08",
  "start": 0,
  "end": 10,
  "bbox_track": [],
  "available": false,
  "is_demo": true
}
```

## GET /stream/CAM_08

HTTP/status: 503

```json
{
  "detail": "place a licensed MP4 at MEDIA_ROOT/CAM_XX.mp4"
}
```

## POST /api/incidents/INC-032/ack

요청: `{"action":"verify"}`

Idempotency-Key: `example-ack`

HTTP/status: 200

```json
{
  "ok": true,
  "incident": {
    "id": "INC-032",
    "sample_id": "demo-INC-032",
    "type": "collapse",
    "title": "데모: collapse",
    "primary_cam": "CAM_08",
    "related_cams": [],
    "location": null,
    "risk": 89,
    "level": "CRITICAL",
    "risk_axes": {
      "severity": 0.9,
      "imminence": 0.95,
      "exposure": 0.8,
      "persistence": 0.85
    },
    "confidence": 0.92,
    "needs_human_review": false,
    "uncertainty_reason": null,
    "rank": null,
    "rank_reason": null,
    "timeline": [],
    "evidence": [],
    "related_views": [],
    "ai_opinion": null,
    "recommended_actions": [],
    "next_incident_id": null,
    "created_at": "2026-10-06T16:01:07.028407Z",
    "status": "acked",
    "dispatch_requested": false,
    "assigned_operator": null,
    "revision": 2
  },
  "revision": 4
}
```

## WS /ws/attention 재연결 snapshot (verify 후)

HTTP/status: 101

```json
{
  "event_type": "snapshot",
  "schema_version": "1.0",
  "revision": 4,
  "active_count": 0,
  "total_cameras": 477,
  "configured_cameras": 9,
  "suppressed_count": 0,
  "level_counts": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0,
    "review": 0,
    "unknown": 0
  },
  "incidents": [],
  "cameras": [
    {
      "id": "CAM_01",
      "name": "CAM 01",
      "location": "demo",
      "stream_url": "/stream/CAM_01",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_02",
      "name": "CAM 02",
      "location": "demo",
      "stream_url": "/stream/CAM_02",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_03",
      "name": "CAM 03",
      "location": "demo",
      "stream_url": "/stream/CAM_03",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_04",
      "name": "CAM 04",
      "location": "demo",
      "stream_url": "/stream/CAM_04",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_05",
      "name": "CAM 05",
      "location": "demo",
      "stream_url": "/stream/CAM_05",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_06",
      "name": "CAM 06",
      "location": "demo",
      "stream_url": "/stream/CAM_06",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_07",
      "name": "CAM 07",
      "location": "demo",
      "stream_url": "/stream/CAM_07",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_08",
      "name": "CAM 08",
      "location": "demo",
      "stream_url": "/stream/CAM_08",
      "status": "normal",
      "bbox": []
    },
    {
      "id": "CAM_09",
      "name": "CAM 09",
      "location": "demo",
      "stream_url": "/stream/CAM_09",
      "status": "normal",
      "bbox": []
    }
  ]
}
```

내부 model ingestion은 HTTP endpoint가 아닙니다. fixture→execute→policy→저장→WS는 tests/integration/test_model_ingestion.py로 검증합니다.
프론트 확인은 handoffs/frontend-contract.md에 기록된 규약 및 모델 suppression의 null 필드 확장을 포함해야 합니다.

