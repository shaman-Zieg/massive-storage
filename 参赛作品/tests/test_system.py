import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from evidence_rag.agent import Agent, Evidence, calculate, clean_queries, valid_citations
from evidence_rag.evaluate import ground_truth_pages
from evidence_rag.index import BM25, Corpus, build, safe_file, tokens
from evidence_rag.models import Config, ModelError, Models, parse_json
from evidence_rag.retrieval import Retriever, embed_corpus
from evidence_rag.server import validate_payload


class CorpusFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root/'parsed'/'finance_0000001'/'auto'
        source.mkdir(parents=True)
        blocks = [
            {'type':'text','text':'Annual Exchange Report','text_level':1,'page_idx':0},
            {'type':'text','text':'Exchange series in Figure 1. Nigeria prices.','page_idx':0},
            {'type':'table','table_caption':['Table 1 Exchange rates'], 'table_body':'<table><tr><td>2012</td><td>161.6</td></tr><tr><td>2013</td><td>167.9</td></tr></table>','page_idx':1},
            {'type':'image','image_caption':['Figure 1 Exchange rates over time'], 'page_idx':2},
            {'type':'equation','text':'x = (167.9 - 161.6) / 161.6','page_idx':2}]
        self.input_path = source/'finance_0000001_content_list.json'
        self.input_path.write_text(json.dumps(blocks),'utf-8')
        # This file must never be ingested.
        (self.root/'parsed'/'queries_30.json').write_text('[{"answer":"LEAK_SENTINEL"}]','utf-8')
        self.cfg = Config(parsed_root=str(self.root/'parsed'), pdf_root=str(self.root/'pdf'),
            index_dir=str(self.root/'index'), legacy_storage=str(self.root/'legacy'),
            use_vector=False,use_rerank=False,use_planner=False,use_vision=False)
        self.stats = build(self.cfg.parsed_root,self.cfg.index_dir)
        self.corpus = Corpus(self.root/'index'/'corpus.json')

    def test_counts_and_one_based_pages(self):
        self.assertEqual(self.stats['documents'],1)
        self.assertEqual(self.stats['blocks'],5)
        self.assertEqual(self.corpus.nodes[2]['page'],2)

    def test_no_qa_leak(self):
        self.assertNotIn('LEAK_SENTINEL',(self.root/'index'/'corpus.json').read_text('utf-8'))

    def test_cross_page_reference_edge(self):
        self.assertIn(3,self.corpus.edges[1])

    def test_html_preserved(self):
        self.assertIn('<table>',self.corpus.nodes[2]['text'])

    def test_relocation_stable(self):
        other=self.root/'index2'
        build(self.cfg.parsed_root,other)
        self.assertEqual((self.root/'index'/'corpus.json').read_bytes(),(other/'corpus.json').read_bytes())

    def test_retrieval_exact_value(self):
        result=Retriever(self.cfg,offline=True).search('161.6 167.9 exchange')
        # Both the table and the equation contain these values; either may rank first.
        self.assertIn({'doc':'finance_0000001','page':2},result['pages'][:3])

    def test_graph_ablation(self):
        self.cfg.use_graph=False
        self.assertNotIn('graph',Retriever(self.cfg,offline=True).search('exchange')['routes'])

    def test_context_budget(self):
        self.cfg.context_chars=350
        content,sources,stats=Evidence(self.cfg,self.corpus).pack('exchange',[2,1,3],[],time.monotonic()+30)
        self.assertLessEqual(stats['text_chars'],350)
        self.assertTrue(sources)

    def test_official_pdf_origin_suffix(self):
        pdf_root=Path(self.cfg.pdf_root)
        pdf_root.mkdir()
        pdf=pdf_root/'finance_0000001_origin.pdf'
        pdf.write_bytes(b'%PDF-1.4\n')
        self.assertEqual(Evidence(self.cfg,self.corpus).pdfs['finance_0000001'],pdf)

    def test_agent_accepts_verified_answer(self):
        ident='finance_0000001:p2:b2'
        responses=[{'sufficient':True,'answer':f'167.9 [{ident}]','citations':[ident]},
                   {'supported':True,'reason':'supported'}]
        with patch.object(Models,'chat',side_effect=responses):
            result=Agent(self.cfg).answer('2013 exchange rate')
        self.assertEqual(result['status'],'verified')
        self.assertEqual(result['citations'][0]['page'],2)

    def test_agent_rejects_bad_citation(self):
        with patch.object(Models,'chat',return_value={'sufficient':True,'answer':'x [invented:p1:b0]','citations':['invented:p1:b0']}):
            result=Agent(self.cfg).answer('exchange')
        self.assertEqual(result['status'],'insufficient_evidence')

    def test_agent_rejects_bad_arithmetic(self):
        ident='finance_0000001:p2:b2'
        responses=[{'sufficient':True,'answer':f'9 [{ident}]','citations':[ident],
                    'calculations':[{'expression':'167.9-161.6','claimed_result':9}]}, {'supported':True}]
        with patch.object(Models,'chat',side_effect=responses):
            result=Agent(self.cfg).answer('exchange change')
        self.assertEqual(result['status'],'insufficient_evidence')

    def test_agent_retrieves_again_when_missing(self):
        ident='finance_0000001:p2:b2'
        responses=[{'sufficient':False,'missing_queries':['161.6 167.9']},
                   {'sufficient':True,'answer':f'6.3 [{ident}]','citations':[ident],
                    'calculations':[{'expression':'167.9-161.6','claimed_result':6.3}]}, {'supported':True}]
        with patch.object(Models,'chat',side_effect=responses):
            result=Agent(self.cfg).answer('change in rate')
        self.assertEqual(result['status'],'verified')
        self.assertEqual(len(result['trace']),2)

    def test_actual_nano_index_and_stale_manifest(self):
        try:
            import numpy as np
            import nano_vectordb
        except ImportError:
            self.skipTest('NanoVectorDB optional in offline-only environments')
        self.cfg.embedding_dim=4
        self.cfg.use_vector=True
        model=Models(self.cfg)
        with patch.object(model,'embed',side_effect=lambda texts: np.tile(np.array([[1,2,3,4]],dtype='float32'),(len(texts),1))):
            embed_corpus(self.cfg,model,batch_size=2)
            retriever=Retriever(self.cfg)
            self.assertTrue(retriever.native_vectors)
            self.assertTrue(retriever.search('exchange',model)['indices'])
        payload=json.loads((self.root/'index'/'corpus.json').read_text('utf-8'))
        payload['nodes'][0]['text']='Changed document'
        (self.root/'index'/'corpus.json').write_text(json.dumps(payload),'utf-8')
        with self.assertRaises(ModelError): Retriever(self.cfg)


class Contracts(unittest.TestCase):
    def test_payload_rejects_label_injection(self):
        for key in ['answer','gt_image_paths','longdoc_image_paths','sample_id']:
            with self.assertRaises(ValueError): validate_payload({'question':'q',key:'secret'})
        self.assertEqual(validate_payload({'question':'hello'}),'hello')

    def test_payload_validation(self):
        for value in ['',None,[],123,'q'*8001]:
            with self.assertRaises(ValueError): validate_payload({'question':value})

    def test_path_traversal(self):
        with self.assertRaises(ValueError): safe_file(Path.cwd(),'../private')

    def test_arithmetic_and_injection(self):
        self.assertAlmostEqual(calculate('(167.9-161.6)/161.6*100'),3.89851485148516)
        for expr in ["__import__('os').getcwd()",'2**9999','float("nan")','True+1','1e99']:
            with self.assertRaises(ValueError): calculate(expr)

    def test_inline_citation_must_match(self):
        source={'doc:p1:b1':{}}
        self.assertTrue(valid_citations({'answer':'x [doc:p1:b1]','citations':['doc:p1:b1']},source))
        self.assertFalse(valid_citations({'answer':'x [wrong:p1:b1]','citations':['doc:p1:b1']},source))

    def test_json_malformed_and_nonobject(self):
        self.assertEqual(parse_json('```json\n{"ok":true}\n```'),{'ok':True})
        for value in ['[]','not JSON']:
            with self.assertRaises(ModelError): parse_json(value)

    def test_zero_or_misordered_embeddings(self):
        cfg=Config(embedding_dim=2)
        model=Models(cfg)
        for response in [{'data':[{'index':0,'embedding':[0,0]}]},
                         {'data':[{'index':1,'embedding':[1,0]}]},
                         {'data':[{'index':0,'embedding':[1]}]}]:
            with patch.object(model,'post',return_value=response):
                with self.assertRaises(ModelError): model.embed(['a'])

    def test_rerank_duplicate_index(self):
        model=Models(Config())
        with patch.object(model,'post',return_value={'results':[{'index':0},{'index':0}]}):
            with self.assertRaises(ModelError): model.rerank('q',['a','b'])

    def test_deadline(self):
        with self.assertRaises(ModelError): Models(Config(),time.monotonic()-1).post('http://localhost',{},'llm')

    def test_bm25_chinese_and_no_match(self):
        self.assertIn('存储',tokens('存储系统'))
        bm=BM25(['storage caching','unrelated'])
        self.assertEqual(bm.search('storage')[0][0],0)
        self.assertEqual(bm.search('不存在'),[])

    def test_unicode_latex_formula_alignment(self):
        self.assertEqual(tokens('ω₂ β2 η²'),tokens(r'\omega_2 \beta_2 \eta^2'))

    def test_reference_path_parser(self):
        self.assertEqual(ground_truth_pages({'gt_image_paths':['images/finance/00123/00123_page_0016.png']}),{('finance_00123',16)})

    def test_queries_bounded_and_deduplicated(self):
        self.assertEqual(clean_queries(['a','a',None,'b','c']),['a','b'])


if __name__=='__main__':
    unittest.main(verbosity=2)
