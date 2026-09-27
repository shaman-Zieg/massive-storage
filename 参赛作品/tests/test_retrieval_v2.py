"""Synthetic evidence tests; no competition questions or reference answers."""
import json
import tempfile
import unittest
from pathlib import Path

from evidence_rag.index import Corpus, build
from evidence_rag.models import Config
from evidence_rag.retrieval import Retriever
from evidence_rag.tables import TableView, table_rows


class TableEvidenceTests(unittest.TestCase):
    def test_rowspan_and_colspan_keep_cell_coordinates(self):
        source = (
            '<table><tr><th rowspan="2">Metric</th><th colspan="2">2025</th></tr>'
            '<tr><th>North</th><th>South</th></tr>'
            '<tr><td>Change</td><td>-12.50 %</td><td>(1,234.00) kg</td></tr></table>'
        )
        self.assertEqual(table_rows(source), [
            ['Metric', '2025', '2025'],
            ['Metric', 'North', 'South'],
            ['Change', '-12.50 %', '(1,234.00) kg'],
        ])

    def test_empty_source_row_occupied_by_rowspan_is_retained(self):
        source = (
            '<table><tr><td rowspan="2" colspan="2">Merged label</td></tr>'
            '<tr></tr></table>'
        )
        self.assertEqual(table_rows(source), [
            ['Merged label', 'Merged label'],
            ['Merged label', 'Merged label'],
        ])

    def test_rowspan_cannot_extend_into_a_separate_table(self):
        source = (
            '<table><tr><td rowspan="5">First table</td></tr></table>'
            '<table><tr><td>Second table</td></tr></table>'
        )
        self.assertEqual(table_rows(source), [['First table'], ['Second table']])

    def test_numeric_sign_percentage_units_and_entities_remain_verbatim(self):
        values = ['-12.50%', '−0.25 µg/mL', '(1,234.00) EUR', '€ 18.00', 'R&D']
        source = (
            '<table><tr><td>-12.50%</td><td>−0.25 µg/mL</td>'
            '<td>(1,234.00) EUR</td><td>&euro; 18.00</td><td>R&amp;D</td></tr></table>'
        )
        self.assertEqual(table_rows(source), [values])
        selected = TableView(source).select('numeric change concentration cost')
        for value in values:
            with self.subTest(value=value):
                self.assertIn(value, selected)

    def test_long_table_selects_late_matching_rows_with_column_context(self):
        rows = ['<tr><th>Asset</th><th>Pressure change</th></tr>']
        rows += [
            f'<tr><td>Routine pump {i}</td><td>Stable baseline measurement {i}.00 kPa</td></tr>'
            for i in range(80)
        ]
        rows.append('<tr><td>Aster turbine</td><td>−18.25 % at 3.4 MPa</td></tr>')
        source = 'Monthly pressure observations\n<table>' + ''.join(rows) + '</table>'
        self.assertGreater(source.index('Aster turbine'), 4500)
        selected = TableView(source).select('Aster turbine pressure change', budget=1200)
        self.assertIn('Aster turbine', selected)
        self.assertIn('−18.25 % at 3.4 MPa', selected)
        self.assertIn('Asset', selected)
        self.assertIn('Pressure change', selected)
        self.assertLessEqual(len(selected), 1200)

    def test_tight_budget_still_retains_unique_matching_late_row(self):
        source = '<table><tr><td>' + 'Verbose heading ' * 35 + '</td></tr>'
        source += '<tr><td>Ordinary observation</td></tr>' * 12
        source += '<tr><td>Unique nebula sensor: 82.7%</td></tr></table>'
        selected = TableView(source).select('Unique nebula sensor', budget=500)
        self.assertIn('Unique nebula sensor: 82.7%', selected)
        self.assertLessEqual(len(selected), 500)

    def test_empty_or_image_only_table_has_no_invented_cells(self):
        for source in ('', 'Caption for an image-only table', '<table></table>'):
            with self.subTest(source=source):
                view = TableView(source)
                self.assertEqual(view.rows, [])
                self.assertEqual(view.fragments(), [])
                self.assertEqual(view.select('requested value'), '')


class FocusedSourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        source = self.root / 'parsed' / 'synthetic_manual' / 'auto'
        source.mkdir(parents=True)
        self.text = ('Routine operating notes with no special pressure requirement. ' * 180)
        self.text += '\nAster emergency valve must be tested at 5.75 MPa before restart.\n'
        blocks = [
            {'type': 'text', 'text': 'Maintenance manual', 'text_level': 1, 'page_idx': 0},
            {'type': 'text', 'text': self.text, 'page_idx': 1},
        ]
        (source / 'synthetic_manual_content_list.json').write_text(
            json.dumps(blocks), encoding='utf-8')
        build(self.root / 'parsed', self.root / 'index')
        self.corpus = Corpus(self.root / 'index' / 'corpus.json')

    def test_long_text_focus_can_reach_tail_and_preserves_source_values(self):
        selected = self.corpus.focused_text(1, 'Aster emergency valve test before restart', budget=1800)
        self.assertGreater(self.text.index('Aster emergency valve'), 4500)
        self.assertIn('Aster emergency valve', selected)
        self.assertIn('5.75 MPa', selected)
        self.assertLessEqual(len(selected), 1800)

    def test_short_source_is_returned_unchanged(self):
        self.assertEqual(
            self.corpus.focused_text(0, 'maintenance', budget=500),
            'Maintenance manual',
        )


class RetrievalDiversityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        documents = {
            'aster_manual': [
                {'type': 'text', 'text': 'Aster turbine coolant pressure manual',
                 'text_level': 1, 'page_idx': 0},
                *[
                    {'type': 'image', 'image_caption': [f'Aster turbine diagram {i}'], 'page_idx': 0}
                    for i in range(10)
                ],
                *[
                    {'type': 'text', 'text': f'Aster turbine coolant pressure maintenance section {i}',
                     'page_idx': i}
                    for i in range(1, 8)
                ],
            ],
            'boreal_manual': [
                {'type': 'text', 'text': 'Boreal compressor nitrogen pressure manual',
                 'text_level': 1, 'page_idx': 0},
                {'type': 'text', 'text': 'Boreal compressor nitrogen venting procedure.', 'page_idx': 0},
                {'type': 'table', 'table_caption': ['Boreal compressor nitrogen pressure limits'],
                 'table_body': '<table><tr><th>Pressure limit</th><td>7.2 MPa</td></tr></table>',
                 'page_idx': 0},
            ],
        }
        for name, blocks in documents.items():
            source = self.root / 'parsed' / name / 'auto'
            source.mkdir(parents=True)
            (source / f'{name}_content_list.json').write_text(json.dumps(blocks), encoding='utf-8')
        build(self.root / 'parsed', self.root / 'index')
        config = Config(index_dir=str(self.root / 'index'), use_vector=False,
                        use_rerank=False, candidates=12, use_page_index=True, use_table_rows=True)
        self.retriever = Retriever(config, offline=True)
        self.corpus = self.retriever.corpus

    def test_cross_document_question_keeps_both_sources_reachable(self):
        result = self.retriever.search('Compare Aster turbine and Boreal compressor pressure limits')
        candidate_docs = {self.corpus.nodes[i]['doc'] for i in result['indices']}
        self.assertEqual(candidate_docs, {'aster_manual', 'boreal_manual'})
        self.assertEqual({page['doc'] for page in result['pages'][:6]},
                         {'aster_manual', 'boreal_manual'})
        self.assertEqual(len(result['indices']), len(set(result['indices'])))
        self.assertLessEqual(len(result['indices']), 12)

    def test_dense_page_cannot_exhaust_neighbor_budget_before_second_seed(self):
        first = min(self.corpus.by_doc['aster_manual'])
        second = min(self.corpus.by_doc['boreal_manual'])
        result = self.corpus.neighbors([first, second], limit=4)
        self.assertEqual(len(result), 4)
        self.assertEqual(len(set(result)), 4)
        self.assertTrue(any(i in self.corpus.by_doc['boreal_manual'] for i in result))
        self.assertTrue(any(i in self.corpus.by_doc['aster_manual'] for i in result))
        self.assertFalse({first, second} & set(result))
        self.assertEqual(self.corpus.neighbors([first, second], limit=0), [])


if __name__ == '__main__':
    unittest.main()
