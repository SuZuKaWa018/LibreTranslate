# 本次分叉改了什么（Campus ZH⇄RU）

对照上游 `LibreTranslate/LibreTranslate@main`（2026-09-28 快照，`upstream-main.tar.gz`
sha256 `45d92891cd2aa1e026badeb166cc5f35c97e8ac927ac271c4f4d017b579775f2`）。

## 新增文件

| 文件 | 行数级 | 作用 |
| --- | --- | --- |
| `libretranslate/campus/__init__.py` | 小 | 包出口，汇总对外 API |
| `libretranslate/campus/placeholders.py` | 中 | 占位符遮蔽/多轮回填/丢失与重复上报 |
| `libretranslate/campus/glossary.py` | 中 | 术语库：匹配、遮蔽、自检、统计、直出 |
| `libretranslate/campus/noise.py` | 中 | 编号保护、输入规范化、缩写表、姓名音译 |
| `libretranslate/campus/templates.py` | 中 | 句切分、句对齐、通知/邮件/课件模板、对照渲染 |
| `libretranslate/campus/pipeline.py` | 中 | prepare/finish 两阶段流水线，引擎可注入 |
| `data/glossary/campus_zh_ru.json` | 119 条 | 中俄校园术语库 |
| `data/glossary/campus_noise.json` | 15 + 129 条 | 校本缩写表与俄语人名音译表 |
| `libretranslate/tests/campus/*` | 71 项测试 | 纯标准库 unittest，无需语言模型 |
| `scripts/campus/run_tests.py` | 小 | 一键跑测试 |
| `scripts/campus/demo.py` | 中 | 离线演示：生成中俄对照通知 |
| `scripts/campus/validate_glossary.py` | 小 | 术语库质检（可挂 CI） |
| `scripts/campus/translate_docs.py` | 中 | txt/md/docx 批量翻译与对照排版 |
| `scripts/campus/smoke_api.py` | 小 | HTTP 层冒烟测试（需完整依赖） |
| `docs/campus-zh-ru.md` | 中 | 设计、用法、术语库治理、AGPL 合规、路线图 |

## 修改的上游文件

| 文件 | 改动 |
| --- | --- |
| `libretranslate/app.py` | ① 引入 `libretranslate.campus`；② `create_app` 装配校园服务；③ `/translate` 支持 `campus`/`glossary`/`protect`/`glossary_strict`/`name_suggestions`；④ 翻译前后调用 `prepare()`/`finish()`，响应附带 `campus` 审计块；⑤ 新增 `GET /campus/status`、`GET /campus/glossary`；⑥ 开启校园增强时跳过翻译缓存，避免参数差异被缓存掩盖 |
| `libretranslate/main.py` | 新增 `--glossary-dir`、`--glossary`、`--campus` |
| `libretranslate/default_values.py` | 新增 `GLOSSARY_DIR`、`GLOSSARY`、`CAMPUS` 三项环境变量默认值 |
| `libretranslate/__init__.py` | 改为 PEP 562 延迟导入：`import libretranslate` 不再强制拉起 Flask/argostranslate，使 campus 工具链可在无模型环境导入与单测（`from libretranslate import main` 用法不变） |
| `README.md` | 增加"校园中俄翻译增强"段落与快速上手命令 |

## 兼容性

* **默认行为与上游一致**：不传新参数、不加 `--campus` 时，`/translate` 的输入输出与上游相同；
* **缓存**：仅在请求启用校园增强时跳过缓存读写，其余路径不变；
* **依赖**：未新增任何第三方依赖；`python-docx` 仅在 DOCX 输出时按需导入；
* **Python 版本**：沿用上游 `requires-python >= 3.8`，新代码只用标准库。

## 验证记录（本机实测）

| 命令 | 结果 |
| --- | --- |
| `python scripts/campus/run_tests.py` | `Ran 71 tests ... OK` |
| `python scripts/campus/validate_glossary.py` | 119 条，问题：无，结论：通过 |
| `python scripts/campus/demo.py` | 生成 md/docx/审计 JSON，术语命中 11 处，保护片段 7 处，占位符回填率 100% |
| `python -m py_compile libretranslate/app.py main.py default_values.py` | 通过 |
| `python scripts/campus/smoke_api.py` | 需完整依赖与语言模型，本机未执行（见 docs 第 8 节说明） |
