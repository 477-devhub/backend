"""Per-frame person detection + 17-keypoint pose with a pretrained nano pose model.

No tracking here (sparse association is done by SparseTracker), no training, no fine-tuning.
Also computes two very cheap per-frame / per-detection descriptors:
image statistics (brightness / contrast / sharpness) and an HSV colour histogram per person box.
"""
import time

import cv2
import numpy as np

from .utils import EXP_ROOT, sha256_file


class PoseDetector:
    def __init__(self, cfg):
        import torch
        import ultralytics
        from ultralytics import YOLO

        self.cfg = cfg
        self.mcfg = cfg['model']
        self.cuda = torch.cuda.is_available()
        self.device = 0 if self.cuda else 'cpu'
        self.half = bool(self.mcfg['half']) and self.cuda
        if self.cuda:
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        self.weights_path = __import__('pathlib').Path(self.mcfg['weights']).resolve()
        t0 = time.perf_counter()
        self.model = YOLO(str(self.weights_path))
        self.model.to('cuda:0' if self.cuda else 'cpu')
        self.load_ms = (time.perf_counter() - t0) * 1000
        self.info = {
            'name': self.weights_path.stem,
            'task': self.model.task,
            'weights_file': self.weights_path.name,
            'weights_sha256': sha256_file(self.weights_path),
            'weights_size_bytes': self.weights_path.stat().st_size,
            'parameters': int(sum(p.numel() for p in self.model.model.parameters())),
            'library': 'ultralytics',
            'library_version': ultralytics.__version__,
            'torch_version': torch.__version__,
            'device': torch.cuda.get_device_name(0) if self.cuda else 'cpu',
            'precision': 'fp16' if self.half else 'fp32',
            'input_size': self.mcfg['imgsz'],
            'conf_threshold': self.mcfg['conf'],
            'iou_threshold': self.mcfg['iou'],
            'batch': self.mcfg['batch'],
            'pretrained_only': True,
        }

    def warmup(self):
        t0 = time.perf_counter()
        dummy = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for n in (self.mcfg['batch'], 5, 1):   # full and partial batch shapes used by the 64-frame protocol
            self._predict([dummy] * n)
        return (time.perf_counter() - t0) * 1000

    def _predict(self, frames_bgr):
        return self.model.predict(
            frames_bgr, imgsz=self.mcfg['imgsz'], conf=self.mcfg['conf'], iou=self.mcfg['iou'],
            max_det=self.mcfg['max_det'], half=self.half, device=self.device,
            classes=self.mcfg['classes'], verbose=False)

    def detect(self, frames_rgb):
        """frames_rgb: list of HxWx3 uint8 RGB arrays. Returns per-frame dicts (pixel coordinates)."""
        out = []
        bs = self.mcfg['batch']
        for start in range(0, len(frames_rgb), bs):
            chunk = frames_rgb[start:start + bs]
            bgr = [np.ascontiguousarray(f[:, :, ::-1]) for f in chunk]
            results = self._predict(bgr)
            for frame_bgr, res in zip(bgr, results):
                out.append(self._parse(frame_bgr, res))
        return out

    def _parse(self, frame_bgr, res):
        h, w = frame_bgr.shape[:2]
        stats = image_stats(frame_bgr)
        dets = []
        boxes = res.boxes
        if boxes is not None and len(boxes):
            xyxy = boxes.xyxy.float().cpu().numpy()
            conf = boxes.conf.float().cpu().numpy()
            kps = res.keypoints.data.float().cpu().numpy() if res.keypoints is not None else None
            for i in range(len(xyxy)):
                x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
                x1, x2 = max(0.0, x1), min(float(w), x2)
                y1, y2 = max(0.0, y1), min(float(h), y2)
                if x2 - x1 < 2 or y2 - y1 < 2:
                    continue
                dets.append({
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float(conf[i]),
                    'keypoints': kps[i].tolist() if kps is not None else None,
                    'appearance': color_hist(frame_bgr, (x1, y1, x2, y2), self.cfg['appearance']),
                })
        # deterministic order: left-to-right, then top-to-bottom
        dets.sort(key=lambda d: (round(d['bbox'][0], 1), round(d['bbox'][1], 1)))
        return {'width': w, 'height': h, 'image_stats': stats, 'detections': dets}


def image_stats(frame_bgr):
    small = cv2.resize(frame_bgr, (480, 270), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return {
        'brightness': float(gray.mean()),
        'contrast': float(gray.std()),
        'sharpness': float(cv2.Laplacian(gray, cv2.CV_64F).var()),
    }


def color_hist(frame_bgr, box, cfg):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    scale = cfg['crop_max_side'] / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [cfg['h_bins'], cfg['s_bins']], [0, 180, 0, 256]).flatten()
    total = hist.sum()
    return (hist / total).astype(np.float32) if total > 0 else None
