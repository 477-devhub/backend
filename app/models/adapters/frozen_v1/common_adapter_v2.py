"""common-adapter-v2: deterministic is_incident / event_type consistency for any decision model (P1, P2, P3, P4).

Input: a frozen-v1-style decision dict per assessment (p_incident, category, category_confidence, ...) plus the prediction
built from it. Output: a copy of the prediction in which only `event_type` may change, plus metadata that keeps the raw
category answer separate from the final presentation. Nothing else is recomputed or modified.
"""
import copy
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / 'adapter_v2.json'


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class CommonAdapterV2:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self.t = self.cfg['incident_threshold']
        self.etm = self.cfg['event_type_map']

    def reconcile(self, d):
        """d: decision dict with p_incident, category (None if refused/invalid), category_confidence."""
        p, cat = d.get('p_incident'), d.get('category')
        if p is None:
            rule, inc, et = 'R4', False, 'uncertain (incident decision unavailable)'
        elif p < self.t:
            rule, inc, et = 'R1', False, self.etm['no_clear_incident']
        elif cat is None:
            rule, inc, et = 'R3', True, self.etm['__refusal__']
        elif cat == 'no_clear_incident':
            rule, inc, et = 'R2b', True, self.etm['uncertain']
        else:
            rule, inc, et = 'R2', True, self.etm[cat]
        return {
            'raw_decision': {'incident_probability': p, 'incident_category': cat,
                             'incident_category_confidence': d.get('category_confidence')},
            'normalized_decision': {'is_incident': inc, 'event_type': et},
            'rule': rule,
        }

    def _apply_one(self, assessment_pred, d, label):
        r = self.reconcile(d)
        if bool(assessment_pred['is_incident']) != r['normalized_decision']['is_incident']:
            raise ValueError(f'{label}: is_incident from the v1 adapter differs from threshold rule; refusing to change it')
        r.update({'assessment': label, 'v1_event_type': assessment_pred['event_type'],
                  'event_type_changed': assessment_pred['event_type'] != r['normalized_decision']['event_type']})
        assessment_pred['event_type'] = r['normalized_decision']['event_type']
        return r

    def apply(self, prediction, decision, task):
        """Returns (v2_prediction, metadata). `decision` is the frozen adapter output (per_camera for attention)."""
        pred = copy.deepcopy(prediction)
        recs = []
        if task == 'attention':
            for a in pred['assessments']:
                recs.append(self._apply_one(a['assessment'], decision['per_camera'][a['camera']], a['camera']))
        else:
            recs.append(self._apply_one(pred, decision, 'single' if task == 'single' else 'multi_camera'))
        meta = {'adapter_version': self.cfg['adapter_version'], 'incident_threshold': self.t,
                'event_type_changes': sum(r['event_type_changed'] for r in recs), 'assessments': recs}
        return pred, meta


def diff_paths(a, b, path=''):
    """All leaf paths whose values differ between two JSON-like objects."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += diff_paths(a.get(k, '<missing>'), b.get(k, '<missing>'), f'{path}.{k}' if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, f'{path}[{i}]')
        return out
    return [] if a == b else [path]
