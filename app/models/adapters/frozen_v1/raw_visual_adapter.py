"""P4 structured visual output -> canonical raw decision + P1 typed-answer records + resolved evidence.

Decision fields are converted exactly as in P3 (predicate probability; choice value/confidence; score*(n_levels-1) so the
frozen P1 DecisionAdapter returns the same 0-1 value). Evidence frame_refs are resolved deterministically to
(camera, exact relative timestamp) from the request's own frame table; a ref that is unknown or belongs to another
camera raises (schema/frame-ref failure policy). Model text is copied verbatim, never rewritten.
"""
PROBABILITY_SOURCE = 'model_generated_estimate'
RISK = ('severity', 'imminence', 'exposure', 'persistence')


class FrameRefError(ValueError):
    pass


def canonical(a):
    return {'incident_probability': a['incident']['probability'], 'raw_category': a['incident_category']['value'],
            'raw_category_confidence': a['incident_category']['confidence'], **{k: a[k]['score'] for k in RISK},
            'human_review_probability': a['human_review']['probability'], 'probability_source': PROBABILITY_SOURCE}


class RawVisualAdapter:
    def __init__(self, p1_qcfg):
        self.levels = {b['key']: len(b['levels']) for b in p1_qcfg['per_assessment_questions'] + p1_qcfg['multi_camera_questions']
                       if b['type'] == 'score'}

    def _answers(self, a, prefix=''):
        c = canonical(a)
        return [{'type': 'predicate', 'name': prefix + 'incident', 'probability': c['incident_probability']},
                {'type': 'choice', 'name': prefix + 'incident_category', 'choice': c['raw_category'], 'confidence': c['raw_category_confidence'], 'probabilities': None},
                *[{'type': 'score', 'name': prefix + k, 'score': c[k] * (self.levels[k] - 1), 'confidence': None, 'probabilities': None} for k in RISK],
                {'type': 'predicate', 'name': prefix + 'human_review', 'probability': c['human_review_probability']}]

    @staticmethod
    def resolve(evidence, table, camera=None):
        out = []
        for e in evidence:
            f = table.get(e['frame_ref'])
            if f is None:
                raise FrameRefError(f"unknown frame_ref {e['frame_ref']}")
            if camera is not None and f['camera'] != camera:
                raise FrameRefError(f"frame_ref {e['frame_ref']} belongs to {f['camera']}, cited for {camera}")
            if not e['description'].strip():
                raise FrameRefError(f"empty evidence description at {e['frame_ref']}")
            out.append({'frame_ref': e['frame_ref'], 'camera': f['camera'], 'timestamp_sec': f['timestamp_sec'], 'description': e['description']})
        return out

    @staticmethod
    def texts(a):
        for k in ('temporal_summary', 'reason'):
            if not a[k].strip():
                raise FrameRefError(f'empty {k}')
        return {'temporal_summary': a['temporal_summary'], 'uncertainties': [u for u in a['uncertainties'] if u.strip()], 'reason': a['reason']}

    def convert(self, task, parsed, cameras, table):
        """Returns (p1_style_answers, canonical_raw, visual) where visual holds resolved evidence + model texts per assessment."""
        if task == 'single':
            vis = {'single': {'evidence': self.resolve(parsed['evidence'], table, cameras[0]), **self.texts(parsed)}}
            return self._answers(parsed), {'assessment': canonical(parsed)}, vis
        if task == 'attention':
            ans, raw, vis = [], {'per_camera': {}}, {}
            for cam in cameras:
                a = parsed['camera_assessments'][cam]
                ans += self._answers(a, cam.lower().replace('_', '') + '_')
                raw['per_camera'][cam] = canonical(a)
                vis[cam] = {'evidence': self.resolve(a['evidence'], table, cam), **self.texts(a)}
            af = parsed['attention_first']
            ans.append({'type': 'choice', 'name': 'attention_first', 'choice': af['camera'], 'confidence': af['confidence'], 'probabilities': None})
            raw['attention_first'] = {'camera': af['camera'], 'confidence': af['confidence'], 'probability_source': PROBABILITY_SOURCE}
            return ans, raw, vis
        ans = self._answers(parsed) + [
            {'type': 'predicate', 'name': 'same_incident', 'probability': parsed['same_incident']['probability']},
            {'type': 'predicate', 'name': 'second_view_adds', 'probability': parsed['second_view_adds']['probability']},
            {'type': 'score', 'name': 'multiview_value', 'score': parsed['multiview_value']['score'] * (self.levels['multiview_value'] - 1),
             'confidence': None, 'probabilities': None}]
        raw = {'assessment': canonical(parsed), 'same_incident_probability': parsed['same_incident']['probability'],
               'second_view_adds_probability': parsed['second_view_adds']['probability'], 'multiview_value': parsed['multiview_value']['score'],
               'probability_source': PROBABILITY_SOURCE}
        vis = {'multi': {'evidence_by_camera': {c: self.resolve(parsed['evidence_by_camera'][c], table, c) for c in cameras}, **self.texts(parsed)}}
        return ans, raw, vis
