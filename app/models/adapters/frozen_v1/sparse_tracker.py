"""Timestamp-aware sparse association for uniform_total64_v1 frames (per camera only).

Frames are ~0.5-1.7 s apart, so continuous-video trackers (ByteTrack/BoT-SORT, Kalman with
30 FPS dynamics) are not used. Each frame's detections are matched to active tracks with a
deterministic Hungarian assignment on an affinity built from:
  * centre distance gated by actual timestamp delta (body heights / second),
  * bbox IoU, bbox size similarity,
  * pose-shape similarity (keypoints in bbox-normalised coordinates),
  * cheap HSV histogram similarity.
Uncertain links are refused (new track) or flagged ambiguous; fragments are never merged.
"""
import math

import numpy as np

try:
    from scipy.optimize import linear_sum_assignment
except ImportError:  # deterministic greedy fallback
    linear_sum_assignment = None


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def pose_shape_similarity(da, db, vis_conf, min_shared=6):
    ka, kb = da.get('keypoints'), db.get('keypoints')
    if ka is None or kb is None:
        return None
    ka, kb = np.asarray(ka), np.asarray(kb)
    shared = (ka[:, 2] >= vis_conf) & (kb[:, 2] >= vis_conf)
    if shared.sum() < min_shared:
        return None

    def norm(k, b):
        w, h = max(b[2] - b[0], 1.0), max(b[3] - b[1], 1.0)
        return np.stack([(k[:, 0] - b[0]) / w, (k[:, 1] - b[1]) / h], axis=1)

    d = np.linalg.norm(norm(ka, da['bbox'])[shared] - norm(kb, db['bbox'])[shared], axis=1).mean()
    return float(math.exp(-d / 0.15))


def hist_similarity(ha, hb):
    if ha is None or hb is None:
        return None
    return float(np.sum(np.sqrt(ha * hb)))  # Bhattacharyya coefficient in [0,1]


class SparseTracker:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tcfg = cfg['tracker']
        self.vis_conf = cfg['keypoints']['visible_conf']

    def affinity(self, track, det, t):
        last = track['last']
        dt = t - track['last_t']
        if dt <= 0 or dt > self.tcfg['max_gap_sec']:
            return None, None
        ba, bb = last['bbox'], det['bbox']
        ha, hb = ba[3] - ba[1], bb[3] - bb[1]
        ref_h = max((ha + hb) / 2.0, 1.0)
        ca, cb = center(ba), center(bb)
        dist = math.hypot(ca[0] - cb[0], ca[1] - cb[1]) / ref_h
        allowed = self.tcfg['gate_base_body_heights'] + self.tcfg['gate_speed_body_heights_per_sec'] * dt
        motion = 1.0 - dist / allowed
        if motion <= 0:
            return None, None
        area_a, area_b = (ba[2] - ba[0]) * ha, (bb[2] - bb[0]) * hb
        comps = {
            'motion': motion,
            'iou': iou(ba, bb),
            'size': math.sqrt(min(area_a, area_b) / max(area_a, area_b)) if max(area_a, area_b) > 0 else 0.0,
            'pose': pose_shape_similarity(last, det, self.vis_conf),
            'appearance': hist_similarity(last.get('appearance'), det.get('appearance')),
        }
        wsum = sum(self.tcfg['weights'][k] for k, v in comps.items() if v is not None)
        aff = sum(self.tcfg['weights'][k] * v for k, v in comps.items() if v is not None) / wsum
        return aff, comps

    def _assign(self, aff):
        n, m = aff.shape
        if n == 0 or m == 0:
            return []
        cost = np.where(np.isnan(aff), 1e6, 1.0 - aff)
        if linear_sum_assignment is not None:
            rows, cols = linear_sum_assignment(cost)
            pairs = list(zip(rows.tolist(), cols.tolist()))
        else:
            pairs, used_r, used_c = [], set(), set()
            for flat in np.argsort(cost, axis=None, kind='stable'):
                r, c = divmod(int(flat), m)
                if r not in used_r and c not in used_c and cost[r, c] < 1e6:
                    pairs.append((r, c)); used_r.add(r); used_c.add(c)
        return [(r, c) for r, c in pairs if not np.isnan(aff[r, c]) and aff[r, c] >= self.tcfg['min_affinity']]

    def run(self, frames):
        """frames: list of {'timestamp_sec', 'detections': [...]} sorted by time.
        Sets det['track_id'] and det['link'] in place; returns list of track dicts."""
        tracks = []
        for fi, frame in enumerate(frames):
            t = frame['timestamp_sec']
            dets = frame['detections']
            active = [tr for tr in tracks if 0 < t - tr['last_t'] <= self.tcfg['max_gap_sec']]
            aff = np.full((len(active), len(dets)), np.nan)
            for i, tr in enumerate(active):
                for j, d in enumerate(dets):
                    a, _ = self.affinity(tr, d, t)
                    if a is not None:
                        aff[i, j] = a
            matched = set()
            for i, j in self._assign(aff):
                tr, d = active[i], dets[j]
                best = aff[i, j]
                row = np.delete(aff[i, :], j)
                col = np.delete(aff[:, j], i)
                rivals = [v for v in np.concatenate([row, col]) if not np.isnan(v)]
                ambiguous = bool(rivals) and bool(best - max(rivals) < self.tcfg['ambiguity_margin'])
                d['track_id'] = tr['track_id']
                d['link'] = {'affinity': float(best), 'ambiguous': ambiguous, 'gap_sec': t - tr['last_t']}
                tr['obs'].append((fi, j))
                tr['last'], tr['last_t'] = d, t
                matched.add(j)
            for j, d in enumerate(dets):
                if j in matched:
                    continue
                tid = f'T{len(tracks) + 1:02d}'
                d['track_id'] = tid
                d['link'] = None
                tracks.append({'track_id': tid, 'obs': [(fi, j)], 'last': d, 'last_t': t})
        for tr in tracks:
            tr.pop('last', None)
            tr.pop('last_t', None)
        return tracks
