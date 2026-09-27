# 模板执行契约

Reference: D:\青\存储大赛\挑战赛道作品设计文档模板.docx
SHA256: e4b0575a9bc948f1cbdbf47b3a707c9a85789dd185e23dc0d9eda554efc8dfa4
实际渲染 5 页；原始 NUMPAGES 缓存为 7，交付时须更新。共 2 个节。
模板原件保持不变。参考图片在 template-render/page-1.png 至 page-5.png，已逐页查看。
技能 render_docx.py 因缺少 LibreOffice 失败；使用只读 Microsoft Word COM 导出和内置 Poppler 实际渲染。

## 页面体系
两节均为 11906 × 16838 twips 纵向 A4。上下边距1440，左1620，右1466。
页眉851，页脚992 twips，单栏，docGrid linePitch312。保持节XML、页脚关系不变。
第一节为封面，在原 paragraph[15] 的 sectPr 结束。第二节含填写说明与正文。
保留封面段落0至15的位置及居中26pt黑体标题。填写说明16至20按原文保留。
空白占位段落21至47及各章后空白是扩展内容槽，可去除并使用显式分页。

## 排版和内容槽
word/document.xml 中 body/p[4] 与 p[5] 是封面主标题（1基XPath），仅补充Title语义样式，不改变26pt黑体加粗居中外观。
body/p[13]至p[16] 是赛题、队伍、邮箱、日期；保留16pt黑体标签及下划线填写区域，替换空白文本，信息缺失填待填写。
body/p[17]至p[21] 是说明页，保持原文与12pt宋体1.5倍行距。
原 paragraph[48]/[90]/[129] 为三章主标题，使用原Heading1 styleId=1、16pt黑体居中。
原 paragraph[49]/[91]/[130] 是提示语槽，删除提示并替换为实际内容。
正文按模板明示要求统一宋体12pt（小四）、1.5倍行距、黑色，首行2字。
二级标题复用Heading2 styleId=2并直接明确14pt黑体加粗黑色、段前8pt段后4pt。
长章可增加分页与二级标题，保留三章顺序。页内主体不放文本框、装饰横线或阴影卡片。
模板无表格和图片、无TOC、无内容控件。新增表格仅用于字段映射、模块、参数、指标对比。
新增表格宽8820 twips，宋体12pt，1.5倍行距；灰色细边，浅灰表头，单元格可自动增长；表头重复且禁止行拆分。

## 包保真
完整part清单及sha256见template-parts.json，节和样式XML见template-evidence.json。
仅document.xml内容、settings.xml字段更新标记、styles.xml新增Title和页脚NUMPAGES缓存可编辑。
全部其他part及关系保持字节不变。保留原有styles中的所有已定义样式。
所有页脚PAGE/NUMPAGES字段保留，设置updateFields；Word导出前Repaginate和更新页脚字段。
封面及说明页与参考图比对；正文检查宋体小四、行距、表格不溢出、每页可读。最终对所有页PNG逐页审查。
复核修正：模板页脚共7页为静态文本。交付将该静态数字替换为 NUMPAGES 域并缓存已验证的14页；原 PAGE 域保持。Word COM 枚举不存在的页眉页脚会引入临时横线，最终仅作只读直接导出，不枚举字段故事。
