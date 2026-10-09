"""Deterministic serializer: Canonical CV State (cv-state-v1) -> Compact Decision State (compact-decision-state-v1).

Only observation summaries are emitted. Harness metadata (item_id, fingerprints, generator), P0 rule conclusions and any
label-like information are never copied. Same input -> byte-identical canonical JSON.
"""
from .utils import canonical_json, norm_float, sha256_bytes

LOW = ('crouched', 'low_posture', 'horizontal')
POSTURES = ('standing', 'crouched', 'low_posture', 'horizontal', 'unknown')


class CompactSerializer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.d = cfg['rounding_digits']
        self.limited = cfg['limited_reliability_features']

    def f(self, x):
        return norm_float(x, self.d)

    def proxy(self, value, feature):
        return {'value': self.f(value), 'reliability': 'limited', 'note': self.limited[feature]}

    # ------------------------------------------------------------------ public
    def serialize(self, state):
        cams = [self.camera(c) for c in state['cameras']]
        compact = {
            'schema_version': self.cfg['schema_version'],
            'task': state['input']['task'],
            'observation_window_sec': self.f(max(c['duration_sec'] for c in state['cameras'])),
            'cameras': [c for c, _ in cams],
            'cross_camera': self.cross(state['cross_camera'], {c['camera_id']: m for c, (_, m) in zip(state['cameras'], cams)}) if state['cross_camera'] else None,
        }
        self.check_forbidden(compact)
        return compact

    def model_input_text(self, compact):
        return self.cfg['model_input_preamble'].strip() + '\n\n' + canonical_json(compact)

    @staticmethod
    def digest(compact):
        return sha256_bytes(canonical_json(compact).encode('utf-8'))

    def check_forbidden(self, obj):
        bad = set()

        def walk(v):
            if isinstance(v, dict):
                for k, x in v.items():
                    if k in self.cfg['forbidden_keys']:
                        bad.add(k)
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(obj)
        if bad:
            raise ValueError(f'Forbidden keys in compact state: {sorted(bad)}')

    # ------------------------------------------------------------------ camera
    def camera(self, cam):
        lim = self.cfg['limits']
        ts = cam['tracks']
        sel_cfg = self.cfg['track_selection']
        scored = []
        for t in ts:
            r = t['reliability']
            if r['observed_frames'] < sel_cfg['min_observed_frames']:
                continue
            s = r['observed_frames'] * (r['reliability_score'] or 0.0) * (r['visible_fraction'] or 0.0)
            scored.append((-s, int(t['track_id'][1:]), t))
        scored.sort(key=lambda x: (x[0], x[1]))
        chosen = [t for _, _, t in scored[:lim['max_tracks_per_camera']]]
        ref = {t['track_id']: f"T{int(t['track_id'][1:])}" for t in chosen}
        scene = cam['scene_observations']
        entries = {e['track_id']: e['type'] for e in scene['track_entries']}
        exits = {e['track_id']: e['type'] for e in scene['track_exits']}
        transitions = {s['track_id'] for s in scene['large_spatial_transitions']}
        tracks = [self.track(t, ref[t['track_id']], entries, exits, transitions) for t in chosen]
        q, ds = cam['quality'], cam['detection_summary']
        out = {
            'camera': cam['camera_id'],
            'observation_window_sec': self.f(cam['duration_sec']),
            'sampling': {'frame_count': cam['frame_count'], 'median_interval_sec': self.f(cam['sampling']['median_interval_sec']),
                         'max_interval_sec': self.f(cam['sampling']['max_interval_sec'])},
            'quality': {
                'cv_reliability': self.f(q['overall_cv_reliability']), 'cv_reliability_label': q['overall_cv_reliability_label'],
                'pose_visibility': self.f(q['pose_visibility']), 'track_fragmentation': self.f(q['track_fragmentation']),
                'occlusion_proxy': self.f(q['occlusion_proxy']), 'detection_dropout_rate': self.f(q['detection_dropout_rate']),
                'small_person_fraction': self.f(q['small_person_fraction']), 'dark_frame_fraction': self.f(q['dark_frame_fraction']),
            },
            'people': {'count_min': ds['person_count_min'], 'count_max': ds['person_count_max'],
                       'count_median': self.f(ds['person_count_median']),
                       'frames_with_person_fraction': self.f(ds['frames_with_person_fraction']),
                       'tracks_total': len(ts), 'tracks_included': len(tracks)},
            'tracks': tracks,
            'interactions': self.interactions(cam['pairwise_interactions'], ref),
            'scene': self.scene(scene, ref),
        }
        return out, ref

    def track(self, t, ref, entries, exits, transitions):
        tl = t['posture']['timeline']
        n = len(tl)
        known = [x for x in tl if x[1] != 'unknown']
        vt, low, mo, r = t['vertical_transition'], t['low_motion'], t['motion'], t['reliability']
        if vt['upright_to_low_transition'] is None:
            trans = {'observed': None}
        elif not vt['upright_to_low_transition']:
            trans = {'observed': False}
        else:
            dc = vt['max_downward_change']
            trans = {
                'observed': True, 'from': vt['from_posture'], 'to': vt['to_posture'],
                'start_sec': self.f(vt['transition_start_sec']), 'end_sec': self.f(vt['transition_end_sec']),
                'duration_sec': self.f(vt['transition_duration_sec']),
                'downward_change_bh': self.proxy(dc, 'hip_based_downward_change') if vt['downward_change_basis'] == 'hip'
                else {'value': self.f(dc), 'reliability': 'normal', 'note': 'bbox-top drop'},
                'confidence': self.f(vt['confidence']),
            }
        return {
            'track_ref': ref,
            'reliability': self.f(r['reliability_score']), 'reliability_label': r['reliability_label'],
            'observed_frames': r['observed_frames'], 'visible_fraction': self.f(r['visible_fraction']),
            'ambiguous_links': r['ambiguous_links'],
            'first_seen_sec': self.f(t['detection']['first_seen_sec']), 'last_seen_sec': self.f(t['detection']['last_seen_sec']),
            'initial_posture': known[0][1] if known else None,
            'final_posture': known[-1][1] if known else None,
            'posture_distribution': {p: self.f(sum(1 for x in tl if x[1] == p) / n) for p in POSTURES},
            'strongest_vertical_transition': trans,
            'longest_low_posture_run_sec': self.f(self._longest_low_run(tl)),
            'post_transition_low_posture_sec': self.f(low['post_transition_low_posture_sec']),
            'motion': {
                'mean_speed_bh_per_sec': self.f(mo['body_height_speed_mean']), 'max_speed_bh_per_sec': self.f(mo['body_height_speed_max']),
                'net_displacement_fh': self.f(mo['net_displacement']), 'direction_change_count': mo['direction_change_count'],
                'stationary_fraction': self.f(mo['stationary_fraction']), 'low_motion_fraction': self.f(low['low_motion_fraction']),
                'longest_low_motion_interval_sec': self.f(low['longest_low_motion_interval_sec']),
                'large_spatial_transition': t['track_id'] in transitions,
            },
            'appearance': {
                'entry': entries.get(t['track_id']), 'exit': exits.get(t['track_id']),
                'entered_frame': entries.get(t['track_id']) in ('edge_entry', 'appears_mid_frame'),
                'exited_frame': exits.get(t['track_id']) in ('edge_exit', 'disappears_mid_frame'),
            },
        }

    @staticmethod
    def _longest_low_run(tl):
        """Longest contiguous run (sample times) of low/crouched/horizontal posture labels; unknown breaks a run."""
        best, start, prev = 0.0, None, None
        for t, lab, _ in tl:
            if lab in LOW:
                start = t if start is None else start
                prev = t
                best = max(best, prev - start)
            else:
                start = None
        return best

    def interactions(self, pairs, ref):
        sc = self.cfg['interaction_selection']
        cand = []
        for p in pairs:
            if p['track_a'] not in ref or p['track_b'] not in ref or p['co_observed_frames'] < sc['min_co_observed_frames']:
                continue
            s = (p['close_proximity_fraction'] or 0.0) * p['co_observed_frames'] * (p['reliability'] or 0.0)
            cand.append((-s, p['minimum_normalized_distance'] if p['minimum_normalized_distance'] is not None else 1e9, p['pair_id'], p))
        cand.sort(key=lambda x: (x[0], x[1], x[2]))
        out = []
        for _, _, _, p in cand[:self.cfg['limits']['max_interactions_per_camera']]:
            out.append({
                'tracks': [ref[p['track_a']], ref[p['track_b']]],
                'reliability': self.f(p['reliability']),
                'co_observed_frames': p['co_observed_frames'],
                'co_observed_start_sec': self.f(p['co_observed_start_sec']), 'co_observed_end_sec': self.f(p['co_observed_end_sec']),
                'minimum_distance_bh': self.f(p['minimum_normalized_distance']), 'mean_distance_bh': self.f(p['mean_normalized_distance']),
                'close_fraction': self.f(p['close_proximity_fraction']), 'close_duration_sec': self.f(p['close_duration_sec']),
                'first_close_sec': self.f(p['first_close_sec']), 'last_close_sec': self.f(p['last_close_sec']),
                'approach_rate_bh_per_sec': self.f(p['approach_rate']), 'approach_events': p['repeated_approach_count'],
                'relative_motion_when_close_bh_per_sec': self.f(p['relative_motion_intensity_when_close']),
                'bbox_overlap_fraction': self.f(p['bbox_overlap_fraction']),
                'contact_proxy': self.proxy(p['contact_proxy']['score'], 'contact_proxy'),
                'arm_extension_score': self.proxy(p['arm_extension_toward_other_score'], 'arm_extension_score'),
                'rapid_limb_motion_score': self.proxy(p['rapid_limb_motion_score'], 'rapid_limb_motion_score'),
            })
        return out

    def scene(self, s, ref):
        links = []
        for l in s['fragment_links']:
            if l['from_track'] not in ref or l['to_track'] not in ref:
                continue
            pc = l['posture_change']
            links.append({
                'from_track': ref[l['from_track']], 'to_track': ref[l['to_track']], 'gap_sec': self.f(l['gap_sec']),
                'distance_bh': self.f(l['distance_body_heights']), 'same_person_confirmed': False,
                'posture_change': None if pc is None else {
                    'from': pc['from_posture'], 'to': pc['to_posture'], 'confidence': self.f(pc['confidence']),
                    'downward_change_bh': self.proxy(pc['downward_change'], 'hip_based_downward_change') if pc['downward_change_basis'] == 'hip'
                    else {'value': self.f(pc['downward_change']), 'reliability': 'normal', 'note': 'bbox-top drop'}},
            })
        return {
            'person_entry_observed': any(e['type'] in ('edge_entry', 'appears_mid_frame') for e in s['track_entries']),
            'person_exit_observed': any(e['type'] in ('edge_exit', 'disappears_mid_frame') for e in s['track_exits']),
            'large_spatial_transition_observed': bool(s['large_spatial_transitions']),
            'occlusion_candidate_count': len(s['occlusion_candidates']),
            'fragment_links': links[:self.cfg['limits']['max_fragment_links_per_camera']],
            'boundary_semantics_available': False,
            'boundary_crossing': None,
            'authorization_known': False,
        }

    # ------------------------------------------------------------------ cross-camera (base observations only)
    def cross(self, x, refs):
        a, b = x['camera_a'], x['camera_b']
        out = {
            'camera_a': a, 'camera_b': b,
            'sync_confirmed': False, 'identity_link_confirmed': False,
            'alignment': 'normalized clip phase 0..1 only',
            'person_count_similarity': self.proxy(x['person_count_similarity'], 'person_count_similarity'),
            'temporal_pattern_similarity': self.proxy(x['temporal_pattern_similarity'], 'temporal_pattern_similarity'),
            'motion_peak_similarity': self.proxy(x['motion_peak_similarity'], 'motion_peak_similarity'),
            'posture_transition_similarity': self.proxy(x['posture_transition_similarity'], 'posture_transition_similarity'),
            'visibility_complementarity': self.f(x['visibility_complementarity_score']),
            'camera_a_visibility_drop_observed': x['camera_a_visibility_drop'],
            'camera_b_visibility_drop_observed': x['camera_b_visibility_drop'],
            'camera_b_has_observations_during_a_low_visibility_phase': x['camera_b_has_observations_during_a_low_visibility_phase'],
            'camera_a_has_observations_during_b_low_visibility_phase': x['camera_a_has_observations_during_b_low_visibility_phase'],
            'camera_a_low_visibility_phases': [[self.f(p), self.f(q)] for p, q in x['camera_a_low_visibility_phases']],
            'camera_b_low_visibility_phases': [[self.f(p), self.f(q)] for p, q in x['camera_b_low_visibility_phases']],
        }
        if self.cfg['cross_camera_count_curve']:
            out['person_count_by_phase'] = {cam: [norm_float(v, 1) for v in x['phase_curves'][cam]['count']] for cam in (a, b)}
        return out
