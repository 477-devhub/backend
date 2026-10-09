"""Human visual inspection artifact; never supplies labels to the models."""
from pathlib import Path
import json
import cv2
import numpy as np

root = Path(__file__).resolve().parent
canvas = np.full((6 * 205, 3 * 360, 3), 242, dtype=np.uint8)
quality = []
for n in range(1, 7):
    source = f"SRC{n:02d}"
    paths = sorted((root / f"data/frames/P{n:03d}" / source).glob("*.png"))
    for col, index in enumerate((0, len(paths) // 2, len(paths) - 1)):
        original = cv2.imread(str(paths[index]))
        quality.append({"source_id": source, "sample_index": index, "pixel_mean": float(original.mean()),
                        "near_black": bool(original.mean() < 2)})
        image = cv2.resize(original, (360, 180))
        canvas[(n - 1) * 205:(n - 1) * 205 + 180, col * 360:(col + 1) * 360] = image
        cv2.putText(canvas, f"{source} sample {index+1}/64", (col * 360 + 8, n * 205 - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (10, 10, 10), 1)
(root / "inspection").mkdir(exist_ok=True)
cv2.imwrite(str(root / "inspection/contact.png"), canvas)
(root / "inspection/quality.json").write_text(json.dumps({"scope": "first/middle/last 18 selected images; not all 768 slots",
    "threshold_pixel_mean": 2, "samples": quality}, indent=2), encoding="utf-8")
