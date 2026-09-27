from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from copy import deepcopy
import hashlib, json, re
from lxml import etree as E

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'参赛作品'
REF=ROOT/'挑战赛道作品设计文档模板.docx'
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS={'w':W}
def tag(n): return '{'+W+'}'+n
def el(n,attrs=None,text=None):
    x=E.Element(tag(n))
    for k,v in (attrs or {}).items(): x.set(tag(k),str(v))
    if text is not None: x.text=text
    return x
def add(x,n,attrs=None,text=None):
    child=el(n,attrs,text);x.append(child);return child

stats=json.loads((OUT/'artifacts/index/build_stats.json').read_text('utf-8'))
report=json.loads((OUT/'artifacts/retrieval_report.json').read_text('utf-8'))
abl=json.loads((OUT/'artifacts/retrieval_no_graph.json').read_text('utf-8'))
test_log=(OUT/'artifacts/unit_tests.txt').read_text('utf-8-sig')
test_count=re.search(r'Ran (\d+) tests',test_log).group(1)
assert 'OK' in test_log and 'FAILED' not in test_log
assert hashlib.sha256(REF.read_bytes()).hexdigest()=='e4b0575a9bc948f1cbdbf47b3a707c9a85789dd185e23dc0d9eda554efc8dfa4'
parts={}
with ZipFile(REF) as z:
    for n in z.namelist():parts[n]=z.read(n)
document=E.fromstring(parts['word/document.xml']);body=document.find('w:body',NS)
original=list(body);chapter_template=deepcopy(original[48]);final_section=deepcopy(original[-1])
for node in list(body):body.remove(node)
for node in original[:21]:body.append(deepcopy(node))

# Modify only the underlined value runs of the retained cover.
cover_values={12:'Agentic AI 多模态表征与检索',13:'待填写',14:'待填写',15:'待填写'}
for idx,value in cover_values.items():
    p=body[idx]; runs=p.findall('w:r',NS)
    for r in runs[1:]:p.remove(r)
    r=deepcopy(runs[-1]); ts=r.findall('.//w:t',NS)
    if ts:
        ts[0].text=value
        for t in ts[1:]:t.text=''
    p.append(r)

styles=E.fromstring(parts['word/styles.xml'])
title_style=el('style',{'type':'paragraph','styleId':'Title'})
add(title_style,'name',{'val':'Title'});add(title_style,'basedOn',{'val':'a'});add(title_style,'qFormat')
styles.append(title_style)
for idx in (3,4):
    pp=body[idx].find('w:pPr',NS)
    pp.insert(0,el('pStyle',{'val':'Title'}))
parts['word/styles.xml']=E.tostring(styles,encoding='UTF-8',xml_declaration=True,standalone=True)

def paragraph(text,kind='body',newpage=False):
    if kind=='chapter':
        p=deepcopy(chapter_template)
        for c in list(p):
            if c.tag!=tag('pPr'):p.remove(c)
        pp=p.find('w:pPr',NS)
    else:
        p=el('p');pp=add(p,'pPr')
        if kind=='sub':add(pp,'pStyle',{'val':'2'})
        add(pp,'spacing',{'line':360,'lineRule':'auto','before':120 if kind=='sub' else 0,'after':80})
        add(pp,'jc',{'val':'left' if kind in ('sub','code') else 'both'})
        if kind=='body':add(pp,'ind',{'firstLine':480})
        add(pp,'snapToGrid',{'val':0})
    add(pp,'widowControl')
    if kind in ('chapter','sub'):add(pp,'keepNext')
    if newpage:add(pp,'pageBreakBefore')
    r=add(p,'r');rp=add(r,'rPr')
    font='SimHei' if kind in ('chapter','sub') else 'SimSun'
    add(rp,'rFonts',{'ascii':font,'hAnsi':font,'eastAsia':font,'cs':font})
    add(rp,'sz',{'val':32 if kind=='chapter' else 28 if kind=='sub' else 24})
    add(rp,'szCs',{'val':32 if kind=='chapter' else 28 if kind=='sub' else 24})
    add(rp,'color',{'val':'000000'})
    if kind in ('chapter','sub'):add(rp,'b')
    add(r,'t',text=text)
    body.append(p)
    return p

def table(headers,rows,widths):
    t=el('tbl');pr=add(t,'tblPr')
    add(pr,'tblW',{'w':sum(widths),'type':'dxa'});add(pr,'tblLayout',{'type':'fixed'})
    borders=add(pr,'tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:add(borders,edge,{'val':'single','sz':4,'color':'D9D9D9'})
    margins=add(pr,'tblCellMar')
    for edge in ['top','bottom']:add(margins,edge,{'w':70,'type':'dxa'})
    for edge in ['left','right']:add(margins,edge,{'w':100,'type':'dxa'})
    grid=add(t,'tblGrid')
    for w in widths:add(grid,'gridCol',{'w':w})
    for ri,row in enumerate([headers]+rows):
        tr=add(t,'tr');trp=add(tr,'trPr');add(trp,'cantSplit')
        if ri==0:add(trp,'tblHeader')
        for ci,value in enumerate(row):
            cell=add(tr,'tc');cp=add(cell,'tcPr');add(cp,'tcW',{'w':widths[ci],'type':'dxa'});add(cp,'vAlign',{'val':'center'})
            if ri==0:add(cp,'shd',{'fill':'EDEDED','val':'clear'})
            p=add(cell,'p');pp=add(p,'pPr');add(pp,'spacing',{'line':360,'lineRule':'auto','after':0});add(pp,'snapToGrid',{'val':0})
            add(pp,'jc',{'val':'left' if ci==0 or len(str(value))>18 else 'center'})
            r=add(p,'r');rp=add(r,'rPr');add(rp,'rFonts',{'ascii':'SimSun','hAnsi':'SimSun','eastAsia':'SimSun'});add(rp,'sz',{'val':24});add(rp,'color',{'val':'000000'})
            if ri==0:add(rp,'b')
            add(r,'t',text=str(value))
    body.append(t)
    paragraph('','code')

def p(text):paragraph(text)
def h(text,newpage=False):paragraph(text,'sub',newpage)
def c(text):paragraph(text,'code')
def pct(value):return f'{value*100:.2f}%'

paragraph('第一章 方案设计','chapter',True)
h('1.1 设计目标与实现范围')
p('本作品选择 Agentic AI 多模态表征与检索赛题，实现 EvidenceRAG 多模态问答系统。系统以可回查的文档页码作为证据边界，把文本、图表、表格和公式组织为带来源的内容块，再以多路检索、原图阅读和迭代核验回答复杂问题。设计目标是在赛题规定模型与评测环境下达到问答准确率大于90%，同时约束构建和查询开销。')
p('当前已完成新增源码、100篇文档的结构索引、本地检索诊断与功能测试。正式模型服务尚未连通，因此本报告不把页面召回率作为问答准确率，也不声明已经达到赛题目标。全部结果按已实现、已测量与待正式环境验证区分说明。')
h('1.2 总体流程')
table(['阶段','处理与输出'],[
 ['解析输入','读取官方 MinerU 内容块和原始 PDF；解析阶段沿用官方附件。'],
 ['统一表征','生成文档、页码、块序号、模态、正文与图片路径；保留表格结构。'],
 ['多路召回','结合块级 BM25、文档级定位、NanoVectorDB 与文档结构关系。'],
 ['证据阅读','重排后选择文本、完整 PDF 页面和局部图像，送入统一视觉模型。'],
 ['迭代核验','判断证据缺口并补查；验证引用与计算；返回有出处的回答。']],[1700,7120])
p('系统只接收用户问题。标准答案、参考图片路径和题目编号留在独立评测进程中，不参与检索、规划或回答。运行日志记录实际模型调用和耗时，便于识别回答质量与效率之间的取舍。')

h('1.3 带来源的多模态表征',True)
p('语料组织以官方 content_list 为准。每个块使用“文档名:p页码:b块序号”作为稳定标识，页码从1开始；工作目录迁移不改变标识。正文段落保留章节上下文，表格保留包含 rowspan 和 colspan 的 HTML，公式保留 LaTeX 原文，图像关联原始裁剪文件和所属页面。')
table(['字段','用途'],[
 ['id 与 doc','确定块和所属文档，作为引用及向量记录主键。'],
 ['page 与 ordinal','提供准确的 PDF 页码和块顺序，不从向量相似度猜页码。'],
 ['kind 与 bbox','保留文本、图像、表格、公式类型及原始区域坐标。'],
 ['text 与 section','保存解析正文及章节标题，支持词法定位和证据呈现。'],
 ['description','复用官方图表生成描述，明确作为可能有误的辅助信息。'],
 ['image','保存相对于解析根目录的文件路径；读取时检查目录边界。']],[2200,6620])
p('图表描述通过图片文件名精确关联，不将历史问答缓存纳入语料。当前关联1,094个带描述的块，解析图像文件可定位1,375个。生成描述只用于补充召回和上下文，不取代原始图表证据。')
p('结构关系包括同页相邻块、同页视觉块，以及正文对 Figure 或 Table 编号的引用。当前生成65,388条有向关联记录。这是文档结构图，并非重新抽取的通用实体知识图谱；关系只影响候选扩展，答案仍须引用原文证据。')

h('1.4 多路召回与候选融合',True)
p('块级 BM25 处理专名、年份、单位和精确数值；文档级 BM25 从整篇材料选择4个候选文档，再交错取回各文档的高分块，保留歧义问题的多个来源。分词对中英文分别处理，并将 Unicode 希腊字母及上下标规范化，使问题中的 ω₂ 能与文档中的 LaTeX 变量匹配。')
p('正式模式使用规定的 bge-m3 嵌入和 NanoVectorDB。默认复用官方4,139条、1,024维 chunk 向量。因为旧索引缺少可靠页码，向量结果仅用于确定候选文档，再检索有确切来源的块。另提供重新生成块向量的路径，便于在正式环境比较精度与构建成本。')
c('BM25 参数为 k1 = 1.2，b = 0.75。')
c('融合分数 S(d) = Σ wᵣ / (60 + rankᵣ(d))。')
table(['召回路径','权重','当前角色'],[
 ['块级关键词','1.00','直接查找有来源的内容块'],
 ['文档级定位','0.65','约束材料范围并保留多文档候选'],
 ['向量语义','1.00','补充语义相关材料'],
 ['结构关系','0.35','补足邻近内容与图表引用']],[2400,1000,5420])
p('融合后最多保留60个块，使用 bge-reranker-v2-m3 重排。多个子问题的结果汇合后，再对原问题重排，降低子问题偏移。页面排序以最佳块为主，并给予同页至多3个支持块有限加分，避免长页仅靠块数量获得优势。')
p('结构扩展限制为一次、最多40个新块，不进行无界图遍历。权重和候选预算是当前工程配置，不宣称已找到全局最优参数；正式调参需要独立验证集与端到端耗时记录。')

h('1.5 主动补查与视觉证据核验',True)
p('Agent 首先生成至多2条互补检索语句，并保留原问题。每轮执行召回、重排、证据打包和回答检查。当缺少年份、对照项、图例或表头等证据时，模型返回新的检索语句，下一轮为新增候选保留容量。相同语句不重复执行，最多3轮，避免反复检索同一材料。')
p('每轮最多选择12个文本块，每页至多3块，证据正文预算为24,000字符；最多提供6张图片，优先给出排名靠前的3张完整页面，再用裁剪图补足细小数值。整页保留图例、坐标轴和段落关系，裁剪图提高局部阅读分辨率。图片长边上限1,600像素。')
p('生成模型必须返回回答、引用、证据是否充分、缺失检索语句和计算表达式。系统检查引用是否来自本轮实际发送的证据，且行内引用与引用清单一致。数值计算通过受限语法树执行，只允许数字及加减乘除，不执行模型生成的程序代码。')
p('候选回答通过初步检查后，系统再次调用相同的统一模型进行证据核验。该步骤是独立的一次调用，并非独立模型，因此不能消除同模型相关错误。只有证据核验与算术核验都通过才返回 verified；否则继续补查，预算耗尽则返回证据不足。该状态表示内部核验通过，不等同于官方判题正确。')
h('1.6 实际材料的回查示例')
p('公开金融样例询问 Nigeria BDC 汇率变化。程序能够定位 finance_3769357 的第16页，并打包该页完整图像及相关裁剪图。人工检查原图可见 Q1 2012 为161.6、Q4 2013 为167.9 NGN/USD，差额为6.3。该例用于验证页码、系列和单位的可回查性；尚未作为真实模型端到端答对的证据。')

paragraph('第二章 关键代码说明','chapter',True)
h('2.1 模块划分')
table(['代码文件','已实现职责'],[
 ['index.py','读取解析块、BM25 分词和检索、构建关系与语料指纹。'],
 ['retrieval.py','多路候选融合、NanoVectorDB 查询、重排和向量断点构建。'],
 ['models.py','规定模型的 HTTP 适配、超时与返回结构验证。'],
 ['agent.py','问题规划、证据打包、PDF 回查、补查及引用和算术核验。'],
 ['server.py','提供 /query 与 /health；只接受问题字段。'],
 ['evaluate.py','页面召回诊断、端到端客户端、计时和结果保存。'],
 ['tests 与 scripts','功能测试、模拟 HTTP 集成测试、本机检查和提交打包。']],[2600,6220])
h('2.2 核心执行顺序')
c('读取问题 → 规划补充查询 → 多路召回 → 候选重排')
c('候选重排 → 选取文本与图片 → 生成候选回答')
c('候选回答 → 引用与计算检查 → 证据核验')
c('通过则输出；未通过则补查；达到预算则返回证据不足')
p('正式服务启动时加载语料与向量索引。模型请求使用 Python 标准库 HTTP 客户端，不绑定特定 GPU 或 NPU 框架；设备部署由赛题提供的 vLLM 服务负责。新增检索与调度代码不修改官方 benchmark、判分程序或模型权重。')

h('2.3 接口与执行预算',True)
p('服务默认监听127.0.0.1:8080，POST /query 请求只包含 question。返回 answer 和 query_time_s，兼容官方测试客户端，同时增加 status、citations、trace 和 model_calls 用于复核。包含标准答案、参考图片路径等额外字段的请求返回400，模型不可用返回503。')
table(['配置项','默认值','说明'],[
 ['max_rounds','3','最多执行3轮取证与核验'],
 ['candidates','60','每次融合后的候选块数'],
 ['evidence_blocks','12','每轮文本证据上限'],
 ['max_images','6','整页与局部图像合计上限'],
 ['context_chars','24000','正文证据字符预算'],
 ['request_timeout','90秒','单次模型请求等待上限'],
 ['query_deadline','240秒','查询模型及渲染预算'],
 ['embedding_dim','1024','规定的 bge-m3 向量维度']],[3200,1400,4220])
p('查询预算通过单调时钟约束模型调用和页面渲染；本地预处理、操作系统调度和响应序列化仍可能增加少量时间，因此并非实时系统的硬截止保证。当前服务串行处理请求，适配随附测试流程；高并发服务扩展尚未测量。')
p('密钥从 RAG_LLM_API_KEY、RAG_EMBEDDING_API_KEY、RAG_RERANK_API_KEY 环境变量读取。日志不记录鉴权请求头和图片正文。输入材料只作为证据，不授权模型调用系统命令；引用错误、零向量、重复重排索引和异常响应均显式报错。')

h('2.4 构建和部署过程',True)
p('第一步，将官方解析数据、原始 PDF 和原有索引放入配置指定的位置。所有相对路径相对于 config.json 解析。PDF 兼容官方文件名中的 _origin 后缀；缺少独立 PDF 目录时，可从解析目录中的原始 PDF 回查。')
c('python -m pip install -r requirements.txt')
c('python -m evidence_rag build')
c('python -m unittest discover -s tests -v')
p('第二步，按组委会要求部署 Qwen3-VL-8B-Instruct、bge-m3 和 bge-reranker-v2-m3，将服务地址和 served-model-name 填入配置。完整页面渲染要求 Poppler 的 pdftoppm 在 PATH 中。接口检查通过后启动查询服务。')
c('python -m evidence_rag doctor')
c('python -m evidence_rag serve')
p('第三步，将官方客户端的 RAG_BINDING_HOST 配置为本服务 /query 地址，运行公开验证集并保存原始回答、逐题时延和轨迹。使用未修改的官方判断模型与评分脚本得出 Accuracy 和总分，不能从检索报告推导问答分数。详细命令和目录说明见 README.md。')
h('2.5 索引一致性与中断恢复')
p('结构索引记录每份 content_list 的 SHA-256，文件通过临时文件写入后替换，避免读取半成品。重新嵌入模式每批保存向量，并记录语料指纹、模型名称和维度；恢复时不匹配即拒绝继续。完整构建后再替换正式索引。')
p('可选 embed 命令会为14,881个块调用规定嵌入模型，其构建时间必须计入正式评测。目前仅对小型合成语料测试过该路径，未在正式模型上完成全量重建。默认复用官方向量的方案与全量重建方案需分别记录构建成本，不能混用时间。')

paragraph('第三章 测试及分析','chapter',True)
h('3.1 本地环境与数据规模')
table(['项目','实际情况'],[
 ['操作系统','Windows 11，版本10.0.26200'],
 ['Python','3.12.14'],
 ['本机 GPU','RTX 4060 Laptop，约8GB显存；本次离线测试未使用 GPU 推理'],
 ['规定模型服务','三个默认本地端点均未连通'],
 ['输入文档与页面','100篇；1,374个包含解析块的页面'],
 ['文本与视觉块','文本13,494；图像854；表格297；公式236'],
 ['结构索引大小',f"{stats['index_bytes']:,}字节，约{stats['index_bytes']/1024/1024:.2f} MiB"]],[2600,6220])
p(f"本地结构索引构建实测为{stats['build_seconds']:.4f}秒。该时间只包括读取已解析语料、关联已有描述和写出结构索引，不包括官方解析、描述生成和既有向量构建，不能直接当作官方完整构建时延。")
h('3.2 功能与协议测试')
p(f'共执行{test_count}项测试，全部通过，记录保存在 artifacts/unit_tests.txt。覆盖确定页码、图表跨页引用、数据隔离、路径边界、公式符号对齐、引用一致性、算术错误拒绝、第二轮补查、真实 NanoVectorDB 读写和索引不匹配拒绝。')
p('HTTP 集成测试通过本地模拟服务验证嵌入、重排、生成和回答服务的序列化与状态流转。模拟数据不进入公开验证集成绩。真实材料回查测试成功打包3张完整页面和2张裁剪图，未产生图片缺失警告；该检查不包含模型推理。')

h('3.3 公开验证集的离线检索结果',True)
p('使用全部100篇材料作为检索库，对公开30道问题逐题运行离线检索。仅问题文本传入检索器，检索后才与参考页集合比较。此模式未调用实时嵌入、神经重排、视觉问答或官方判题。公开题目已用于开发诊断，不能当作独立盲测集。')
p('Hit@K 表示前K个候选页至少命中一个参考页的题目比例；AllPages@K 表示前K页覆盖该题全部参考页的比例；PageRecall@K 是逐题参考页召回率的平均。参考页可能多于一页，因此三个指标不能互相替代。')
table(['K','Hit@K','AllPages@K','PageRecall@K'],[
 [str(k),pct(report['overall'][f'hit@{k}']),pct(report['overall'][f'all_pages@{k}']),pct(report['overall'][f'page_recall@{k}'])] for k in (1,3,5,10,20)], [700,2400,2700,3020])
p('前5页至少命中参考页的题目为29/30，但完整覆盖全部参考页的题目为21/30；前10页至少命中30/30，完整覆盖26/30。这说明候选定位具有一定效果，但跨页证据完整性仍然是主要短板，也不能据此判断真实模型会正确读取和推理。')
p(f"已加载索引上的平均离线查询时间为{report['mean_query_seconds']*1000:.1f}毫秒，P95为{report['p95_query_seconds']*1000:.1f}毫秒；本次索引加载约{report['load_seconds']:.2f}秒。该测量不含页面渲染、网络、模型调用和判题。30条样本的短耗时容易受系统状态影响，不作为官方时延结论。")

h('3.4 结构关系消融与误差分析',True)
p('保持语料、查询和候选数不变，仅关闭结构关系召回，得到如下对比。两组都属于离线检索；这不是与完整 RAG-Anything 基线的比较，也没有证明正式问答准确率提升。')
table(['指标','无结构扩展','有结构扩展'],[
 [label,pct(abl['overall'][key]),pct(report['overall'][key])] for label,key in [('Hit@1','hit@1'),('Hit@5','hit@5'),('AllPages@5','all_pages@5'),('AllPages@10','all_pages@10'),('PageRecall@10','page_recall@10')]], [3100,2860,2860])
p('结构扩展使前5页完整覆盖率从66.67%升至70.00%，即多覆盖1道题；前10页完整覆盖率从83.33%升至86.67%。样本只有30题，差异有限。部分图文题的前3页覆盖还会下降，因此不能宣称该路径对所有题型都有效。')
p('符号问题最初受到 Unicode 与 LaTeX 分词不一致影响。统一希腊字母及上下标后，包含 ω₂、β₂、η₂ 的题目能在前10页内命中目标，但仍未进入前5页，说明符号对齐只能解决部分召回问题，后续仍需语义重排。')
p('表格类问题共8道，当前 AllPages@5 为37.50%，明显低于单页图像类题目。可能原因包括续表跨页、表头与正文分离，以及问题所需数值被通用词汇覆盖。后续优先检验表格行级索引和相邻页补查，实施后需重新测试，不能把这些计划写成已完成能力。')
p('模型自我核验也可能错误接受不充分证据，或者因为过于保守导致拒答。应分别统计错误接受率、拒答率与被拒题目的可回答性，并用隐藏题验证；不能只观察最终回答中带有多少引用。')

h('3.5 正式评测与性能分析方法',True)
p('正式部署后先验证指定硬件、模型名称、向量维度和服务版本。按照官方脚本在相同输入上运行完整基线与本方案，分别保留构建时长、逐题端到端回答时间、原始回答和判断结果。模型启动、索引复用与缓存状态需说明，确保比较边界一致。')
p('评测以官方统一判断模型给出的 Accuracy 为准。按照附件中的公式，精度得分为100×Accuracy；检索项系数α=1，构建项系数β=5，各项按相对基线耗时差计算。实现不擅自更改基线、计时范围或统计规则，最终规则和边界阈值以组委会公布口径为准。')
c('总分 = 100×Accuracy − α×min((Tq−Bq)/Bq, 1)')
c('                         − β×min((Tb−Bb)/Bb, 1)')
p('其中 Tq、Tb 为本方案检索与构建时长，Bq、Bb 为相同口径下的基线时长。本次缺少真实问答 Accuracy 与完整基线计时，因此不计算总分。赛题提出大于90%的推理精度目标，该目标仍需正式环境验证。')
h('3.6 后续实验顺序')
p('首先连通三项规定服务，完成30题完整问答与官方判分，找出召回失败、图表读错、推理错误和核验误判各自所占比例。随后分别关闭结构扩展、问题规划、视觉输入和多轮补查，测量每条路径的精度收益与时间代价。')
p('再比较复用旧向量与重新构建块向量的方案。若表格仍是主要误差来源，优先实现表头绑定的行级表征；若时间开销主要来自多次大模型调用，再考虑依据检索确定性减少规划或核验调用。最后在未用于开发的隐藏题上检验泛化，确认问答精度、资源使用和提交时限。')

h('3.7 交付内容与引用来源',True)
p('交付目录包含设计文档、evidence_rag 源码、配置、依赖清单、README、测试、实际测量文件、本地结构索引和原创性声明模板。所有原始附件保持不变。数据集、模型权重和第三方运行时不重复打包，在正式环境中使用官方提供数据或按说明安装。')
p('提交前需填写封面中的队伍名称、邮箱和实际提交日期，并由队伍成员核实和签署原创性声明。华为云账号用于正式压缩包命名。打包脚本会运行功能测试、记录文件校验值、检查压缩包完整性与小于500MB的大小限制；签名、正式模型成绩和参赛信息仍需人工确认。')
p('新增代码由本次人机协作编写，使用了既有 BM25、倒数排名融合、多模态证据阅读等方法，不声称原创这些基础技术。官方语料、既有图表描述、模板和验证题均注明来源。第三方依赖和辅助工具说明见 THIRD_PARTY_NOTICES.md。')
h('参考资料')
c('［1］主办方  Agentic AI 多模态表征与检索赛题文档  本地附件。')
c('［2］主办方  RAG-Anything-0713 测试流程和公开30题验证集  本地附件。')
c('［3］HKUDS  RAG-Anything v1.2.9。')
c('https://github.com/HKUDS/RAG-Anything/tree/v1.2.9')
c('［4］HKUDS  LightRAG v1.4.9.11。')
c('https://github.com/HKUDS/LightRAG/tree/v1.4.9.11')
c('［5］NanoVectorDB 官方代码及接口。')
c('https://github.com/gusye1234/nano-vectordb')
c('［6］vLLM 官方兼容服务接口文档。')
c('https://docs.vllm.ai/en/v0.7.0/serving/openai_compatible_server.html')
p('软件接口资料核对日期为2026年9月27日。具体模型服务端版本、比赛细则与评分仍以正式评测环境和主办方最新公布为准。')

body.append(final_section)
parts['word/document.xml']=E.tostring(document,encoding='UTF-8',xml_declaration=True,standalone=True)
settings=E.fromstring(parts['word/settings.xml'])
for x in settings.findall('w:updateFields',NS):settings.remove(x)
add(settings,'updateFields',{'val':'true'})
parts['word/settings.xml']=E.tostring(settings,encoding='UTF-8',xml_declaration=True,standalone=True)
# The template's total-page count is literal text, not a field. Replace only that
# literal with NUMPAGES and an accurate cached value after verified pagination.
footer=E.fromstring(parts['word/footer2.xml'])
for text_node in footer.findall('.//w:t',NS):
    if text_node.text==' 7':
        run=text_node.getparent(); parent=run.getparent();position=parent.index(run)
        text_node.text=' '
        field=el('fldSimple',{'instr':' NUMPAGES '})
        cache_run=deepcopy(run);cache_run.find('w:t',NS).text='14';field.append(cache_run)
        parent.insert(position+1,field)
parts['word/footer2.xml']=E.tostring(footer,encoding='UTF-8',xml_declaration=True,standalone=True)
target=OUT/'设计文档.docx'
with ZipFile(target,'w',ZIP_DEFLATED) as z:
    for name,data in parts.items():z.writestr(name,data)
# Keep the official declaration byte-identical and unsigned.
(OUT/'作品原创性声明_待签署.docx').write_bytes((ROOT/'作品原创性声明.docx').read_bytes())
inventory=json.loads((ROOT/'工作记录/template-parts.json').read_text('utf-8'))
for record in inventory:
    if record['classification']=='preserve':assert hashlib.sha256(parts[record['path']]).hexdigest()==record['sha256']
assert len(document.findall('.//w:sectPr',NS))==2
text='\n'.join(document.xpath('//w:t/text()',namespaces=NS))
assert '（建议包括' not in text
(ROOT/'工作记录/design_text.txt').write_text(text,'utf-8')
print(json.dumps({'path':str(target),'bytes':target.stat().st_size,'body_paragraphs':len(body.findall('w:p',NS)),'tables':len(body.findall('w:tbl',NS)),'preserved_parts':True},ensure_ascii=False))
