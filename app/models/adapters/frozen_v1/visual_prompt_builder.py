"""Builds the single P4 user message and the strict output schema from frozen artifacts only.

message content = [input_text: visual_prompt_v1 + decision definitions + output guidance]
                  + for each canonical frame: [input_text 'F### | CAM_## | t=s.sssS', input_image(data URL, detail=high)]
Decision definitions = frozen P1 decisions_questions_v1.json (same keys, categories, level labels/descriptions, P3 0-1 anchors)
with CV-state wording replaced by visual wording via the fixed MODALITY_SUBSTITUTIONS below (no item-specific text).
"""
import copy

from .utils import P1_QUESTIONS_CONFIG, P4_PROMPT, SCHEMA_DIR, read_allowed_json, read_allowed_text

MODALITY_SUBSTITUTIONS = [
    ('Use only the supplied computer-vision observations.', 'Use only the supplied frames.'),
    ('Do not infer weapons unless supported by supplied evidence.', 'Do not infer weapons unless supported by the visual evidence.'),
    ('Treat null/unavailable fields as unknown, not false.', 'Treat anything not visible as unknown, not false.'),
    ('Treat low-reliability CV proxies (reliability "limited") as uncertain evidence.', 'Treat unclear, small, dark or partly occluded content as uncertain evidence.'),
    ('Does the provided CV evidence indicate', 'Does the provided visual evidence indicate'),
    ('pattern in the CV observations?', 'pattern in the frames?'),
    ('rapid relative movement or limb-motion proxies.', 'rapid relative movement or limb motion.'),
    ('in a way an operator may want to check; boundary semantics are not known.',
     'in a way an operator may want to check, including crossing a visible wall, gate, doorway or other boundary; authorization is not known.'),
    ('Do the supplied camera-level CV observation patterns support', 'Do the supplied camera views support'),
]
OUTPUT_GUIDANCE = [
    'Output guidance:',
    '- evidence: 1 to 6 items. Each item names one supplied frame_ref and states only an observable visual fact seen in that frame '
    '(no diagnosis, intent, authorization or identity). If evidence is weak, still cite what is visible and state the limitation in uncertainties.',
    '- temporal_summary: 1-3 sentences describing how the scene develops over the ordered frames.',
    '- uncertainties: short statements of what cannot be determined from the frames.',
    '- reason: one brief operator-facing rationale (no step-by-step reasoning).',
]
MULTI_NOTE = ['Two camera views may or may not show the same underlying incident.', 'Do not assume exact synchronization.',
              'Do not assert cross-camera identity.',
              'Use visual scene/action consistency and complementary evidence, while preserving uncertainty.',
              'In uncertainties, consider whether precise synchronization and cross-camera identity are unknown from the supplied frames.']


def _sub(text):
    for old, new in MODALITY_SUBSTITUTIONS:
        text = text.replace(old, new)
    return text


def _fmt_question(q):
    name = q['key']
    if q['type'] == 'predicate':
        return [f"- {name}.probability: probability in [0,1] that the answer is yes. Question: {_sub(q['instructions'])}"]
    if q['type'] == 'choice':
        return ([f"- {name}: choose exactly one value and give your confidence in [0,1]. Question: {_sub(q['instructions'])}"]
                + [f"    * {c['value']}: {_sub(c['description'])}" for c in q['choices']])
    n = len(q['levels'])
    return ([f"- {name}.score: a value in [0,1]; anchors below, intermediate values allowed. Question: {_sub(q['instructions'])}"]
            + [f"    * {k / (n - 1):.2f} = {l['label']}: {l['description']}" for k, l in enumerate(q['levels'])])


class VisualPromptBuilder:
    def __init__(self):
        self.base = read_allowed_text(P4_PROMPT).strip()
        self.q = read_allowed_json(P1_QUESTIONS_CONFIG)
        missing = [o for o, _ in MODALITY_SUBSTITUTIONS if o not in __import__('json').dumps(self.q, ensure_ascii=False).replace('\\"', '"')]
        if missing:
            raise RuntimeError(f'modality substitution source text not found in frozen P1 questions: {missing}')
        self.single_t = read_allowed_json(SCHEMA_DIR / 'visual_single.schema.json')
        self.multi_t = read_allowed_json(SCHEMA_DIR / 'visual_multi.schema.json')
        read_allowed_json(SCHEMA_DIR / 'visual_attention.schema.json')

    def task_prompt(self, task, cameras):
        q = self.q
        L = [self.base, '', 'Decision policy (applies to every decision): ' + _sub(q['policy']), '']
        per = [x for b in q['per_assessment_questions'] for x in _fmt_question(b)]
        if task == 'single':
            L += ['Task: one camera. ' + q['scope']['single'], 'Decisions (top-level fields):'] + per
        elif task == 'attention':
            L += ['Task: concurrent alerts from several cameras. Produce one assessment per camera under camera_assessments.<camera>; '
                  "each camera's evidence may cite only that camera's frames."]
            L += ['For camera_assessments.' + c + ': ' + q['scope']['camera'].format(camera=c) for c in cameras]
            L += ['Decisions for each camera assessment:'] + per + ['', 'Additional decision (top-level field):']
            for b in q['attention_questions']:
                b = dict(b, choices=[c for c in b['choices'] if c['value'] in set(cameras) | {'no_clear_priority'}])
                L += [x.replace(f"- {b['key']}: choose", f"- {b['key']}.camera: choose") for x in _fmt_question(b)]
        elif task == 'multi_camera':
            L += ['Task: several camera views. ' + q['scope']['multi_camera']] + MULTI_NOTE + ['Decisions (top-level fields):'] + per
            L += [x for b in q['multi_camera_questions'] for x in _fmt_question(b)]
            L += ["- evidence_by_camera.<camera>: 1 to 6 evidence items per camera, citing only that camera's frames."]
        else:
            raise ValueError(task)
        L += [''] + OUTPUT_GUIDANCE + ['', 'Frames follow in order. Each frame is preceded by a label: frame_ref | camera | relative time within that camera clip.']
        return '\n'.join(L).strip()

    @staticmethod
    def frame_label(f):
        return f"{f['ref']} | {f['camera']} | t={f['timestamp_sec']:.3f}s"

    def content(self, task, cameras, frames, data_urls, detail):
        parts = [{'type': 'input_text', 'text': self.task_prompt(task, cameras)}]
        for f, u in zip(frames, data_urls):
            parts.append({'type': 'input_text', 'text': self.frame_label(f)})
            parts.append({'type': 'input_image', 'image_url': u, 'detail': detail})
        return parts

    @staticmethod
    def request_text(parts):
        return '\n'.join(p['text'] for p in parts if p['type'] == 'input_text')

    def _single(self, refs):
        s = copy.deepcopy(self.single_t)
        s.pop('$comment', None)
        s['properties']['evidence']['items']['properties']['frame_ref']['enum'] = list(refs)
        return s

    def output_schema(self, task, cameras, frames):
        refs = {c: [f['ref'] for f in frames if f['camera'] == c] for c in cameras}
        if task == 'single':
            return self._single(refs[cameras[0]])
        if task == 'attention':
            return {'type': 'object', 'additionalProperties': False, 'required': ['camera_assessments', 'attention_first'],
                    'properties': {'camera_assessments': {'type': 'object', 'additionalProperties': False, 'required': list(cameras),
                                                          'properties': {c: self._single(refs[c]) for c in cameras}},
                                   'attention_first': {'type': 'object', 'additionalProperties': False, 'required': ['camera', 'confidence'],
                                                       'properties': {'camera': {'type': 'string', 'enum': list(cameras) + ['no_clear_priority']},
                                                                      'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}}}}}
        if task == 'multi_camera':
            s = self._single([f['ref'] for f in frames])
            ev = s['properties'].pop('evidence')
            s['required'].remove('evidence')
            byc = {}
            for c in cameras:
                e = copy.deepcopy(ev)
                e['items']['properties']['frame_ref']['enum'] = refs[c]
                byc[c] = e
            s['properties']['evidence_by_camera'] = {'type': 'object', 'additionalProperties': False, 'required': list(cameras), 'properties': byc}
            s['properties'].update(copy.deepcopy(self.multi_t['multi_camera_extra']))
            s['required'] += ['evidence_by_camera'] + list(self.multi_t['multi_camera_extra'])
            return s
        raise ValueError(task)

    def text_format(self, task, cameras, frames):
        return {'type': 'json_schema', 'name': f'p4_visual_{task}', 'strict': True, 'schema': self.output_schema(task, cameras, frames)}
