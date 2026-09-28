"""Management metadata must survive edits/backups without changing learning content."""
import copy
import unittest
import test_server as base_tests


class WordDetailsTests(unittest.TestCase):
    setUp = base_tests.Tests.setUp
    tearDown = base_tests.Tests.tearDown
    api = base_tests.Tests.api
    progress = base_tests.Tests.progress

    def add_word(self):
        return self.api('POST', '/api/vocabulary', {
            'english': 'order', 'vietnamese': 'đặt hàng', 'list_id': 1,
            'part_of_speech': '  n/v  ', 'phonetic': ' /ˈɔːdə/ '
        }, 201)['item']

    def test_create_partial_edit_move_clear_and_restart(self):
        word = self.add_word()
        self.assertEqual((word['english'], word['part_of_speech'], word['phonetic']), ('order', 'n/v', '/ˈɔːdə/'))
        other = self.api('POST', '/api/lists', {'name': 'New list'}, 201)['item']['id']
        moved = self.api('PUT', f"/api/vocabulary/{word['id']}", {'list_id': other})['item']
        self.assertEqual((moved['part_of_speech'], moved['phonetic']), ('n/v', '/ˈɔːdə/'))
        self.app.init_db()
        self.assertEqual(self.api('GET', '/api/vocabulary?search=n%2Fv')['total'], 1)
        edited = self.api('PUT', f"/api/vocabulary/{word['id']}", {'phonetic': '/ˈɔːrdər/'})['item']
        self.assertEqual((edited['english'], edited['part_of_speech'], edited['phonetic']), ('order', 'n/v', '/ˈɔːrdər/'))
        cleared = self.api('PUT', f"/api/vocabulary/{word['id']}", {'part_of_speech': '', 'phonetic': '  '})['item']
        self.assertEqual((cleared['part_of_speech'], cleared['phonetic']), ('', ''))

    def test_invalid_details_are_rejected_without_partial_writes(self):
        word = self.add_word()
        for invalid in [{'part_of_speech': ['n']}, {'phonetic': None}, {'part_of_speech': 'x'*65}, {'phonetic': 'x'*257}]:
            self.api('PUT', f"/api/vocabulary/{word['id']}", {'english': 'must not change', **invalid}, 400)
            self.api('POST', '/api/vocabulary', {'english': 'must not be added', 'vietnamese': 'thử', **invalid}, 400)
        self.assertEqual(self.api('GET', '/api/stats')['total_vocabulary'], 17)
        saved = self.api('GET', '/api/vocabulary?search=order')['items'][0]
        self.assertEqual((saved['part_of_speech'], saved['phonetic']), ('n/v', '/ˈɔːdə/'))

    def test_backup_roundtrip_and_legacy_backups(self):
        word = self.add_word()
        backup = self.api('GET', '/api/backup')
        self.assertEqual(backup['version'], 3)
        self.api('PUT', f"/api/vocabulary/{word['id']}", {'phonetic': ''})
        preview = self.api('POST', '/api/restore/preview', {'backup': backup})
        self.api('POST', '/api/restore', {'backup': backup, 'token': preview['token']})
        self.assertEqual(self.api('GET', '/api/vocabulary?search=order')['items'][0]['phonetic'], '/ˈɔːdə/')
        for version in (1, 2):
            old = copy.deepcopy(backup); old['version'] = version
            if version == 1: old.pop('learning')
            for item in old['vocabulary']:
                item.pop('part_of_speech'); item.pop('phonetic')
            preview = self.api('POST', '/api/restore/preview', {'backup': old})
            self.api('POST', '/api/restore', {'backup': old, 'token': preview['token']})
            rows = self.api('GET', '/api/vocabulary')['items']
            self.assertEqual(len(rows), 17)
            self.assertTrue(all(item['part_of_speech'] == item['phonetic'] == '' for item in rows))

    def test_metadata_edits_preserve_round_and_learning_history(self):
        progress = self.progress()
        first_id = progress['words'][0]['id']
        progress['learning'] = {'id': 'metadata-match-001', 'startedAt': 90, 'scopeName': 'All',
                                'events': [{'correct': True, 'wordIds': [first_id], 'at': 95}]}
        dbid = self.api('GET', '/api/progress')['database_id']
        self.api('PUT', '/api/progress', {'database_id': dbid, 'item': progress})
        history = self.api('GET', '/api/learning/history')
        self.api('PUT', f'/api/vocabulary/{first_id}', {'part_of_speech': 'n', 'phonetic': '/nuːn/'})
        self.assertEqual(self.api('GET', '/api/progress')['item'], progress)
        self.assertEqual(self.api('GET', '/api/learning/history'), history)
        self.assertEqual(self.api('GET', '/api/progress')['database_id'], dbid)


if __name__ == '__main__':
    unittest.main()
