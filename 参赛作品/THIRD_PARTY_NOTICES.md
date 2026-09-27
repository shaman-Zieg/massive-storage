# 引用与来源说明

- 原始 PDF、MinerU 解析结果、公开验证题、预构建向量与图表描述：来自用户提供的竞赛附件。其权利和使用范围按主办方要求执行。本作品不把这些内容声明为自行采集或自行标注。
- 设计文档模板与原创性声明：主办方提供；设计文档按模板填写，声明由队伍核实后签署。
- RAG-Anything v1.2.9 与 LightRAG v1.4.9.11：赛题基线与接口参考。本作品未复制其运行时代码，也未修改其 benchmark 或 judger。仓库：https://github.com/HKUDS/RAG-Anything/tree/v1.2.9 ；https://github.com/HKUDS/LightRAG/tree/v1.4.9.11 。
- NanoVectorDB 0.0.4.3：通过 Python 依赖安装并实际调用。项目：https://github.com/gusye1234/nano-vectordb 。使用其官方接口和存储格式。
- vLLM 模型服务协议参考：https://docs.vllm.ai/en/v0.7.0/serving/openai_compatible_server.html 。具体服务端版本由正式环境固定。
- NumPy、Pillow、Poppler：用于向量数组、图像缩放编码和 PDF 页面渲染；按各上游许可安装使用，不在提交包中复制其二进制。
- BM25、倒数排名融合 RRF、多路检索、基于证据的生成与核验属于已有技术。本作品的新增实现是对确定页码的块组织、结构关联、候选调度、迭代流程、引用与计算核验、测试及部署代码的工程组合，不声称发明上述基础算法。

新增源码与设计文档由本次人机协作编写。参赛团队应理解、复核并按赛事有关辅助工具的要求说明使用情况；原创性声明尚未由任何成员签署。
