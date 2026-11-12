import unittest

from mosaic_gui.skill_editor import render_editor, update_editor


ALPHA = {
    'skill_id': 'alpha',
    'display_name': 'Alpha',
    'description': '',
    'groups': ['example/planning'],
}
BETA = {
    'skill_id': 'beta-skill',
    'display_name': 'Beta',
    'description': '',
    'groups': ['example/planning'],
}
GAMMA = {
    'skill_id': 'gamma',
    'display_name': 'Gamma',
    'description': '',
    'groups': ['example/delivery'],
}


class SkillEditorTests(unittest.TestCase):
    def setUp(self):
        self.state = None
        self.sequence = 0
        self.event('open')
        self.result(
            {'version': 1, 'skills': [ALPHA], 'withdrawn_skill_ids': ['retired']}
        )
        self.result({'items': ['example'], 'next_offset': 1})
        self.event('skill-more-domains')
        self.assertEqual(self.state['request']['params'], {'offset': 1})
        self.result({'items': ['second-domain'], 'next_offset': None})
        self.event('skill-path-domains-example')
        self.result({'items': ['planning', 'delivery'], 'next_offset': None})

    def event(self, action, value=None):
        self.sequence += 1
        self.state = update_editor(
            {
                'sequence': self.sequence,
                'action': action,
                'value': value,
            },
            self.state,
        )

    def result(self, data=None, **error):
        self.event('result', {'id': self.state['request']['id'], 'data': data, **error})

    def test_bulk_keeps_closed_function_closed_and_saves_atomic_ids(self):
        self.assertEqual(self.state['request']['kind'], 'check')
        self.result([ALPHA, BETA])
        self.event('skill-function-toggle-delivery')
        self.assertEqual(
            self.state['request']['params'],
            {'domain': 'example', 'function': 'delivery'},
        )
        self.result([GAMMA])
        self.assertIsNone(self.state['function'])
        self.assertEqual(render_editor(self.state, False)[4], '2 selected')
        self.event('skill-path-functions-planning')
        self.result({'items': [ALPHA], 'next_offset': 1})
        self.event('skill-function-toggle-planning')
        self.assertEqual(
            list(self.state['selected']), ['alpha', 'retired', 'gamma', 'beta-skill']
        )
        self.assertIsNone(self.state['pages']['skills']['next_offset'])
        self.event('skill-option-beta-skill')
        self.event('skill-function-toggle-planning')
        self.event('skill-function-toggle-planning')
        self.event('save-skills')
        self.assertEqual(
            self.state['request']['body'],
            {'expected_version': 1, 'skill_ids': ['retired', 'gamma']},
        )

    def test_failed_bulk_and_stale_results_preserve_selection(self):
        self.result(error='Unable to reach the backend.')
        self.event('skill-path-functions-planning')
        self.result({'items': [ALPHA], 'next_offset': 1})
        self.event('skill-function-toggle-planning')
        self.assertEqual(self.state['request']['page']['next_offset'], 1)
        self.result(error='Unable to reach the backend.')
        self.assertEqual(list(self.state['selected']), ['alpha', 'retired'])
        self.event('skill-function-toggle-planning')
        bulk_id = self.state['request']['id']
        self.event('skill-search', 'beta')
        self.event('result', {'id': bulk_id, 'data': [ALPHA, BETA]})
        self.assertEqual(list(self.state['selected']), ['alpha', 'retired'])
        self.result({'items': [BETA], 'next_offset': None})
        self.event('skill-option-beta-skill')
        self.event('skill-remove-retired')
        self.assertEqual(list(self.state['selected']), ['alpha', 'beta-skill'])
        self.event('cancel-skills')
        self.assertEqual(list(self.state['selected']), ['alpha', 'retired'])

    def test_conflict_keeps_draft_and_retries_only_on_explicit_save(self):
        self.result([ALPHA, BETA])
        self.event('skill-function-toggle-planning')
        self.event('save-skills')
        self.result(status=409, error='Conflict')
        self.result({'version': 2, 'skills': [GAMMA], 'withdrawn_skill_ids': []})
        self.assertEqual(list(self.state['selected']), ['alpha', 'beta-skill'])
        self.assertIn('Currently saved: Gamma', self.state['error'])
        self.assertIsNone(self.state['request'])
        self.event('save-skills')
        self.assertEqual(self.state['request']['body']['expected_version'], 2)
        self.result({'version': 3, 'skills': [ALPHA, BETA]})
        self.assertEqual(render_editor(self.state, False)[5], 'Skills saved')
        self.event('skill-remove-alpha')
        self.event('skill-remove-beta-skill')
        self.event('save-skills')
        self.assertEqual(self.state['request']['body']['skill_ids'], [])
        self.event('reset')
        self.assertEqual(render_editor(self.state, False)[3], [])
