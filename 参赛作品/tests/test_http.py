"""Synthetic local HTTP tests. These measure contracts, NOT model answer accuracy."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from evidence_rag.agent import Agent
from evidence_rag.models import Models
from evidence_rag.retrieval import embed_corpus
from evidence_rag.server import make_handler
from test_system import CorpusFixture


class HTTPContracts(CorpusFixture):
    # Reuse fixture setup without repeating inherited tests in this module.
    pass


class Integration(unittest.TestCase):
    def setUp(self):
        self.fixture=CorpusFixture()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.seen=[]
        seen=self.seen

        class FakeModels(BaseHTTPRequestHandler):
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path,value))
                if self.path=='/embedding':
                    response={'data':[{'index':i,'embedding':[1,2,3,4]} for i,_ in enumerate(value['input'])]}
                elif self.path=='/rerank':
                    response={'results':[{'index':i,'relevance_score':1/(i+1)} for i,_ in enumerate(value['documents'])]}
                else:
                    system=value['messages'][0]['content']
                    if 'Plan retrieval' in system:
                        result={'queries':['2013 exchange rate'],'needs_visual':False}
                    elif 'Check whether' in system:
                        result={'supported':True,'reason':'synthetic fixture'}
                    else:
                        result={'answer':'167.9 [finance_0000001:p2:b2]',
                                'citations':['finance_0000001:p2:b2'],'sufficient':True}
                    response={'choices':[{'message':{'content':json.dumps(result)},'finish_reason':'stop'}]}
                raw=json.dumps(response).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args): pass

        server=ThreadingHTTPServer(('127.0.0.1',0),FakeModels)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def cleanup():
            server.shutdown();server.server_close();thread.join(3)
        self.addCleanup(cleanup)
        self.cfg=self.fixture.cfg
        base=f'http://127.0.0.1:{server.server_port}'
        self.cfg.llm_url=base+'/chat'
        self.cfg.embedding_url=base+'/embedding'
        self.cfg.rerank_url=base+'/rerank'
        self.cfg.embedding_dim=4

    def test_real_http_adapters_and_agent(self):
        self.cfg.use_rerank=True
        self.cfg.use_planner=True
        self.cfg.use_vector=True
        embed_corpus(self.cfg,Models(self.cfg),batch_size=3)
        result=Agent(self.cfg).answer('2013 exchange rate')
        self.assertEqual(result['status'],'verified')
        self.assertEqual({call['service'] for call in result['model_calls']},{'llm','embedding','rerank'})
        self.assertEqual({path for path,_ in self.seen},{'/chat','/embedding','/rerank'})

    def test_service_rejects_labels_and_returns_compatible_response(self):
        agent=Agent(self.cfg)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(agent))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f'http://127.0.0.1:{server.server_port}/query'
            request=urllib.request.Request(url,json.dumps({'question':'2013 exchange rate'}).encode(),{'Content-Type':'application/json'})
            with urllib.request.urlopen(request) as response: result=json.load(response)
            self.assertIn('answer',result);self.assertIn('query_time_s',result)
            request=urllib.request.Request(url,b'{"question":"q","answer":"leak"}',{'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as failure: urllib.request.urlopen(request)
            self.assertEqual(failure.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join(3)


# Only Integration is collected here; CorpusFixture lives in test_system.py.
def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(Integration)
