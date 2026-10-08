# 校园中俄翻译增强（Campus ZH⇄RU）使用与设计说明

> 面向中外合作办学场景（首发：深圳北理莫斯科大学）的 LibreTranslate 增强层：
> **术语库优先、校园噪音保护、姓名音译、中俄对照排版**。
> 上游项目：https://github.com/LibreTranslate/LibreTranslate （AGPL-3.0）

---

## 1. 为什么需要这一层

LibreTranslate 本身是一个**通用**机器翻译服务：给定源语言和目标语言，它把整句交给
Argos（CTranslate2 + SentencePiece）模型。它在"日常句子"上够用，但落到中俄合作办学的
真实材料上会稳定地踩三类坑：

| 现象 | 例子 | 后果 |
| --- | --- | --- |
| 术语被自由发挥 | "数据结构" → «структура информации» | 与俄方课程大纲（РПД）用词不一致，学生看不懂、教务对不上 |
| 该原样保留的被翻译/吞掉 | 课程号 `МА101`、教室 `3-412`、学号、邮箱、公式编号 | 通知里的关键信息在俄文版里消失 |
| 校园特有表达处理不了 | "深北莫"、`МГУ-ППИ`、教师姓名 `Иванов И.И.` | 缩写要么被逐字翻译，要么音译错 |

同时，双语材料（通知、邮件、课件）在**排版层**还有额外诉求：
中文一段、俄文一段，逐句对齐，便于双方对照阅读。

这一层就是为这四件事写的，且刻意做成**不依赖语言模型**：
术语库、编号保护、姓名音译、句对齐、模板排版都是纯逻辑，用标准库即可运行与测试。
只有真正"把句子翻过去"这一步才需要引擎。

---

## 2. 目录与模块

```
libretranslate/campus/
├── placeholders.py   占位符机制：遮蔽、由严到宽的回填、丢失/重复上报
├── glossary.py       术语库：加载、最长优先匹配、遮蔽、自检、统计
├── noise.py          噪音：编号/链接/日期保护、输入规范化、缩写表、姓名音译
├── templates.py      句切分、句对齐、通知/邮件/课件模板、中俄对照渲染
└── pipeline.py       两阶段流水线（prepare / finish），引擎可注入

data/glossary/
├── campus_zh_ru.json 术语库 119 条（cs/math/physics/econ/campus/admin）
└── campus_noise.json 校本缩写 15 条 + 俄语人名表 129 条

scripts/campus/
├── run_tests.py       跑 71 项单元测试（无需模型）
├── demo.py            离线演示：生成中俄对照通知（md + docx + 审计 JSON）
├── validate_glossary.py  术语库质检，输出 JSON 报告
├── translate_docs.py  txt/md/docx 批量翻译与一键对照排版
└── smoke_api.py       HTTP 层冒烟测试（需装好完整依赖与模型）
```

---

## 3. 五分钟上手（不需要模型）

```bash
git clone https://github.com/<your-name>/LibreTranslate.git
cd LibreTranslate

python scripts/campus/run_tests.py        # 71 项测试，全部离线
python scripts/campus/validate_glossary.py
python scripts/campus/demo.py             # 生成 demo_output/notice_zh_ru.md / .docx

python scripts/campus/translate_docs.py \
    -i 通知.md -o out/通知_中俄对照.md --layout paragraph
```

`demo.py` 输出的审计信息长这样（真实运行结果，节选）：

```
原文  ：数据结构（课程号 МА101）与操作系统（课程号 МА102）为先修课程，教室为 3-412。
遮蔽后：[[T1]](课程号 [[T3]])与 [[T2]](课程号 [[T4]])为先修课程, 教室为 [[T5]].
译文  ：структуры данных (код курса МА101) и операционная система (код курса МА102)
        являются предшествующими дисциплинами, аудитория 3-412.
术语命中合计：11，保护片段合计：7，占位符回填率：100%
```

---

## 4. 服务端用法（需要模型）

```bash
pip install -e .
python main.py --update-models          # 首次下载模型
python main.py --glossary-dir data/glossary --glossary campus_zh_ru --campus
```

新增命令行参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--glossary-dir` | `data/glossary` | 术语库目录（环境变量 `LT_GLOSSARY_DIR`） |
| `--glossary` | `campus_zh_ru` | 默认术语库 profile（环境变量 `LT_GLOSSARY`） |
| `--campus` | 关闭 | 中俄方向的请求默认套用术语库 + 编号保护（环境变量 `LT_CAMPUS`） |

### 4.1 `/translate` 新增参数

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `campus` | `true/false` | 一键开启术语库 + 编号保护 |
| `glossary` | `true` / profile 名 / 内联 JSON | 使用默认术语库、指定 profile，或本次请求专用的术语表 |
| `protect` | `true/false` | 只控制编号/链接/日期保护 |
| `glossary_strict` | `true/false` | `true`=占位符保护后交给模型；`false`=术语直出替换 |
| `name_suggestions` | `true/false` | 顺带返回俄语姓名的音译建议 |

```bash
curl -s http://localhost:5000/translate -H 'Content-Type: application/json' -d '{
  "q": "本课程讲授数据结构与操作系统，教室 3-412。",
  "source": "zh", "target": "ru", "campus": true
}' | python -m json.tool
```

响应里除上游字段外多出一个 `campus` 审计块（批量请求时是数组）：

```json
{
  "translatedText": "Этот курс охватывает структуры данных и операционная система, аудитория 3-412.",
  "campus": {
    "maskedText": "本课程讲授 [[T1]] 与 [[T2]]，教室 [[T3]]。",
    "glossaryMatches": [
      {"origin": "数据结构", "target": "структуры данных", "domain": "cs", "zh": "数据结构", "ru": "структуры данных"},
      {"origin": "操作系统", "target": "операционная система", "domain": "cs", "zh": "操作系统", "ru": "операционная система"}
    ],
    "protected": [{"rule": "room", "text": "3-412"}],
    "glossaryCoverage": 0.42,
    "placeholderRestoreRate": 1.0,
    "warnings": []
  }
}
```

`placeholderRestoreRate` 是这条链路的**质量阀门**：它等于"成功回填的占位符 / 全部占位符"。
小于 1 说明底层模型吞掉了术语或编号，`warnings` 会列出具体片段，并在译文后附上
"术语对照（机翻未保留，供人工确认）"，避免信息静默丢失。

### 4.2 新增只读接口

| 接口 | 说明 |
| --- | --- |
| `GET /campus/status` | 术语库规模与领域分布、启用的保护规则、缩写/人名表规模 |
| `GET /campus/glossary?source=zh&target=ru` | 导出全部术语，附 `direct` 直出对照表 |

### 4.3 内联术语表（不改服务端配置）

```bash
curl -s http://localhost:5000/translate -H 'Content-Type: application/json' -d '{
  "q": "编译原理", "source": "zh", "target": "ru",
  "glossary": "[{\"zh\":\"编译原理\",\"ru\":\"теория компиляции\"}]"
}'
```

适合任课老师临时加一个班级内部用词，而**不需要**管理员改仓库文件。

---

## 5. 术语库怎么建、怎么维护

这部分是我们认为最值得长期投入的地方，流程写死成工具，避免"术语库建了没人用"。

**① 采集**——三个来源，按可信度排序：

1. **俄方官方文件**：合作高校的 РПД（工作大纲）、《Положение》（条例）、课程表；
2. **权威词条**：ru.wikipedia 词条标题、俄罗斯高校课程页；
3. **校内共识**：教务处/俄语教研室已有的双语表格，由俄语教师签字确认。

**② 标注**——每条术语五个字段，可直接被 `translate_docs.py` 使用：

```json
{
  "zh": "数据结构",
  "ru": "структуры данных",
  "en": "data structures",
  "domain": "cs",
  "note": "已核对：ru.wikipedia.org «Структуры данных»",
  "source": "中俄校园术语调研 2026-10-08"
}
```

`note` 里写"为什么这么译、有争议的另一种译法是什么"，这是术语库最容易被忽略、
却最影响可信度的部分。例如：

* 编译原理 → «теория компиляции»（МГУ ВМК 课程名；另有 «теория трансляции»）
* 微积分 → «математический анализ»（不用 «исчисление»，后者偏"演算"）
* 选修课 → «дисциплина по выбору»（«факультатив» 指不计学分的选修，不是一回事）
* 考试/考查 → «экзамен»（记分）/ «зачёт»（通过制）
* 学籍 → «контингент обучающихся»（俄语无单词对等词，直译 «статус студента» 会走偏）

**③ 质检**——`validate_glossary.py` 会查：空字段、领域取值非法、俄语侧混入汉字、
中文侧混入西里尔、俄语侧混入拉丁却无说明、同一中文两种译法且都没写 note（歧义）。
存在 error 级问题时退出码为 1，可直接挂到 CI。

**④ 增补**——`Glossary.unknown_candidates(text)` 会把文本里"看着像术语但库里没有"的
汉字片段挑出来（长词优先），作为下一轮入库候选。演示：

```python
from libretranslate.campus import Glossary
g = Glossary.from_json_dir("data/glossary", profile="campus_zh_ru")
print(g.unknown_candidates("本课程讲授编译原理与计算机组成原理"))
```

**⑤ 回馈上游**——通用词条（如"数据结构""操作系统"）与其说属于我们，不如说属于所有
用户。建议按上游 `AGENTS.md` 的约定**手工**提交 PR（上游明确拒绝自动提交的 PR），
并在 PR 描述里说明 AI 参与程度。

配套的入库存量：`data/glossary/campus_zh_ru.json` 目前 119 条（cs 23 / math 16 /
physics 10 / econ 11 / admin 47 / campus 12），118 条带核实说明。

---

## 6. 占用符（占位符）机制与降级策略

1. **遮蔽**：术语命中先换成 `[[T1]]`，编号/邮箱/日期等换成后续序号，两者**共用同一张占位符表**，
   因此序号不会冲突；
2. **翻译**：模型只会看到"中文 + `[[T1]]`"这种文本；
3. **回填**：由严到宽三轮匹配——先精确 `[[T1]]`，再容忍 `[T1]`、`(T1)`、`{{T1}}`、
   大小写与空格噪声，最后（可选）容忍裸写的 `T1`；
4. **降级**：
   * 占位符丢失 → `warnings` 记录 + 译文末尾附术语对照；
   * 占位符重复出现 → 按术语表回填并告警；
   * 引擎抛异常 → 包装成 `警告：翻译引擎报错：…`，返回遮蔽文本而不是 500；
   * 内容无需翻译（纯数字/空白）→ 原样返回。

> 经验值：占位符存活率与引擎强相关。上线前建议用 `smoke_api.py` 在自己的模型上
> 跑一遍，读 `placeholderRestoreRate`；低于 0.95 时把 `glossary_strict` 设为 `false`
> （术语直出替换），牺牲一点流畅度换取术语准确。

---

## 7. 合规：AGPL-3.0 怎么处理

* 本仓库是 LibreTranslate 的**分叉**，整体仍以 **AGPL-3.0** 发布，`LICENSE` 未改动；
  新增文件同样受 AGPL-3.0 约束；
* AGPL 第 13 条要求：**若把修改后的程序作为网络服务提供给他人使用，必须向使用者提供
  对应的完整源代码**。因此校园版部署时：
  1. 在服务页面/登录页放一个"源代码"链接（指向本 fork）；
  2. 保留版权声明与许可文本，明确标注"基于 LibreTranslate 修改"；
  3. 把我们对上游的通用改进（如 `libretranslate/__init__.py` 的延迟导入、
     术语库自检、占位符保护）**回馈上游 PR**，让分叉的必要性随时间递减；
* 商标：按上游 `TRADEMARK.md`，不在服务名称/域名中使用 "LibreTranslate" 商标，
  校内实例命名为"校园中俄翻译服务（校内非商业使用）"；
* 数据边界：翻译在内网/校内服务器完成，**不调用外部商业翻译接口**，学生姓名、
  学号、成绩等个人数据不出校，符合《个人信息保护法》对数据本地化的要求。

---

## 8. 已知限制

* **zh⇄ru 直连模型**：Argos 官方模型以英语为枢纽，中俄方向通常需要
  `zh→en→ru` 两跳，质量和延迟都受影响。`translate_docs.py --engine argos`
  已内置 pivot 逻辑；后续可用校内语料微调 zh→ru 直连模型（见路线图）。
* **占位符不是万无一失**：见第 6 节的降级策略。
* **姓名音译**：词表命中（约 130 个常见俄语姓名）置信度高；未命中走音节表兜底，
  会在结果里标 `review=true`，提示人工复核，不假装准确。
* **句对齐**：以"N:N 逐句"为主，遇到合句/拆句会按长度比例分配并给出 `warnings`。
* **测试边界**：71 项单元测试与离线演示都不需要模型；**HTTP 层**的端到端验证需要
  完整依赖与模型，请在本机执行 `scripts/campus/smoke_api.py`。

---

## 9. 路线图

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| M1（已完成） | 术语库 + 编号保护 + 姓名音译 + 对照排版 + 71 项测试 | `run_tests.py` 全绿，`demo.py` 产出对照稿 |
| M2 | 浏览器插件（选词即译 + 术语气泡）、服务端部署到校内服务器 | 教务处/俄语教研室试用反馈 |
| M3 | 用校内双语语料微调 zh→ru 直连模型；术语命中率/回填率看板 | 课程术语一致率 ≥ 95% |
| M4 | 推广到中俄合作办学同类机构（见策划书"可推广性"章节） | 2 所以上院校试用 |
