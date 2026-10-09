# Input Protocol

Protocol: `uniform_total64_v1`.
Use only `iter_model_frames(item_id)`. Every ITEM has **64 total frames**.
CV pipelines also must not read source frames beyond these 64 canonical frames.

| Input | Allocation |
|---|---|
| Single-camera | 64 |
| ITEM_04, three cameras | CAM_01: 22 / CAM_02: 21 / CAM_03: 21 |
| ITEM_07, two cameras | CAM_01: 32 / CAM_02: 32 |

Allocation is equal per camera, with the remainder assigned in manifest order.
For allocation N and frame count F, selected indices are
`floor(j * (F - 1) / (N - 1) + 0.5)` for `j = 0..N-1`.
The frozen loader performs selection and RGB conversion; do not replace this algorithm.

Each yielded frame contains packed RGB bytes (1920 x 1080 x 3), a generic camera ID,
and a timestamp relative to that camera's clip. Timestamps are selected indices divided by 30.
No precise cross-camera synchronization is assumed.

Model-visible information: canonical pixels, generic camera IDs, neutral relative timestamps,
common prompt and task-specific response structure only. Paths, opaque asset locators,
ITEM IDs, fingerprints and local media handles stay in the harness.
Use the loader's fingerprint unchanged in the result envelope.

No whole-video fallback, extra frames, external visual information, or label metadata.
The CV stage in P0–P3 receives the same canonical pixels as the VLM stage in P4.
P1–P3 may pass CV-derived features from those pixels to their decision model.
Within an ITEM, reuse decoded canonical frames between stages rather than selecting more frames.

For ITEM_05 use one view only; ITEM_06 uses the other view only; ITEM_07 uses both views.
ITEM_07 remains 32 + 32 = 64, never 128.
For ITEM_04, assess all three cameras and provide a complete attention queue.

P4 must use canonical frames instead of uploading the MP4. If a provider cannot accept
64 images at once, batch the same canonical frames. Do not generate or add other frames.
Document batching and cross-batch aggregation in `runtime_config`.
