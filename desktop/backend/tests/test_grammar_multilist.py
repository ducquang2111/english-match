import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_server as base


class GrammarMultiListTests(unittest.TestCase):
    setUp = base.Tests.setUp
    tearDown = base.Tests.tearDown
    api = base.Tests.api
    progress = base.Tests.progress

    def test_complete_catalog_and_progress_backup_restore(self):
        catalog = self.api('GET', '/api/grammar/catalog')
        sections = [s for c in catalog['chapters'] for s in c['sections']]
        self.assertEqual(len(catalog['chapters']), 26)
        self.assertEqual(len(sections), 295)
        self.assertEqual(len({s['id'] for s in sections}), 295)
        self.assertEqual(sum(b['type'] == 'table' for b in [b for s in sections for b in s['blocks']] + catalog['sources']), 22)
        progress = {'version': 1, 'completed': ['1.1', '8.2'], 'bookmarks': ['20.3'], 'last_section': '20.3', 'updatedAt': 10}
        db = self.api('GET', '/api/grammar/progress')['database_id']
        self.api('PUT', '/api/grammar/progress', {'database_id': db, 'item': progress})
        self.app.init_db()
        self.assertEqual(self.api('GET', '/api/grammar/progress')['item'], progress)
        backup = self.api('GET', '/api/backup')
        self.assertEqual(backup['version'], 4)
        self.assertEqual(backup['grammar'], progress)
        self.api('PUT', '/api/grammar/progress', {'database_id': db, 'item': None})
        token = self.api('POST', '/api/restore/preview', {'backup': backup})['token']
        self.api('POST', '/api/restore', {'backup': backup, 'token': token})
        self.assertEqual(self.api('GET', '/api/grammar/progress')['item'], progress)
        self.api('PUT', '/api/grammar/progress', {'database_id': db, 'item': progress}, 409)

    def test_invalid_grammar_cannot_replace_existing_data(self):
        original = self.api('GET', '/api/backup')
        for bad in ({'completed': ['1.1', '1.1']}, {'bookmarks': ['<script>']}, {'last_section': 1}, {'updatedAt': True}):
            value = {**original['grammar'], **bad}
            db = self.api('GET', '/api/grammar/progress')['database_id']
            self.api('PUT', '/api/grammar/progress', {'database_id': db, 'item': value}, 400)
            backup = {**original, 'grammar': value}
            self.api('POST', '/api/restore/preview', {'backup': backup}, 400)
        self.assertEqual(self.api('GET', '/api/grammar/progress')['item'], original['grammar'])
        self.assertEqual(self.api('GET', '/api/stats')['total_vocabulary'], 16)

    def test_version_three_backup_is_still_readable(self):
        backup = self.api('GET', '/api/backup'); backup['version'] = 3; backup.pop('grammar')
        token = self.api('POST', '/api/restore/preview', {'backup': backup})['token']
        self.api('POST', '/api/restore', {'backup': backup, 'token': token})
        self.assertEqual(self.api('GET', '/api/grammar/progress')['item']['completed'], [])
        self.assertEqual(self.api('GET', '/api/stats')['total_vocabulary'], 16)

    def test_multiple_list_scope_survives_round_review_and_backup(self):
        other = self.api('POST', '/api/lists', {'name': 'Other'}, 201)['item']['id']
        self.api('PUT', '/api/vocabulary/1', {'list_id': other})
        scope = f'1,{other}'
        p = self.progress(); p['scope'] = scope
        db = self.api('GET', '/api/progress')['database_id']
        self.api('PUT', '/api/progress', {'database_id': db, 'item': p})
        review = dict(version=1, id='multiple-list-review', mode='typing', scope=scope, scopeName='Two lists', wrongOnly=False, startedAt=100, updatedAt=100, words=p['words'], index=0, results=[], flipped=False)
        self.api('PUT', '/api/review/progress', {'database_id': db, 'item': review})
        backup = self.api('GET', '/api/backup')
        token = self.api('POST', '/api/restore/preview', {'backup': backup})['token']
        self.api('POST', '/api/restore', {'backup': backup, 'token': token})
        self.assertEqual(self.api('GET', '/api/progress')['item']['scope'], scope)
        self.assertEqual(self.api('GET', '/api/review/progress')['item']['scope'], scope)

    def test_invalid_scopes_do_not_overwrite_saved_round(self):
        p = self.progress(); db = self.api('GET', '/api/progress')['database_id']
        self.api('PUT', '/api/progress', {'database_id': db, 'item': p})
        for bad in ('', '1,1', '1,', '0,1', '1,-2', '1,all', '1,2.5', ['1', '2']):
            changed = copy.deepcopy(p); changed['scope'] = bad
            self.api('PUT', '/api/progress', {'database_id': db, 'item': changed}, 400)
        self.assertEqual(self.api('GET', '/api/progress')['item'], p)
