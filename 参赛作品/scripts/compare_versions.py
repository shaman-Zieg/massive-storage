"""Reproduce exposed-public-set diagnostics using one evaluator for both versions.

The frozen V1 package is never on the inference import path. No answer labels are
passed to either Retriever or Evidence. This is not an official QA evaluation.
"""
import argparse
import importlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from evidence_rag.models import Config
from evidence_rag import evaluate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions',required=True)
    parser.add_argument('--config',default=str(ROOT/'config.json'))
    parser.add_argument('--output',default=str(ROOT/'artifacts'))
    args=parser.parse_args()
    cfg=Config.load(args.config)
    folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    init=ROOT/'benchmarks/v1/evidence_rag/__init__.py'
    spec=importlib.util.spec_from_file_location('baseline_rag',init,submodule_search_locations=[str(init.parent)])
    baseline=importlib.util.module_from_spec(spec);sys.modules[spec.name]=baseline;spec.loader.exec_module(baseline)
    old_r=importlib.import_module('baseline_rag.retrieval').Retriever
    old_e=importlib.import_module('baseline_rag.agent').Evidence
    old_path=folder/'v1_evidence_report.json'
    with patch.object(evaluate,'Retriever',old_r),patch.object(evaluate,'Evidence',old_e):
        old_cfg=replace(cfg,use_page_index=False,use_page_neighbors=False,use_table_rows=False)
        before=evaluate.retrieval_report(old_cfg,args.questions,old_path)
    after=evaluate.retrieval_report(cfg,args.questions,folder/'retrieval_report.json',baseline=old_path)
    for field,name in [('use_graph','retrieval_no_graph.json'),
                       ('use_page_index','retrieval_no_page.json'),
                       ('use_page_neighbors','retrieval_no_neighbors.json'),
                       ('use_table_rows','retrieval_no_table_rows.json')]:
        ablation=Config.load(args.config);setattr(ablation,field,False)
        evaluate.retrieval_report(ablation,args.questions,folder/name)
    comparison=after['paired_comparison']
    evaluate.save_json(folder/'optimization_comparison.json',comparison)
    print(json.dumps({'v1':before['overall'],'v2':after['overall'],
                      'comparison':str(folder/'optimization_comparison.json')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
