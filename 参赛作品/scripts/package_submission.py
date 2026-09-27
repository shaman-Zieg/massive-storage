"""Package explicit submission files, not credentials, caches, datasets or runtimes."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]


def package(destination):
    files=[]
    for folder in ['evidence_rag','tests','scripts','benchmarks']:
        files.extend(p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    for name in ['README.md','优化说明.md','THIRD_PARTY_NOTICES.md','requirements.txt','config.json','设计文档.docx','作品原创性声明_待签署.docx']:
        p=root/name
        if not p.is_file(): raise FileNotFoundError(name)
        files.append(p)
    files.extend(p for p in (root/'artifacts').glob('*') if p.is_file() and p.suffix in ['.json','.txt','.md'])
    files.extend([root/'artifacts/index/corpus.json',root/'artifacts/index/build_stats.json'])
    manifest={p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}
    destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(set(files)): z.write(p,'参赛作品/'+p.relative_to(root).as_posix())
        z.writestr('参赛作品/MANIFEST.sha256.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    if destination.stat().st_size>=500_000_000: raise ValueError('Submission exceeds 500 MB')
    with zipfile.ZipFile(destination) as z:
        if z.testzip(): raise ValueError('ZIP integrity check failed')
    return {'path':str(destination),'bytes':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'files':len(files)+1}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--team',required=True);p.add_argument('--account',required=True);p.add_argument('--output',default='..')
    a=p.parse_args()
    if any(re.search(r'[<>:"/\\|?*\x00-\x1f]',v) or not v.strip() for v in [a.team,a.account]):
        p.error('Invalid team or account filename characters')
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests'],cwd=root,check=True)
    target=Path(a.output)/f'Agentic AI 多模态表征与检索-{a.team}-{a.account}.zip'
    print(json.dumps(package(target),ensure_ascii=False,indent=2))
    print('请人工确认原创性声明已签署、队伍信息已填全、正式评测已完成。')
