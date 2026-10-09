"""Observable CV features for one camera (cv-state-v1).

Everything here is an *observation* derived from the canonical frames: geometry, sampled motion,
posture proxies, pairwise proximity/motion proxies, generic scene entry/exit, quality.
No event semantics (fall / fight / trespass ...) are produced in this module.

Units
  fh  = frame-height units (pixels / frame height); x and y both divided by frame height.
  bh  = body heights (pixels / reference standing bbox height of that person).
  All rates use the *actual* timestamp difference between the sparse samples.
Unknown values are None (JSON null), never False/0 by default.
"""
import math
import statistics

import numpy as np

from .utils import clip01, reliability_label, rnd

KP = {'nose': 0, 'ls': 5, 'rs': 6, 'le': 7, 're': 8, 'lw': 9, 'rw': 10,
      'lh': 11, 'rh': 12, 'lk': 13, 'rk': 14, 'la': 15, 'ra': 16}
LOW_SET = ('crouched', 'low_posture', 'horizontal')


# ----------------------------------------------------------------------------- per detection
def _mid(kp, vis, a, b):
    pts = [kp[i, :2] for i in (a, b) if vis[i]]
    return np.mean(pts, axis=0) if pts else None


def pose_geometry(det, cfg):
    b = det['bbox']
    w, h = b[2] - b[0], b[3] - b[1]
    aspect = h / w if w > 0 else None
    g = {'aspect_ratio': aspect, 'keypoint_visible_count': 0, 'keypoint_visibility': 0.0,
         'torso_angle_deg': None, 'body_orientation_angle_deg': None,
         'hip_height_normalized': None, 'shoulder_height_normalized': None,
         'leg_extension_ratio': None, 'torso_length_px': None,
         'upright_score': None, 'horizontal_score': None, 'crouched_score': None}
    if det.get('keypoints') is None:
        return g
    kp = np.asarray(det['keypoints'], dtype=float)
    vis = kp[:, 2] >= cfg['keypoints']['visible_conf']
    g['keypoint_visible_count'] = int(vis.sum())
    g['keypoint_visibility'] = float(vis.sum() / 17.0)
    if vis.sum() < cfg['keypoints']['min_visible_for_pose']:
        return g
    pts = kp[vis, :2]
    if len(pts) >= 5:
        cov = np.cov((pts - pts.mean(axis=0)).T)
        evals, evecs = np.linalg.eigh(cov)
        ax = evecs[:, int(np.argmax(evals))]
        g['body_orientation_angle_deg'] = math.degrees(math.atan2(abs(ax[0]), abs(ax[1])))
    S = _mid(kp, vis, KP['ls'], KP['rs'])
    P = _mid(kp, vis, KP['lh'], KP['rh'])
    if S is None or P is None:
        return g
    L = float(np.linalg.norm(S - P))
    if L < 1.0:
        return g
    cos_up = float(np.clip((P[1] - S[1]) / L, -1.0, 1.0))
    g['torso_angle_deg'] = math.degrees(math.acos(cos_up))
    g['torso_length_px'] = L
    g['hip_height_normalized'] = (b[3] - P[1]) / h
    g['shoulder_height_normalized'] = (b[3] - S[1]) / h
    A = _mid(kp, vis, KP['la'], KP['ra'])
    if A is not None:
        g['leg_extension_ratio'] = (A[1] - P[1]) / L
    else:
        K = _mid(kp, vis, KP['lk'], KP['rk'])
        if K is not None:
            g['leg_extension_ratio'] = 2.0 * (K[1] - P[1]) / L
    cos_pos = max(0.0, cos_up)
    aspect_up = clip01((aspect - 1.0) / 1.0) if aspect else 0.0
    aspect_flat = clip01((1.2 - aspect) / 0.7) if aspect else 0.0
    leg = g['leg_extension_ratio']
    if leg is not None:
        leg_up = clip01((leg - 0.6) / 0.9)
        leg_fold = 1.0 - clip01((leg - 0.4) / 0.8)
        g['upright_score'] = 0.5 * cos_pos + 0.25 * aspect_up + 0.25 * leg_up
        g['crouched_score'] = cos_pos * leg_fold * (1.0 - 0.5 * aspect_flat)
    else:
        g['upright_score'] = 0.6 * cos_pos + 0.4 * aspect_up
    g['horizontal_score'] = 0.5 * (1.0 - cos_pos) + 0.5 * aspect_flat
    return g


def posture_label(g, body_height_ratio, cfg):
    pc = cfg['posture']
    if g['upright_score'] is None:
        if g['aspect_ratio'] is not None and g['aspect_ratio'] < pc['bbox_only_horizontal_aspect']:
            return 'horizontal', pc['bbox_only_confidence'], 'bbox_only'
        return 'unknown', None, 'insufficient_keypoints'
    scores = {'standing': g['upright_score'], 'horizontal': g['horizontal_score'], 'crouched': g['crouched_score'] or 0.0}
    order = sorted(scores, key=lambda k: (-scores[k], k))
    best = order[0]
    conf = scores[best] * (0.5 + 0.5 * min(1.0, g['keypoint_visible_count'] / 12.0))
    label = best
    if best in ('crouched', 'horizontal') and abs(scores['crouched'] - scores['horizontal']) < pc['ambiguity_margin']:
        label = 'low_posture'
    if best == 'standing' and body_height_ratio is not None and body_height_ratio < pc['low_height_ratio']:
        label, conf = 'low_posture', conf * 0.8
    if conf < pc['min_confidence']:
        return 'unknown', conf, 'low_confidence'
    return label, conf, 'keypoints'


# ----------------------------------------------------------------------------- helpers
def _center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _touches_edge(b, W, H, m):
    return b[0] <= m * W or b[2] >= (1 - m) * W or b[1] <= m * H or b[3] >= (1 - m) * H


def _norm_box(b, W, H):
    return [rnd(b[0] / W), rnd(b[1] / H), rnd(b[2] / W), rnd(b[3] / H)]


def _inter_over_min(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    m = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / m if m > 0 else 0.0


# ----------------------------------------------------------------------------- camera
class CameraFeatureExtractor:
    def __init__(self, cfg):
        self.cfg = cfg

    def extract(self, camera_id, frames, tracks):
        cfg = self.cfg
        W, H = frames[0]['width'], frames[0]['height']
        times = [f['timestamp_sec'] for f in frames]
        intervals = [b - a for a, b in zip(times, times[1:])]
        self.ctx = {'W': W, 'H': H, 'times': times, 'n': len(frames),
                    'interval': statistics.median(intervals) if intervals else None}
        for f in frames:
            for k, d in enumerate(f['detections']):
                d['_det_index'] = k
                d['geom'] = pose_geometry(d, cfg)
        track_objs = []
        for tr in tracks:
            obs = [(fi, frames[fi]['detections'][j]) for fi, j in tr['obs']]
            self._assign_reference_heights(obs)
            for fi, d in obs:
                lab, conf, basis = posture_label(d['geom'], d['body_height_ratio'], cfg)
                d['posture'] = {'label': lab, 'confidence': conf, 'basis': basis}
            track_objs.append({'track_id': tr['track_id'], 'obs': obs})
        track_states = [self._track_features(t) for t in track_objs]
        fragment_links = self._fragment_links(track_objs)
        pairwise = self._pairwise(track_objs)
        scene = self._scene(track_objs, fragment_links)
        quality = self._quality(frames, track_objs, track_states, scene)
        return {
            'camera_id': camera_id,
            'image_size': [W, H],
            'frame_count': len(frames),
            'duration_sec': rnd(times[-1] + 1.0 / 30.0) if times else None,
            'sampling': {
                'timestamps_sec': [rnd(t) for t in times],
                'median_interval_sec': rnd(self.ctx['interval']),
                'max_interval_sec': rnd(max(intervals)) if intervals else None,
                'note': 'Sparse uniform samples; motion values are sampled displacements over actual timestamp deltas, not continuous-video measurements.',
            },
            'frames': [self._frame_out(f, W, H) for f in frames],
            'detection_summary': self._detection_summary(frames),
            'tracks': track_states,
            'pairwise_interactions': pairwise,
            'scene_observations': scene,
            'quality': quality,
        }

    # ------------------------------------------------------------------ reference heights
    def _assign_reference_heights(self, obs):
        win = self.cfg['posture']['reference_window_sec']
        heights = [d['bbox'][3] - d['bbox'][1] for _, d in obs]
        p90 = float(np.percentile(heights, 90))
        times = self.ctx['times']
        upright = [(times[fi], d['bbox'][3] - d['bbox'][1]) for fi, d in obs
                   if d['geom']['upright_score'] is not None and d['geom']['upright_score'] >= 0.6]
        for fi, d in obs:
            near = [h for t, h in upright if abs(t - times[fi]) <= win]
            ref = max(near) if near else p90
            d['ref_height'] = max(ref, 1.0)
            d['body_height_ratio'] = (d['bbox'][3] - d['bbox'][1]) / d['ref_height']

    # ------------------------------------------------------------------ track
    def _intervals(self, obs):
        times, H = self.ctx['times'], self.ctx['H']
        out = []
        for (fa, da), (fb, db) in zip(obs, obs[1:]):
            dt = times[fb] - times[fa]
            ca, cb = _center(da['bbox']), _center(db['bbox'])
            dx, dy = cb[0] - ca[0], cb[1] - ca[1]
            px = math.hypot(dx, dy)
            ref = (da['ref_height'] + db['ref_height']) / 2.0
            out.append({'t0': times[fa], 't1': times[fb], 'dt': dt, 'dx': dx, 'dy': dy,
                        'disp_fh': px / H, 'disp_bh': px / ref, 'speed_fh': px / H / dt, 'speed_bh': px / ref / dt})
        return out

    def _track_features(self, tr):
        cfg, times, W, H = self.cfg, self.ctx['times'], self.ctx['W'], self.ctx['H']
        obs = tr['obs']
        n_obs = len(obs)
        fi0, fi1 = obs[0][0], obs[-1][0]
        span_frames = fi1 - fi0 + 1
        links = [d['link'] for _, d in obs[1:] if d.get('link')]
        gaps = [times[b[0]] - times[a[0]] for a, b in zip(obs, obs[1:])]
        assoc = statistics.fmean(l['affinity'] for l in links) if links else None
        ambiguous = sum(1 for l in links if l['ambiguous'])
        rel_score = None
        if n_obs >= 2:
            rel_score = (assoc or 0) * (n_obs / span_frames) * min(1.0, n_obs / cfg['tracker']['min_reliable_observations'])
            rel_score *= (1.0 - 0.5 * ambiguous / max(1, len(links)))
        reliability = {
            'association_confidence': rnd(assoc),
            'observed_frames': n_obs,
            'visible_fraction': rnd(n_obs / span_frames),
            'max_gap_sec': rnd(max(gaps)) if gaps else None,
            'ambiguous_links': ambiguous,
            'reliability_score': rnd(rel_score),
            'reliability_label': 'low' if n_obs < cfg['tracker']['min_reliable_observations'] else reliability_label(rel_score, cfg['quality']['reliability_labels']),
        }
        boxes = [d['bbox'] for _, d in obs]
        centers = [_center(b) for b in boxes]
        areas = [(b[2] - b[0]) * (b[3] - b[1]) / (W * H) for b in boxes]
        geometry = {
            'bbox_center_x': rnd(statistics.fmean(c[0] for c in centers) / W),
            'bbox_center_y': rnd(statistics.fmean(c[1] for c in centers) / H),
            'bbox_width': rnd(statistics.fmean(b[2] - b[0] for b in boxes) / W),
            'bbox_height': rnd(statistics.fmean(b[3] - b[1] for b in boxes) / H),
            'bbox_area_ratio': rnd(statistics.fmean(areas)),
            'reference_height': rnd(statistics.fmean(d['ref_height'] for _, d in obs) / H),
            'center_path': [[rnd(times[fi]), rnd(c[0] / W), rnd(c[1] / H)] for (fi, _), c in zip(obs, centers)],
            'bbox_area_change': rnd((areas[-1] - areas[0]) / areas[0]) if areas[0] > 0 else None,
            'vertical_position_change': rnd((centers[-1][1] - centers[0][1]) / H),
        }
        iv = self._intervals(obs)
        low_thr = cfg['motion']['low_motion_body_heights_per_sec']
        if iv:
            dir_changes, prev = 0, None
            for s in iv:
                if s['disp_bh'] < cfg['motion']['min_segment_body_heights']:
                    continue
                ang = math.atan2(s['dy'], s['dx'])
                if prev is not None:
                    diff = abs((ang - prev + math.pi) % (2 * math.pi) - math.pi)
                    if math.degrees(diff) > cfg['motion']['direction_change_deg']:
                        dir_changes += 1
                prev = ang
            net = math.hypot(centers[-1][0] - centers[0][0], centers[-1][1] - centers[0][1]) / H
            motion = {
                'units': 'fh = frame heights; bh = body heights; per second of actual sample-time delta',
                'normalized_speed_mean': rnd(statistics.fmean(s['speed_fh'] for s in iv)),
                'normalized_speed_max': rnd(max(s['speed_fh'] for s in iv)),
                'body_height_speed_mean': rnd(statistics.fmean(s['speed_bh'] for s in iv)),
                'body_height_speed_max': rnd(max(s['speed_bh'] for s in iv)),
                'displacement_total': rnd(sum(s['disp_fh'] for s in iv)),
                'net_displacement': rnd(net),
                'direction_change_count': dir_changes,
                'stationary_fraction': rnd(sum(s['speed_bh'] < low_thr for s in iv) / len(iv)),
            }
        else:
            motion = {'units': 'fh = frame heights; bh = body heights; per second of actual sample-time delta',
                      'normalized_speed_mean': None, 'normalized_speed_max': None,
                      'body_height_speed_mean': None, 'body_height_speed_max': None,
                      'displacement_total': None, 'net_displacement': None,
                      'direction_change_count': None, 'stationary_fraction': None}
        posture = self._posture_summary(obs)
        vt = self._vertical_transition(obs)
        low = self._low_motion(obs, iv, vt)
        return {
            'track_id': tr['track_id'],
            'reliability': reliability,
            'detection': {
                'first_seen_sec': rnd(times[fi0]),
                'last_seen_sec': rnd(times[fi1]),
                'observed_frames': n_obs,
                'visible_fraction': rnd(n_obs / span_frames),
                'visible_fraction_of_clip': rnd(n_obs / self.ctx['n']),
                'mean_detection_confidence': rnd(statistics.fmean(d['confidence'] for _, d in obs)),
            },
            'observations': [[fi, frame_det_index(d)] for fi, d in obs],
            'geometry': geometry,
            'motion': motion,
            'posture': posture,
            'vertical_transition': vt,
            'low_motion': low,
        }

    def _posture_summary(self, obs):
        times = self.ctx['times']
        labels = [d['posture']['label'] for _, d in obs]
        counts = {k: labels.count(k) for k in ('standing', 'crouched', 'low_posture', 'horizontal', 'unknown')}
        known = len(obs) - counts['unknown']

        def mean_of(key):
            vals = [d['geom'][key] for _, d in obs if d['geom'][key] is not None]
            return rnd(statistics.fmean(vals)) if vals else None
        return {
            'pose_observed_fraction': rnd(sum(1 for _, d in obs if d['geom']['upright_score'] is not None) / len(obs)),
            'known_posture_observations': known,
            'posture_counts': counts,
            'low_or_horizontal_fraction': rnd(sum(counts[k] for k in LOW_SET) / known) if known else None,
            'mean_torso_angle_deg': mean_of('torso_angle_deg'),
            'mean_body_orientation_angle_deg': mean_of('body_orientation_angle_deg'),
            'mean_upright_score': mean_of('upright_score'),
            'mean_horizontal_score': mean_of('horizontal_score'),
            'mean_crouched_score': mean_of('crouched_score'),
            'timeline': [[rnd(times[fi]), d['posture']['label'], rnd(d['posture']['confidence'])] for fi, d in obs],
        }

    def _drop(self, da, db):
        """Downward change (bh) between two detections: hip drop if both have hips, else bbox-top drop."""
        ref = da['ref_height']
        ga, gb = da['geom'], db['geom']
        if ga['hip_height_normalized'] is not None and gb['hip_height_normalized'] is not None:
            ya = da['bbox'][3] - ga['hip_height_normalized'] * (da['bbox'][3] - da['bbox'][1])
            yb = db['bbox'][3] - gb['hip_height_normalized'] * (db['bbox'][3] - db['bbox'][1])
            return (yb - ya) / ref, 'hip'
        return (db['bbox'][1] - da['bbox'][1]) / ref, 'bbox_top'

    def _vertical_transition(self, obs):
        cfg, times = self.cfg, self.ctx['times']
        vc = cfg['vertical_transition']
        known = [(fi, d) for fi, d in obs if d['posture']['label'] != 'unknown']
        empty = {'upright_to_low_transition': None, 'upright_to_horizontal_transition': None,
                 'max_downward_change': None, 'downward_change_basis': None,
                 'transition_start_sec': None, 'transition_end_sec': None, 'transition_duration_sec': None,
                 'from_posture': None, 'to_posture': None, 'confidence': None,
                 'temporal_resolution_sec': rnd(self.ctx['interval'])}
        if len(known) < vc['min_known_posture_obs']:
            return empty
        best = None
        any_h = False
        for a in range(len(known)):
            fa, da = known[a]
            if da['posture']['label'] != 'standing':
                continue
            for b in range(a + 1, len(known)):
                fb, db = known[b]
                dt = times[fb] - times[fa]
                if dt > vc['max_window_sec']:
                    break
                if db['posture']['label'] not in LOW_SET:
                    continue
                drop, basis = self._drop(da, db)
                any_h = any_h or db['posture']['label'] == 'horizontal'
                conf = min(da['posture']['confidence'], db['posture']['confidence'])
                key = (drop, -dt)
                if best is None or key > best[0]:
                    best = (key, fa, fb, da, db, drop, basis, conf)
        out = dict(empty)
        out['upright_to_low_transition'] = best is not None
        out['upright_to_horizontal_transition'] = any_h
        if best is None:
            return out
        _, fa, fb, da, db, drop, basis, conf = best
        link_affs = [d['link']['affinity'] for fi, d in obs if fa < fi <= fb and d.get('link')]
        link_factor = statistics.fmean(link_affs) if link_affs else 0.5
        out.update({
            'max_downward_change': rnd(drop), 'downward_change_basis': basis,
            'transition_start_sec': rnd(times[fa]), 'transition_end_sec': rnd(times[fb]),
            'transition_duration_sec': rnd(times[fb] - times[fa]),
            'from_posture': da['posture']['label'], 'to_posture': db['posture']['label'],
            'confidence': rnd(conf * (0.5 + 0.5 * link_factor)),
        })
        return out

    def _low_motion(self, obs, iv, vt):
        thr = self.cfg['motion']['low_motion_body_heights_per_sec']
        times = self.ctx['times']
        res = {'semantics': 'low sampled displacement between sparse samples; not a claim of motionlessness',
               'low_motion_fraction': None, 'longest_low_motion_interval_sec': None,
               'post_transition_low_motion_sec': None, 'post_transition_low_posture_sec': None,
               'post_transition_observed_sec': None}
        if not iv:
            return res
        total = sum(s['dt'] for s in iv)
        res['low_motion_fraction'] = rnd(sum(s['dt'] for s in iv if s['speed_bh'] < thr) / total)
        longest = run = 0.0
        for s in iv:
            run = run + s['dt'] if s['speed_bh'] < thr else 0.0
            longest = max(longest, run)
        res['longest_low_motion_interval_sec'] = rnd(longest)
        if vt.get('transition_end_sec') is not None:
            t_end = vt['transition_end_sec']
            post = [s for s in iv if s['t0'] >= t_end - 1e-9]
            acc = 0.0
            for s in post:
                if s['speed_bh'] >= thr:
                    break
                acc += s['dt']
            res['post_transition_low_motion_sec'] = rnd(acc)
            last_low = t_end
            for fi, d in obs:
                if times[fi] <= t_end + 1e-9:
                    continue
                if d['posture']['label'] == 'standing':
                    break
                last_low = times[fi]
            res['post_transition_low_posture_sec'] = rnd(last_low - t_end)
            res['post_transition_observed_sec'] = rnd(times[obs[-1][0]] - t_end)
        return res

    # ------------------------------------------------------------------ fragments
    def _fragment_links(self, tracks):
        tc, times = self.cfg['tracker'], self.ctx['times']
        links = []
        for a in tracks:
            fa, da = a['obs'][-1]
            for b in tracks:
                if b is a:
                    continue
                fb, db = b['obs'][0]
                gap = times[fb] - times[fa]
                if gap <= 0 or gap > tc['fragment_link_max_gap_sec']:
                    continue
                ca, cb = _center(da['bbox']), _center(db['bbox'])
                dist = math.hypot(ca[0] - cb[0], ca[1] - cb[1]) / da['ref_height']
                if dist > tc['fragment_link_max_distance_body_heights']:
                    continue
                last_up = next((d for fi, d in reversed(a['obs']) if d['posture']['label'] == 'standing'
                                and times[fa] - times[fi] <= self.cfg['vertical_transition']['max_window_sec']), None)
                first_low = next((d for fi, d in b['obs'][:3] if d['posture']['label'] in LOW_SET), None)
                posture_change = None
                if last_up is not None and first_low is not None:
                    drop, basis = self._drop(last_up, first_low)
                    posture_change = {'from_posture': 'standing', 'to_posture': first_low['posture']['label'],
                                      'downward_change': rnd(drop), 'downward_change_basis': basis,
                                      'confidence': rnd(min(last_up['posture']['confidence'], first_low['posture']['confidence']))}
                links.append({'from_track': a['track_id'], 'to_track': b['track_id'], 'gap_sec': rnd(gap),
                              'from_end_sec': rnd(times[fa]), 'to_start_sec': rnd(times[fb]),
                              'distance_body_heights': rnd(dist), 'posture_change': posture_change,
                              'identity_confirmed': False})
        return links

    # ------------------------------------------------------------------ pairwise
    def _pairwise(self, tracks):
        ic, times, H = self.cfg['interaction'], self.ctx['times'], self.ctx['H']
        vc = self.cfg['keypoints']['visible_conf']
        out = []
        for i in range(len(tracks)):
            for j in range(i + 1, len(tracks)):
                A, B = tracks[i], tracks[j]
                ma, mb = dict(A['obs']), dict(B['obs'])
                co = sorted(set(ma) & set(mb))
                if len(co) < ic['min_co_observed']:
                    continue
                rows = []
                for fi in co:
                    da, db = ma[fi], mb[fi]
                    ref = (da['ref_height'] + db['ref_height']) / 2.0
                    ca, cb = _center(da['bbox']), _center(db['bbox'])
                    d = math.hypot(ca[0] - cb[0], ca[1] - cb[1]) / ref
                    rows.append({'fi': fi, 't': times[fi], 'd': d, 'ov': _inter_over_min(da['bbox'], db['bbox']),
                                 'da': da, 'db': db, 'ca': ca, 'cb': cb, 'ref': ref})
                close_thr = ic['close_distance_body_heights']
                close = [r['d'] < close_thr for r in rows]
                approach_rates, rel_all, rel_close, close_dur = [], [], [], 0.0
                limb_speeds = []
                for r0, r1, c0, c1 in zip(rows, rows[1:], close, close[1:]):
                    dt = r1['t'] - r0['t']
                    if dt > self.cfg['tracker']['max_gap_sec']:
                        continue
                    approach_rates.append(-(r1['d'] - r0['d']) / dt)
                    va = ((r1['ca'][0] - r0['ca'][0]) / dt, (r1['ca'][1] - r0['ca'][1]) / dt)
                    vb = ((r1['cb'][0] - r0['cb'][0]) / dt, (r1['cb'][1] - r0['cb'][1]) / dt)
                    rel = math.hypot(va[0] - vb[0], va[1] - vb[1]) / ((r0['ref'] + r1['ref']) / 2.0)
                    rel_all.append(rel)
                    if c0 or c1:
                        rel_close.append(rel)
                        for key in ('da', 'db'):
                            s = _limb_speed(r0[key], r1[key], dt, vc)
                            if s is not None:
                                limb_speeds.append(s)
                    if c0 and c1:
                        close_dur += dt
                approaches, state_far = 0, True
                for r in rows:
                    if state_far and r['d'] < close_thr:
                        approaches += 1
                        state_far = False
                    elif not state_far and r['d'] >= close_thr * ic['far_hysteresis']:
                        state_far = True
                close_rows = [r for r, c in zip(rows, close) if c]
                arm_scores, wrist_in = [], []
                for r in close_rows:
                    s1 = _arm_toward(r['da'], r['cb'], vc, ic)
                    s2 = _arm_toward(r['db'], r['ca'], vc, ic)
                    vals = [s for s in (s1, s2) if s is not None]
                    if vals:
                        arm_scores.append(max(vals))
                    w1 = _wrist_in_box(r['da'], r['db']['bbox'], vc, ic['wrist_bbox_expand'])
                    w2 = _wrist_in_box(r['db'], r['da']['bbox'], vc, ic['wrist_bbox_expand'])
                    if w1 is not None or w2 is not None:
                        wrist_in.append(bool(w1) or bool(w2))
                rel_close_mean = statistics.fmean(rel_close) if rel_close else None
                max_rate = max(approach_rates) if approach_rates else None
                terms = {
                    'close_bbox_distance': (sum(1 for r in close_rows if r['ov'] > 0) / len(rows)) if rows else None,
                    'pose_overlap': (sum(wrist_in) / len(wrist_in)) if wrist_in else None,
                    'rapid_relative_motion': clip01(rel_close_mean / ic['relative_motion_ref_body_heights_per_sec']) if rel_close_mean is not None else None,
                }
                weights = {'close_bbox_distance': 0.4, 'pose_overlap': 0.3, 'rapid_relative_motion': 0.3}
                avail = {k: v for k, v in terms.items() if v is not None}
                contact = sum(weights[k] * v for k, v in avail.items()) / sum(weights[k] for k in avail) if avail else None
                if contact is not None and not close_rows:
                    contact = 0.0
                out.append({
                    'pair_id': f"{A['track_id']}-{B['track_id']}",
                    'track_a': A['track_id'], 'track_b': B['track_id'],
                    'co_observed_frames': len(rows),
                    'co_observed_start_sec': rnd(rows[0]['t']), 'co_observed_end_sec': rnd(rows[-1]['t']),
                    'minimum_normalized_distance': rnd(min(r['d'] for r in rows)),
                    'mean_normalized_distance': rnd(statistics.fmean(r['d'] for r in rows)),
                    'distance_units': 'body heights (centre-to-centre / mean reference height)',
                    'distance_series': [[rnd(r['t']), rnd(r['d']), c] for r, c in zip(rows, close)],
                    'approach_rate': rnd(statistics.fmean(approach_rates)) if approach_rates else None,
                    'max_approach_rate': rnd(max_rate),
                    'rapid_approach_score': rnd(clip01(max_rate / ic['rapid_approach_ref_body_heights_per_sec'])) if max_rate is not None else None,
                    'close_proximity_fraction': rnd(len(close_rows) / len(rows)),
                    'close_duration_sec': rnd(close_dur),
                    'first_close_sec': rnd(close_rows[0]['t']) if close_rows else None,
                    'last_close_sec': rnd(close_rows[-1]['t']) if close_rows else None,
                    'bbox_overlap_fraction': rnd(sum(1 for r in rows if r['ov'] > 0) / len(rows)),
                    'mean_bbox_overlap': rnd(statistics.fmean(r['ov'] for r in rows)),
                    'repeated_approach_count': approaches,
                    'relative_motion_intensity': rnd(statistics.fmean(rel_all)) if rel_all else None,
                    'relative_motion_intensity_when_close': rnd(rel_close_mean),
                    'relative_motion_max': rnd(max(rel_all)) if rel_all else None,
                    'arm_extension_toward_other_score': rnd(statistics.fmean(arm_scores)) if arm_scores else None,
                    'arm_extension_toward_other_max': rnd(max(arm_scores)) if arm_scores else None,
                    'rapid_limb_motion_score': rnd(clip01(max(limb_speeds) / ic['limb_speed_ref_torso_per_sec'])) if limb_speeds else None,
                    'limb_motion_note': 'wrist displacement relative to torso between sparse samples; aliasing likely',
                    'contact_proxy': {
                        'score': rnd(contact),
                        'terms': {k: rnd(v) for k, v in terms.items()},
                        'basis': [k for k, v in terms.items() if v is not None and v >= ic['contact_basis_min']],
                        'note': '2D image-plane proxy only; physical contact is not established',
                    },
                    'reliability': rnd(min(_track_rel(A), _track_rel(B))),
                    'temporal_resolution_sec': rnd(self.ctx['interval']),
                })
        return out

    # ------------------------------------------------------------------ scene
    def _scene(self, tracks, fragment_links):
        sc, times, W, H, n = self.cfg['scene'], self.ctx['times'], self.ctx['W'], self.ctx['H'], self.ctx['n']
        entries, exits, transitions = [], [], []
        for tr in tracks:
            (f0, d0), (f1, d1) = tr['obs'][0], tr['obs'][-1]
            if f0 == 0:
                etype = 'present_at_clip_start'
            elif _touches_edge(d0['bbox'], W, H, sc['edge_margin']):
                etype = 'edge_entry'
            else:
                etype = 'appears_mid_frame'
            if f1 == n - 1:
                xtype = 'present_at_clip_end'
            elif _touches_edge(d1['bbox'], W, H, sc['edge_margin']):
                xtype = 'edge_exit'
            else:
                xtype = 'disappears_mid_frame'
            entries.append({'track_id': tr['track_id'], 'time_sec': rnd(times[f0]), 'type': etype})
            exits.append({'track_id': tr['track_id'], 'time_sec': rnd(times[f1]), 'type': xtype})
            c0, c1 = _center(d0['bbox']), _center(d1['bbox'])
            net = math.hypot(c1[0] - c0[0], c1[1] - c0[1]) / H
            if net >= sc['large_transition_frame_heights']:
                transitions.append({'track_id': tr['track_id'], 'start_sec': rnd(times[f0]), 'end_sec': rnd(times[f1]),
                                    'from_xy': [rnd(c0[0] / W), rnd(c0[1] / H)], 'to_xy': [rnd(c1[0] / W), rnd(c1[1] / H)],
                                    'net_displacement_fh': rnd(net)})
        occl = [x for x in exits if x['type'] == 'disappears_mid_frame']
        return {
            'track_entries': entries,
            'track_exits': exits,
            'large_spatial_transitions': transitions,
            'occlusion_candidates': [{'track_id': x['track_id'], 'time_sec': x['time_sec'],
                                      'reappearance_candidate': next((l['to_track'] for l in fragment_links if l['from_track'] == x['track_id']), None)}
                                     for x in occl],
            'fragment_links': fragment_links,
            'boundary_crossing': None,
            'boundary_crossing_reliability': 'unavailable',
            'scene_semantics': {'zones': None, 'reliability': 'unavailable',
                                'note': 'Generic CV layer has no gate/wall/restricted-area knowledge; no per-scene ROIs are configured.'},
        }

    # ------------------------------------------------------------------ quality / summary
    def _detection_summary(self, frames):
        counts = [len(f['detections']) for f in frames]
        confs = [d['confidence'] for f in frames for d in f['detections']]
        return {
            'person_count_min': min(counts), 'person_count_max': max(counts),
            'person_count_median': rnd(statistics.median(counts)),
            'person_count_mean': rnd(statistics.fmean(counts)),
            'frames_with_person_fraction': rnd(sum(c > 0 for c in counts) / len(counts)),
            'total_detections': len(confs),
            'mean_detection_confidence': rnd(statistics.fmean(confs)) if confs else None,
        }

    def _quality(self, frames, tracks, track_states, scene):
        qc, W, H = self.cfg['quality'], self.ctx['W'], self.ctx['H']
        dets = [d for f in frames for d in f['detections']]
        stats = [f['image_stats'] for f in frames]
        dark = sum(s['brightness'] < qc['dark_brightness'] for s in stats) / len(stats)
        q = {
            'mean_brightness': rnd(statistics.fmean(s['brightness'] for s in stats), 2),
            'mean_contrast': rnd(statistics.fmean(s['contrast'] for s in stats), 2),
            'mean_sharpness': rnd(statistics.fmean(s['sharpness'] for s in stats), 2),
            'dark_frame_fraction': rnd(dark),
            'temporal_resolution_sec': rnd(self.ctx['interval']),
        }
        if not dets:
            q.update({'mean_person_box_area_ratio': None, 'small_person_fraction': None, 'pose_visibility': None,
                      'detection_dropout_rate': None, 'track_fragmentation': None, 'occlusion_proxy': None,
                      'overall_cv_reliability': None, 'overall_cv_reliability_label': 'unknown',
                      'note': 'No person detections; absence claims depend on image quality and sparse sampling.'})
            return q
        areas = [(d['bbox'][2] - d['bbox'][0]) * (d['bbox'][3] - d['bbox'][1]) / (W * H) for d in dets]
        small = sum((d['bbox'][3] - d['bbox'][1]) / H < qc['small_person_height'] for d in dets) / len(dets)
        pose_vis = statistics.fmean(d['geom']['keypoint_visibility'] for d in dets)
        multi = [t for t in track_states if t['detection']['observed_frames'] >= 2]
        dropout = (1.0 - statistics.fmean(t['detection']['visible_fraction'] for t in multi)) if multi else None
        counts = sorted(len(f['detections']) for f in frames)
        p90 = counts[int(0.9 * (len(counts) - 1))]
        frag_ratio = len(multi) / max(1, p90)
        frag = clip01((frag_ratio - 1.0) / 3.0)
        overl = 0
        for f in frames:
            ds = f['detections']
            for a in range(len(ds)):
                if any(_inter_over_min(ds[a]['bbox'], ds[b]['bbox']) > qc['overlap_occlusion'] for b in range(len(ds)) if b != a):
                    overl += 1
        mid_disappear = len(scene['occlusion_candidates']) / max(1, len(tracks))
        occlusion = clip01(0.5 * overl / len(dets) + 0.5 * mid_disappear)
        mean_conf = statistics.fmean(d['confidence'] for d in dets)
        rel = (0.3 * mean_conf + 0.2 * pose_vis + 0.2 * (1.0 - (dropout or 0.0)) + 0.15 * (1.0 - frag) + 0.15 * (1.0 - occlusion))
        rel *= (1.0 - 0.5 * dark) * (1.0 - 0.3 * small)
        q.update({
            'mean_person_box_area_ratio': rnd(statistics.fmean(areas), 5),
            'small_person_fraction': rnd(small),
            'pose_visibility': rnd(pose_vis),
            'detection_dropout_rate': rnd(dropout),
            'track_fragmentation': rnd(frag),
            'track_fragmentation_ratio': rnd(frag_ratio),
            'occlusion_proxy': rnd(occlusion),
            'overall_cv_reliability': rnd(rel),
            'overall_cv_reliability_label': reliability_label(rel, qc['reliability_labels']),
        })
        return q

    def _frame_out(self, f, W, H):
        dets = []
        for k, d in enumerate(f['detections']):
            g = d['geom']
            kps = None
            if d.get('keypoints') is not None:
                kps = [[rnd(x / W), rnd(y / H), rnd(c, 3)] for x, y, c in d['keypoints']]
            dets.append({
                'det_index': k,
                'track_id': d.get('track_id'),
                'bbox_norm': _norm_box(d['bbox'], W, H),
                'confidence': rnd(d['confidence']),
                'keypoints_norm': kps,
                'link': {'affinity': rnd(d['link']['affinity']), 'ambiguous': d['link']['ambiguous'], 'gap_sec': rnd(d['link']['gap_sec'])} if d.get('link') else None,
                'posture': {
                    'label': d['posture']['label'], 'confidence': rnd(d['posture']['confidence']), 'basis': d['posture']['basis'],
                    'torso_angle_deg': rnd(g['torso_angle_deg'], 2), 'body_orientation_angle_deg': rnd(g['body_orientation_angle_deg'], 2),
                    'hip_height_normalized': rnd(g['hip_height_normalized']), 'shoulder_height_normalized': rnd(g['shoulder_height_normalized']),
                    'leg_extension_ratio': rnd(g['leg_extension_ratio']), 'body_height_ratio': rnd(d.get('body_height_ratio')),
                    'aspect_ratio': rnd(g['aspect_ratio']), 'keypoint_visibility': rnd(g['keypoint_visibility']),
                    'upright_score': rnd(g['upright_score']), 'horizontal_score': rnd(g['horizontal_score']),
                    'crouched_score': rnd(g['crouched_score']),
                },
            })
        s = f['image_stats']
        return {'index': f['index'], 'timestamp_sec': rnd(f['timestamp_sec']), 'frame_number': f['frame_number'],
                'person_count': len(dets), 'image_stats': {k: rnd(v, 2) for k, v in s.items()}, 'detections': dets}


def frame_det_index(d):
    return d['_det_index']


def _track_rel(tr):
    affs = [d['link']['affinity'] for _, d in tr['obs'][1:] if d.get('link')]
    return statistics.fmean(affs) if affs else 0.0


def _arm_toward(det, other_center, vc, ic):
    kp = det.get('keypoints')
    g = det['geom']
    if kp is None or g['torso_length_px'] is None:
        return None
    kp = np.asarray(kp)
    best = None
    for s, w in ((KP['ls'], KP['lw']), (KP['rs'], KP['rw'])):
        if kp[s, 2] < vc or kp[w, 2] < vc:
            continue
        v = kp[w, :2] - kp[s, :2]
        o = np.asarray(other_center) - kp[s, :2]
        nv, no = np.linalg.norm(v), np.linalg.norm(o)
        if nv < 1 or no < 1:
            continue
        ext = nv / g['torso_length_px']
        cos = float(v @ o / (nv * no))
        score = clip01((ext - ic['arm_extension_min']) / (ic['arm_extension_full'] - ic['arm_extension_min'])) * max(0.0, cos)
        best = score if best is None else max(best, score)
    return best


def _wrist_in_box(det, box, vc, expand):
    kp = det.get('keypoints')
    if kp is None:
        return None
    kp = np.asarray(kp)
    w, h = box[2] - box[0], box[3] - box[1]
    ex = (box[0] - expand * w, box[1] - expand * h, box[2] + expand * w, box[3] + expand * h)
    seen = False
    for k in (KP['lw'], KP['rw']):
        if kp[k, 2] < vc:
            continue
        seen = True
        if ex[0] <= kp[k, 0] <= ex[2] and ex[1] <= kp[k, 1] <= ex[3]:
            return True
    return False if seen else None


def _limb_speed(d0, d1, dt, vc):
    g0, g1 = d0['geom'], d1['geom']
    if d0.get('keypoints') is None or d1.get('keypoints') is None or g0['torso_length_px'] is None or g1['torso_length_px'] is None:
        return None
    k0, k1 = np.asarray(d0['keypoints']), np.asarray(d1['keypoints'])
    c0, c1 = _center(d0['bbox']), _center(d1['bbox'])
    L = (g0['torso_length_px'] + g1['torso_length_px']) / 2.0
    best = None
    for w in (KP['lw'], KP['rw']):
        if k0[w, 2] < vc or k1[w, 2] < vc:
            continue
        r0 = k0[w, :2] - np.asarray(c0)
        r1 = k1[w, :2] - np.asarray(c1)
        s = float(np.linalg.norm(r1 - r0)) / L / dt
        best = s if best is None else max(best, s)
    return best
