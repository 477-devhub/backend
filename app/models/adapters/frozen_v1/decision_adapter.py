"""Typed Decisions answers -> deterministic decision values (frozen mapping in configs/decisions_questions_v1.json).

Refusal is not an error: the decision becomes unknown, confidence is lowered and human review is forced.
"""


def index_answers(answers):
    return {a.get('name'): a for a in answers}


def _score01(ans, n_levels):
    return max(0.0, min(1.0, ans['score'] / (n_levels - 1)))


class DecisionAdapter:
    def __init__(self, qcfg):
        self.q = qcfg
        self.a = qcfg['adapter']
        self.levels = {b['key']: len(b['levels']) for b in qcfg['per_assessment_questions'] + qcfg['multi_camera_questions'] if b['type'] == 'score'}

    def assessment(self, answers, prefix=''):
        """Decision values for one assessment (single item, one camera of an attention item, or the multi-camera item)."""
        g = lambda k: answers.get(prefix + k)
        refused = [prefix + k for k in ('incident', 'incident_category', 'severity', 'imminence', 'exposure', 'persistence', 'human_review')
                   if g(k) is None or g(k)['type'] == 'refusal']
        inc, cat, rev = g('incident'), g('incident_category'), g('human_review')
        p_inc = inc['probability'] if inc and inc['type'] == 'predicate' else None
        category = cat['choice'] if cat and cat['type'] == 'choice' else None
        cat_conf = cat['confidence'] if cat and cat['type'] == 'choice' else None
        p_rev = rev['probability'] if rev and rev['type'] == 'predicate' else None
        risk, risk_raw = {}, {}
        for k in ('severity', 'imminence', 'exposure', 'persistence'):
            ans = g(k)
            if ans and ans['type'] == 'score':
                risk[k] = round(_score01(ans, self.levels[k]), 4)
                risk_raw[k] = {'score': ans['score'], 'levels': self.levels[k], 'confidence': ans['confidence']}
            else:
                risk[k] = self.a['refused_score_value']
                risk_raw[k] = {'refused': True}
        comps = []
        if cat_conf is not None:
            comps.append(cat_conf)
        if p_inc is not None:
            comps.append(max(p_inc, 1.0 - p_inc))
        conf = sum(comps) / len(comps) if comps else 0.0
        if len(comps) < 2:
            conf *= 0.5
        conf = round(conf, 4)
        w = self.a['priority_weights']
        priority = round(sum(w[k] * risk[k] for k in w), 4)
        is_incident = p_inc is not None and p_inc >= self.a['is_incident_threshold']
        review = (p_rev is None or p_rev >= self.a['human_review_threshold'] or bool(refused)
                  or conf < self.a['low_confidence_review_threshold'])
        etm = self.a['event_type_map']
        return {
            'p_incident': p_inc, 'is_incident': is_incident,
            'category': category, 'category_confidence': cat_conf,
            'category_probabilities': cat['probabilities'] if category is not None else None,
            'event_type': etm[category] if category is not None else etm['__refusal__'],
            'risk': risk, 'risk_raw': risk_raw, 'priority_score': priority,
            'confidence': conf, 'p_human_review': p_rev, 'human_review_required': review,
            'refused_questions': refused,
        }

    def attention(self, answers, cameras):
        per = {c: self.assessment(answers, c.lower().replace('_', '') + '_') for c in cameras}
        keys = {'priority_score_desc': lambda c, i: -per[c]['priority_score'],
                'severity_desc': lambda c, i: -per[c]['risk']['severity'],
                'confidence_desc': lambda c, i: -per[c]['confidence'],
                'input_camera_order_asc': lambda c, i: i}
        order = sorted(cameras, key=lambda c: tuple(keys[k](c, cameras.index(c)) for k in self.a['attention_tie_break']))
        af = answers.get('attention_first')
        first = None if af is None or af['type'] == 'refusal' else {'choice': af['choice'], 'confidence': af['confidence'], 'probabilities': af['probabilities']}
        return {'per_camera': per, 'order': order, 'attention_first_supplementary': first,
                'attention_first_refused': af is None or af['type'] == 'refusal'}

    def multi(self, answers):
        base = self.assessment(answers)
        si, sv, mv = answers.get('same_incident'), answers.get('second_view_adds'), answers.get('multiview_value')
        p_same = si['probability'] if si and si['type'] == 'predicate' else None
        p_sv = sv['probability'] if sv and sv['type'] == 'predicate' else None
        mvv = _score01(mv, self.levels['multiview_value']) if mv and mv['type'] == 'score' else None
        extra_refused = [k for k, x in (('same_incident', si), ('second_view_adds', sv), ('multiview_value', mv)) if x is None or x['type'] == 'refusal']
        base['refused_questions'] += extra_refused
        if extra_refused:
            base['human_review_required'] = True
        base.update({
            'p_same_incident': p_same,
            'same_incident': p_same is not None and p_same >= self.a['same_incident_threshold'],
            'p_second_view_adds': p_sv,
            'second_view_adds': p_sv is not None and p_sv >= self.a['second_view_threshold'],
            'multiview_value': None if mvv is None else round(mvv, 4),
        })
        return base
