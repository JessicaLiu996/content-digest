"""Offline behavior checks; these do not test media acquisition or recognition."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get('CONTENT_DIGEST_SKILL_DIR', ROOT / 'skills/content-digest'))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


importer = load('import_text')
renderer = load('build_reader')


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'result'
        importer.import_text(ROOT / 'examples/source.srt', self.folder, 'Original example')
        self.digest = json.loads((ROOT / 'examples/sample/digest.json').read_text())

    def render(self, data=None, output=None):
        path = self.folder / 'digest.json'
        path.write_text(json.dumps(self.digest if data is None else data))
        return renderer.build(path, output)

    def test_full_example_is_rendered_from_imported_srt(self):
        result = self.render()
        page = Path(result['page']).read_text()
        self.assertEqual(result['insights'], 3)
        self.assertEqual(result['chapters'], 5)
        self.assertIn('Start with one useful result', page)
        self.assertIn('transcript.md', page)
        self.assertIn('"excerpt_end":70.0', page)
        self.assertNotIn('__CD_DATA__', page)
        self.assertEqual(json.loads((self.folder / 'transcript.json').read_text())['segments'][-1]['end'], 175)

    def test_untimed_text_stays_untimed(self):
        source = Path(self.temp.name) / 'plain.txt'
        source.write_text('First paragraph.\n\nSecond paragraph.')
        output = Path(self.temp.name) / 'untimed'
        importer.import_text(source, output, 'Plain text')
        document = json.loads((output / 'transcript.json').read_text())
        self.assertTrue(all(s['start'] is None and s['end'] is None for s in document['segments']))
        data = copy.deepcopy(self.digest)
        data.update(quotes=[], chapters=[])
        for insight in data['insights']:
            insight.update(ref=None, details=[])
        (output / 'digest.json').write_text(json.dumps(data))
        rendered = renderer.build(output / 'digest.json')
        self.assertEqual(rendered['chapters'], 0)

    def test_existing_output_is_preserved(self):
        original = (self.folder / 'transcript.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'empty output'):
            importer.import_text(ROOT / 'examples/source.srt', self.folder, 'Another input')
        self.assertEqual(original, (self.folder / 'transcript.json').read_bytes())

    def test_invented_quote_and_missing_read_part_are_rejected(self):
        data = copy.deepcopy(self.digest)
        data['quotes'][0]['text'] = 'This sentence does not appear in the source.'
        with self.assertRaisesRegex(ValueError, 'Quote does not match'):
            self.render(data)
        data = copy.deepcopy(self.digest)
        data['read_parts'] = []
        with self.assertRaisesRegex(ValueError, 'read_parts'):
            self.render(data)

    def test_partial_and_out_of_range_sources_are_rejected(self):
        state_path = self.folder / 'task-state.json'
        state = json.loads(state_path.read_text())
        state['status'] = 'sample_transcribed'
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'full transcription'):
            self.render()
        state['status'] = 'text_imported'
        state_path.write_text(json.dumps(state))
        data = copy.deepcopy(self.digest)
        data['insights'][0]['ref']['end'] = 9999
        with self.assertRaisesRegex(ValueError, 'outside the source'):
            self.render(data)

    def test_page_content_is_not_executable_markup(self):
        data = copy.deepcopy(self.digest)
        data['title'] = '</script><script>alert("source text")</script>'
        page = Path(self.render(data)['page']).read_text()
        self.assertNotIn(data['title'], page)
        self.assertIn('\\u003c/script\\u003e', page)

    def test_output_cannot_overwrite_source_attachment(self):
        original = (self.folder / 'transcript.md').read_bytes()
        with self.assertRaisesRegex(ValueError, 'overwrite source'):
            self.render(output=self.folder / 'transcript.md')
        self.assertEqual(original, (self.folder / 'transcript.md').read_bytes())

    @unittest.skipIf(os.name == 'nt', 'Transcription helper uses Unix locking')
    def test_transcription_export_uses_portable_english_artifact_names(self):
        transcriber = load('transcribe')
        folder = Path(self.temp.name) / 'export'
        folder.mkdir()
        parts = transcriber.export_text(folder,
            {'title': 'Fixture', 'source_url': '', 'language_requested': 'en'},
            [{'start': 0, 'end': 3, 'text': 'An original example.'}], 3, True)
        self.assertTrue((folder / 'transcript.md').is_file())
        self.assertTrue((folder / 'transcript.srt').is_file())
        self.assertEqual(parts[0]['file'], 'transcript.txt')
        self.assertEqual(transcriber.MODEL, None if not os.environ.get('CONTENT_DIGEST_MODEL')
                         else Path(os.environ['CONTENT_DIGEST_MODEL']).expanduser())


if __name__ == '__main__':
    unittest.main()
