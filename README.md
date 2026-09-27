# massive-storage

存储竞赛项目、原始数据及工作记录。按本地目录结构保存五个文件夹，不包含压缩包。

| 目录 | 内容 |
|---|---|
| `参赛作品/` | 方案代码、设计文档、原创性声明、配置、测试及本地索引 |
| `工作记录/` | 设计文档生成脚本、排版检查与优化记录 |
| `索引与demo代码-0730/` | 主办方赛题附件、参考代码及预构建索引 |
| `mineru-parsed/` | 文档解析内容、原始页面及裁剪图片 |
| `original_pdf_files_100/` | 原始PDF文档 |

## 获取完整文件

数据集、原始PDF、图片及官方大型索引使用 Git LFS。请先安装 Git LFS，再运行：

```bash
git lfs install
git clone https://github.com/shaman-Zieg/massive-storage.git
cd massive-storage
git lfs pull
```

若下载后的文件仅包含 `version https://git-lfs.github.com/spec/v1` 等几行内容，说明取得的是LFS指针，仍需拉取实际数据。

运行方法见 `参赛作品/README.md`。模型权重不在仓库内，需要连接赛题规定模型服务。已有离线检索指标不等于正式问答准确率。数据、模板和参考代码沿用各自原有来源及使用要求，详见 `参赛作品/THIRD_PARTY_NOTICES.md`。
