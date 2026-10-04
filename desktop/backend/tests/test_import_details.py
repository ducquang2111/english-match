"""Exercise both import formats through the same preview/apply/backup API as the UI."""
import csv
import io
import unicodedata
import unittest
import test_server as base_tests


class ImportDetailsTests(unittest.TestCase):
    setUp = base_tests.Tests.setUp
    tearDown = base_tests.Tests.tearDown
    api = base_tests.Tests.api

    def test_mixed_widths_preview_apply_restart_and_backup_restore(self):
        data = {'list_id': 1, 'text': 'provide | v | /prəˈvaɪd/ | cung cấp\nsimple | đơn giản\nempty | | | để trống'}
        report = self.api('POST', '/api/import/preview', data)
        self.assertEqual((report['new'], report['errors']), (3, 0))
        self.assertEqual(report['formats'], {'two_columns': 1, 'four_columns': 2})
        self.assertEqual(report['delimiter'], '|')
        self.assertEqual(self.api('GET', '/api/stats')['total_vocabulary'], 16)
        self.api('POST', '/api/import', data)
        self.app.init_db()
        word = self.api('GET', '/api/vocabulary?search=provide')['items'][0]
        self.assertEqual((word['english'], word['part_of_speech'], word['phonetic'], word['vietnamese']),
                         ('provide', 'v', '/prəˈvaɪd/', 'cung cấp'))
        self.assertEqual(self.api('GET', '/api/vocabulary?search=simple')['items'][0]['phonetic'], '')
        backup = self.api('GET', '/api/backup')
        self.assertEqual(backup['version'], 4)
        self.api('DELETE', f"/api/vocabulary/{word['id']}")
        preview = self.api('POST', '/api/restore/preview', {'backup': backup})
        self.api('POST', '/api/restore', {'backup': backup, 'token': preview['token']})
        restored = self.api('GET', '/api/vocabulary?search=provide')['items'][0]
        self.assertEqual((restored['part_of_speech'], restored['phonetic']), ('v', '/prəˈvaɪd/'))

    def test_auto_delimiters_with_mixed_rows_and_quoted_cells(self):
        for delimiter in ('\t', '|', ',', ';'):
            with self.subTest(delimiter=delimiter):
                buffer = io.StringIO()
                writer = csv.writer(buffer, delimiter=delimiter)
                writer.writerows([['two words', 'nghĩa, có | và ; ký tự'],
                                  ['offer', 'n/v', '/ˈɒfə/', 'đề nghị, "mời"']])
                r = self.api('POST', '/api/import/preview', {'list_id': 1, 'text': buffer.getvalue()})
                self.assertEqual((r['delimiter'], r['new'], r['errors']), (delimiter, 2, 0))
                self.assertEqual(r['rows'][1]['vietnamese'], 'đề nghị, "mời"')
                self.assertEqual(r['rows'][1]['part_of_speech'], 'n/v')

    def test_headers_english_vietnamese_and_reordered_columns(self):
        samples = [
            ('english,part_of_speech,phonetic,vietnamese\nprovide,v,/prəˈvaɪd/,cung cấp', 'v', '/prəˈvaɪd/'),
            ('Từ tiếng Anh\tLoại từ\tPhiên âm\tNghĩa tiếng Việt\nprovide\tv\t/prəˈvaɪd/\tcung cấp', 'v', '/prəˈvaɪd/'),
            ('nghĩa;phiên âm;từ;loại từ\ncung cấp;/prəˈvaɪd/;provide;v', 'v', '/prəˈvaɪd/'),
            ('vietnamese,english\ncung cấp,provide', '', ''),
        ]
        for text, pos, ipa in samples:
            with self.subTest(text=text):
                r = self.api('POST', '/api/import/preview', {'list_id': 1, 'text': '\ufeff' + unicodedata.normalize('NFD', text.split('\n')[0]) + '\n' + text.split('\n')[1]})
                self.assertTrue(r['header_skipped'])
                self.assertEqual((r['new'], r['errors']), (1, 0))
                row = r['rows'][0]
                self.assertEqual((row['english'], row['vietnamese'], row['part_of_speech'], row['phonetic']), ('provide', 'cung cấp', pos, ipa))

    def test_duplicates_never_overwrite_existing_metadata(self):
        original = {'list_id': 1, 'text': 'provide|v|/prəˈvaɪd/|cung cấp'}
        self.api('POST', '/api/import', original)
        r = self.api('POST', '/api/import', {'list_id': 1, 'text': 'provide|cung cấp\nPROVIDE|n|/wrong/|cung cấp\nother|n|/x/|khác\nother|khác'})
        self.assertEqual((r['new'], r['duplicates'], r['errors']), (1, 3, 0))
        saved = self.api('GET', '/api/vocabulary?search=provide')['items'][0]
        self.assertEqual((saved['part_of_speech'], saved['phonetic']), ('v', '/prəˈvaɪd/'))

    def test_invalid_widths_lengths_and_empty_required_fields_are_atomic(self):
        invalid = ['three|n|nghĩa', 'five|n|/x/|nghĩa|extra',
                   'missing|n|/x/|', '|n|/x/|nghĩa',
                   'long|' + 'n'*65 + '|/x/|nghĩa', 'long|n|' + 'x'*257 + '|nghĩa']
        for text in invalid:
            data = {'list_id': 1, 'text': 'valid|v|/x/|hợp lệ\n' + text, 'delimiter': '|'}
            preview = self.api('POST', '/api/import/preview', data)
            self.assertEqual(preview['errors'], 1)
            self.api('POST', '/api/import', data, 400)
        self.assertEqual(self.api('GET', '/api/stats')['total_vocabulary'], 16)

    def test_quoted_multiline_and_malformed_quote(self):
        data = {'list_id': 1, 'text': 'english,part_of_speech,phonetic,vietnamese\nquote,n,/kwəʊt/,"trích dẫn,\nhai dòng"'}
        r = self.api('POST', '/api/import', data)
        self.assertEqual(r['rows'][0]['vietnamese'], 'trích dẫn, hai dòng')
        self.assertEqual(r['rows'][0]['line'], 3)
        self.api('POST', '/api/import', {'list_id': 1, 'text': 'valid|nghĩa\nbroken|"chưa đóng', 'delimiter': '|'}, 400)
        self.assertEqual(self.api('GET', '/api/vocabulary?search=valid')['total'], 0)


if __name__ == '__main__':
    unittest.main()
