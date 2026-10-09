# Verification — 2026-10-06

Environment: Linux, Python 3.12.14. No real provider credentials or CCTV dataset.

| Check | Observed result |
|---|---|
| Original pytest | 4 passed; mock/risk only |
| Revised pytest | 41 passed |
| pip install -e ".[dev]" | Success, 477-role1 0.2.0 editable wheel built |
| Regular wheel build | Success; only app packages included |
| Live Uvicorn HTTP smoke | status/demo/incident/ACK succeeded |
| TOML parse | Global config and all five custom roles parsed |
| Contract hash check | Passed |
| Mock CLI | exit 0; is_mock=true, uncertain/review |
| Real local_cv unconfigured CLI | expected exit 2; provider_error, risk_axes=null, review |
| Fixture→assessment→Incident→GET | Integration test passed |
| WebSocket | Initial/push/ACK update/reconnect and cleanup tests passed |
| ACK | State/audit, idempotent replay, 409 conflict, invalid action tests passed |
| Suppressed restore | Preserved id, single restored review incident, replay test passed |
| Manifest | Source-group leakage, checksum, path escape, observation labels tested |
| Frozen test guard | Missing lock/modified manifest rejected |

One upstream Starlette TestClient deprecation warning for httpx was emitted. It did not fail tests.
41 passed includes parametrized schema/model tests; it does not certify real model accuracy, real video decode,
provider billing, Windows/Python3.11 compatibility, production auth/DB or 477-camera throughput.

Source attachments' six configuration files byte-match the recovered original ZIP.
Source ZIP was inspected; original supplied files were not overwritten.
Resolved dependency versions are in requirements-tested.txt, a tested-environment snapshot rather than universal lock.
