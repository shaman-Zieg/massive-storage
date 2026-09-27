# Agentic AI 多模态表征与检索

本作品实现基于页码证据的多路检索和 Agent 迭代问答。新增代码位于 `evidence_rag/`，保留赛题指定的 Qwen3-VL-8B-Instruct、bge-m3、bge-reranker-v2-m3 和 NanoVectorDB。方案名称为 EvidenceRAG。

**V2 优化版：74项测试通过，公开30题的实际文本证据全部参考页覆盖从24/30升至28/30（80%→93.33%）。** 这是首轮实际打包文本中的页面覆盖，**不是问答准确率，也不代表达到 >90% 推理目标**。本机未连接三项规定模型服务，正式模型成绩仍未验证。旧版源码、同条件比较和退化项均随包保留，见 `优化说明.md` 和 `artifacts/optimization_comparison.json`。

新版增加页面与表格行候选、轮转图扩展、页面预算分配、相关行取证与定向查页；多查询每轮一次批量嵌入、一次统一重排。同证据修订与JSON重试均有全题上限，算术错误不能通过宽松核验放行。邻页补充和在线页面融合权重属于待正式环境验证的启发式，提供关闭选项。

## 目录与依赖

解压后建议保持以下目录关系；也可在 `config.json` 中修改路径，所有相对路径都相对于该配置文件：

```text
工作目录/
  mineru-parsed/                 官方解析数据
  original_pdf_files_100/        官方 PDF，支持 *_origin.pdf 文件名
  索引与demo代码-0730/
    RAG-Anything-0713/
      RAG_STORAGE_0713_retry/    官方索引与图表描述
      queries_30.json           只允许评测程序读取
  参赛作品/
    evidence_rag/               新增实现
    tests/                      单元及模拟 HTTP 集成测试
    scripts/                    环境、自测和打包脚本
    benchmarks/v1/              冻结旧版源码与来源校验值
    artifacts/                  实际测量记录和已构建本地索引
    config.json
    设计文档.docx
    作品原创性声明_待签署.docx
```

推荐 Python 3.12，兼容 Python 3.10 及以上；安装 `requirements.txt`。完整页面回查需要 Poppler 的 `pdftoppm` 在 PATH 中。Ubuntu 可使用 `apt-get install poppler-utils`；Windows 配置 Poppler 的 bin 目录。索引及离线检索本身只需要标准库；NanoVectorDB 需要 NumPy，图像编码需要 Pillow。

```bash
python -m venv .venv
# Linux: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m evidence_rag build
python -m unittest discover -s tests -v
```

在当前电脑也可直接运行 `powershell -File scripts/local_check.ps1`，脚本使用本次验证的已安装运行时，不安装模型或修改系统设置。迁移到服务器使用常规 Python 命令。

## 离线检查

```bash
python -m evidence_rag search "What variation occurred in the Bureau de Change exchange rate between Q1 2012 and Q4 2013?" --offline
python -m evidence_rag evaluate-retrieval --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json --output artifacts/retrieval_report.json
python -m evidence_rag evaluate-retrieval --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json --output artifacts/retrieval_no_graph.json --no-graph
# 同一评测器重跑V1、V2及四项消融，约几十秒；只做离线诊断
python scripts/compare_versions.py --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json
```

离线模式明确关闭在线向量查询、神经重排和生成，不输出伪造回答或官方分数。图表描述来自主办方已提供的文档索引；这部分预处理成本不包含在本地构建耗时中。

## 接入正式模型环境

1. 按赛题要求部署统一模型，配置 `llm_url`、`embedding_url`、`rerank_url`。模型名称要与 vLLM 的 `served-model-name` 完全一致。官方赛题要求 910B3 NPU 配置；附件中 A800 示例仅供接口理解，最终以组委会环境为准。
2. `embedding_dim` 固定为 1024。正式默认开启所有 `use_*` 选项。
3. 如服务需要鉴权，使用环境变量 `RAG_LLM_API_KEY`、`RAG_EMBEDDING_API_KEY`、`RAG_RERANK_API_KEY`。不把密钥写进配置或压缩包。
4. 执行 `python -m evidence_rag doctor`。退出码 2 表示依赖或服务尚未就绪；`/health` 仅表示本地索引已加载，不表示远端模型已探测成功。
5. 执行 `python -m evidence_rag serve`。默认仅监听 `127.0.0.1:8080`，串行处理请求，适配随附 benchmark；如需远程暴露应自行部署网关与访问控制。

```bash
python -m evidence_rag doctor
python -m evidence_rag serve
# 另开一个终端
python -m evidence_rag ask "What variation occurred in the BDC exchange rate between Q1 2012 and Q4 2013?"
python -m evidence_rag benchmark --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json --output artifacts/e2e
# 只有已有真实完整构建计时后，才传入用于正式计分；JSON须含正数build_time
python -m evidence_rag benchmark --questions ../索引与demo代码-0730/RAG-Anything-0713/queries_30.json --output artifacts/e2e_scored --build-timings artifacts/real_build_timings.json
```

`POST /query` 输入仅为 `{"question":"..."}`，返回 `answer`、`query_time_s`、`status`、`citations`、`trace` 和 `model_calls`。额外传入 `answer`、`gt_image_paths`、`sample_id` 等字段将得到 HTTP 400。模型调用失败返回 HTTP 503；证据不足返回 `status=insufficient_evidence`，不得计为正确答案。

随附官方测试端可直接把 `RAG_BINDING_HOST` 指向 `http://127.0.0.1:8080/query`。本作品 benchmark 输出包含官方判题需要的 `question`、`answer`、`pred` 等字段；标准答案仅保留在独立评测输出中，不发送给回答服务。调用未经修改的官方 judger 得到问答 Accuracy，再用官方评分脚本计算总分。不要以本地检索指标替代该步骤。

官方评分脚本要求 `timings.json` 同时包含 `build_time` 和 `search_time`。benchmark 支持互斥参数 `--build-timings`（读取含 `build_time` 的实测JSON）或 `--build-time-s`（真实完整构建秒数）；拒绝零、负数及非有限值。不传仍可收集问答和逐题耗时，但 `benchmark_manifest.json` 会标记 `official_scoring_ready=false`。这里的ready只表示计时字段齐全，官方判题和硬件验收仍须完成。构建边界包含初始化、全部入库及所需向量/图谱工作，不能填本地3.54秒的局部结构文件构建；`search_time` 按官方口径统计整个串行查询循环墙钟时间，包含HTTP及结果落盘，不能用服务端耗时求和替代。

## 两种向量索引路径

- 默认复用官方 `vdb_chunks.json`，通过真实 NanoVectorDB 执行查询。旧 chunk 缺少精确页码，因此其结果只用于选择候选文档，再在候选文档中检索带页码的原始块；不会从相似度猜页码。
- `python -m evidence_rag embed` 使用规定的 bge-m3 为本作品块重新嵌入，写入 `artifacts/index/vectors.json`。每批保存，可中断续建；完整构建后原子替换。模型名、维度、语料 SHA-256 不一致时拒绝加载，防止错用旧索引。全量 14,881 块会消耗模型服务资源；正式评分必须把这部分构建时间计入。

结构索引保持表格 HTML、公式原文、图像相对路径和一基页码；图结构是同页邻接、文本到图表引用等**文档结构关系**，当前未重新抽取通用语义知识图谱。所有引用回到确定的页码和块 ID。

## 复现实验口径

`v1_evidence_report.json` 与 `retrieval_report.json` 使用同一新版评测器对冻结V1和V2重跑，语料、60候选、12文本块及24,000字符预算一致。`retrieval_no_graph/no_page/no_neighbors/no_table_rows.json` 为四项消融。这不是与完整官方 RAG-Anything 基线的对比。实际文本页覆盖由生产 Evidence.pack 选块完成后计算，参考页不进入检索或打包；它不能证明页面上所需数值一定进入片段。

`unit_tests.txt` 中的 HTTP 测试使用确定性模拟服务。`model_call_contract.json` 记录三查询只需一次嵌入、一次重排的合成合同，不能证明真实服务加速。`visual_evidence_smoke.json` 用真实文档验证原图可解码及来源正确，不调用模型。可用 `python scripts/visual_smoke.py --question "问题文本"` 重现。

当前结构文件构建约3.54秒，不含MinerU、描述生成、向量和服务启动；V2页面及表格行倒排索引在启动时构建，计入报告的load_seconds。新版离线检索加文本打包均值约5.47毫秒，旧版约2.00毫秒，覆盖收益伴随额外CPU开销；不含图片渲染、网络、模型推理或官方判题。报告分别列出加载、检索、打包及合计时间，不能据此推断正式环境速度。

公开30题已用于开发，不能当独立盲测集。评测固定seed=20260927按文档分成21题开发组和9题回顾检查组，明确后者也已看过。配对差值按文档组重采样2,000次；95%区间只描述这一公开集，不证明隐藏题泛化。AllPages@5有1题退化，全部细节保留。正式环境仍须用未修改官方判题器测真实Accuracy、端到端时延、拒答率和总分。

## 提交

作品包须含设计文档、源码、运行说明、测试记录和签署后的原创性声明。文档中的队伍、邮箱、提交日期待填写；华为云账号用于压缩包命名。原创性声明保留官方文件，尚未签署。

```bash
python scripts/package_submission.py --team "队伍名称" --account "hid_xxx" --output ..
```

打包器默认要求基础功能测试通过且原创性文件存在；仍需提交者检查签名和正式评测结果。输出遵循 `Agentic AI 多模态表征与检索-队伍名称-华为账号.zip`，检查大小小于500,000,000字节。`参赛作品_v2优化版_待补信息.zip` 是工作包，尚需正式命名及签署。原始数据、模型权重和第三方运行时不重复打包，本地结构索引随包提供且可重建。
