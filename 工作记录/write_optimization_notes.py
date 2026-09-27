from pathlib import Path
import json,hashlib,re
root=Path(__file__).resolve().parents[1]/'参赛作品'
a=root/'artifacts'
test_count=int(re.search(r'Ran (\d+) tests',(a/'unit_tests.txt').read_text('utf-8-sig')).group(1))
before=json.loads((a/'v1_evidence_report.json').read_text('utf-8'))
after=json.loads((a/'retrieval_report.json').read_text('utf-8'))
cmp=json.loads((a/'optimization_comparison.json').read_text('utf-8'))
pct=lambda x:f'{x*100:.2f}%'
keys=[('首位页命中 Hit@1','hit@1'),('前5页全部参考页覆盖','all_pages@5'),('前6页全部参考页覆盖','all_pages@6'),('前10页全部参考页覆盖','all_pages@10'),('实际文本全部参考页覆盖','packed_text_all_pages'),('实际文本参考页召回','packed_text_page_recall')]
table='\n'.join('| '+label+' | '+pct(before['overall'][key])+' | '+pct(after['overall'][key])+' |' for label,key in keys)
ablations=[]
for label,name in [('关闭结构扩展','retrieval_no_graph'),('关闭页面路径','retrieval_no_page'),('关闭邻页补充','retrieval_no_neighbors'),('关闭表格行视图','retrieval_no_table_rows')]:
    r=json.loads((a/(name+'.json')).read_text('utf-8'))
    ablations.append('| '+label+' | '+pct(r['overall']['packed_text_all_pages'])+' |')
baseline_ms=before['mean_retrieval_and_packing_seconds']*1000
new_ms=after['mean_retrieval_and_packing_seconds']*1000
text=f'''# EvidenceRAG V2 优化与验证说明

已完成代码、测试、文档与可复现实验更新。公开30题首轮实际文本证据的全部参考页覆盖由24题提升到28题；尚未测得正式问答Accuracy或比赛总分。

## 已落地的改动

1. **让证据覆盖更多相关页。** 块、文档与向量保持主召回；页面和表格行轮转分享最多20%补充席位，结构邻居轮转扩展。页面词法与块形成的页序融合，前4页后为首位页相邻上下文预留最多2页；跨文档来源保留。在线精排页序权重为2，词法页序为1，离线等权；在线权重效果尚未验证。
2. **减少表格丢行。** 展开rowspan/colspan但保留原值和行列位置，按问题选择命中行、前导行及邻行。长首行不能挤掉小预算中的唯一末行命中；跨表合并范围不会串到下一张表。无法确认的列头不猜测，原图继续作为视觉依据。
3. **把预算用在实际证据上。** 先给前6个候选页各一个相关块，再补上下文；总12块、24,000字符不增加。指明文档页的补查可扩展该页至6块，并结合补充查询选择片段；没有补充查询时也能有限探索未读页。
4. **减少重复服务请求。** 原题加2条子查询，旧版3次嵌入请求、4次重排请求，新版分别1次；以合成测试确认调用结构，不把它宣称为实际加速。引用格式/证据核验失败有一次同证据修订，JSON格式全题最多重试一次，大模型调用上限10次。算术错误保持硬校验。
5. **让改进可复核。** 冻结旧版源码并使用同一新版评测器，输出实际打包证据ID、配对提升/退化、文档分组区间与四项消融。{test_count}项测试通过，真实图像打包检查包含12个文本块、6张图像且无警告。

## 同条件测量

语料为相同100篇，问题为相同30题；候选60、文本12块、24,000字符均相同。离线比较不使用在线向量、重排或VLM，也不执行官方判题。

| 指标 | V1 | V2 |
|---|---:|---:|
{table}

实际文本全部页覆盖：4题提升、0题退化；按文档组配对bootstrap 2,000次，增量95%描述区间+3.33至+26.67个百分点。AllPages@5有4题提升、1题退化，其区间为−3.33至+23.33个百分点，跨越0。不能挑选有利指标隐藏退化。

全部问题和标签已在开发中被查看。固定seed=20260927按文档分成21题开发组和9题回顾检查组，两个集合都不是独立盲测。区间只描述这一公开样本，不保证隐藏题、名次或奖项。

## 消融与成本

| V2变体 | 实际文本全部参考页覆盖 |
|---|---:|
| 完整V2 | {pct(after['overall']['packed_text_all_pages'])} |
{chr(10).join(ablations)}

目前页覆盖指标支持页面与邻页调度收益，未显示表格行视图或结构扩展的额外页覆盖收益。行视图的末行与单位保存由合成用例验证，真实模型答对率收益仍待测量。

本次已加载索引上的离线检索加文本打包均值：V1约{baseline_ms:.2f}毫秒，V2约{new_ms:.2f}毫秒。索引加载分别{before['load_seconds']:.2f}秒、{after['load_seconds']:.2f}秒。新增倒排索引带来CPU和内存开销；图片、网络、模型、加载均不计入前述查询均值。不能用离线毫秒数代替官方端到端时延。

当前仍有2道公开题未在首轮文本中覆盖全部参考页：construction_text_only_0079涉及远距离多页材料，crm_table_required_0105涉及表格相关邻页。它们用于误差分析，题号不进入推理代码；尚未证明后续真实模型补查能答对。

## 复现与正式评分

在参赛作品目录执行：

```bash
python -m unittest discover -s tests -v
python scripts/compare_versions.py --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json
python -m evidence_rag doctor
# 三项服务可用后
python -m evidence_rag serve
# 另开终端
python -m evidence_rag benchmark --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json --output artifacts/e2e
```

后续仍须接入指定Qwen3-VL-8B-Instruct、bge-m3、bge-reranker-v2-m3，运行未修改的官方判题和计分脚本，比较Accuracy、拒答、完整构建成本及逐题延迟。页面覆盖不证明所需数值完整，更不等于问答准确率。正式服务地址、团队信息、账号和签署声明尚待补全。

正式评分还要求完整构建耗时。benchmark支持 `--build-timings artifacts/real_build_timings.json` 读取含正数 `build_time` 的真实计时，或互斥的 `--build-time-s`。不传仍收集回答，但manifest明确计时未就绪；不能把离线结构文件的3.54秒填成完整构建时间。query计时取整个串行循环墙钟时间，包含HTTP和落盘；兼容字段不等于官方判题已完成。

答辩可重点展示：同一证据预算下的28/30页面覆盖、可追溯原图与长表行的演示、三查询只做一次嵌入及一次重排的调用轨迹。对外性能结论应在正式模型测量后填写，当前不宣称达到大于90%的推理目标。
'''
(root/'优化说明.md').write_text(text,'utf-8')
readme=root/'README.md';s=readme.read_text('utf-8')
s=re.sub(r'\d+项测试通过',f'{test_count}项测试通过',s)
s=re.sub(r'新版离线检索加文本打包均值约[\d.]+毫秒，旧版约[\d.]+毫秒',f'新版离线检索加文本打包均值约{new_ms:.2f}毫秒，旧版约{baseline_ms:.2f}毫秒',s)
readme.write_text(s,'utf-8')
files=list((root/'evidence_rag').glob('*.py'))+list((root/'tests').glob('*.py'))
(a/'validation_provenance.json').write_text(json.dumps({'version':'2.0.0','corpus_sha256':after['corpus_sha256'],'source_sha256':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'test_count':test_count,'official_qa_accuracy':None,'official_score':None,'frozen_v1':'benchmarks/v1/PROVENANCE.json'},ensure_ascii=False,indent=2),'utf-8')
print('Wrote optimization notes and validation provenance')
