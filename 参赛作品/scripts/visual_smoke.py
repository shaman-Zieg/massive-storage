"""Check real source-image packing without sending data to any model."""
import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from evidence_rag.models import Config
from evidence_rag.retrieval import Retriever
from evidence_rag.agent import Evidence

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question',required=True)
    parser.add_argument('--config',default=str(ROOT/'config.json'))
    parser.add_argument('--output',default=str(ROOT/'artifacts/visual_evidence_smoke.json'))
    args=parser.parse_args();cfg=Config.load(args.config)
    retrieval=Retriever(cfg,offline=True);found=retrieval.search(args.question)
    content,sources,stats=Evidence(cfg,retrieval.corpus).pack(args.question,found['indices'],found['pages'],time.monotonic()+cfg.query_deadline)
    images=[]
    for index,item in enumerate(content):
        if item['type']=='image_url':
            raw=base64.b64decode(item['image_url']['url'].split(',',1)[1])
            with Image.open(io.BytesIO(raw)) as picture:
                dimensions=picture.size;picture.verify()
            images.append({'label':content[index-1]['text'],'dimensions':dimensions,'bytes':len(raw)})
    result={'mode':'real_corpus_no_model_visual_packing','question':args.question,'sources':sources,
            'stats':stats,'images':images,'answer_accuracy':None,'note':'Image decoding/provenance check only; not VLM reading or answer judging.'}
    assert stats['images']==len(images)<=cfg.max_images
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'text_sources':sum(s['kind']!='page_image' for s in sources.values()),'stats':stats,'images':images},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
