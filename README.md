# LibreTranslate

[Try it online!](https://libretranslate.com) | [API Docs](https://docs.libretranslate.com) | [Community Forum](https://community.libretranslate.com/) | [Bluesky](https://bsky.app/profile/libretranslate.com)

[![Python versions](https://img.shields.io/pypi/pyversions/libretranslate)](https://pypi.org/project/libretranslate) [![Run tests](https://github.com/LibreTranslate/LibreTranslate/workflows/Run%20tests/badge.svg)](https://github.com/LibreTranslate/LibreTranslate/actions?query=workflow%3A%22Run+tests%22) [![Build and Publish Docker Image](https://github.com/LibreTranslate/LibreTranslate/actions/workflows/publish-docker.yml/badge.svg)](https://github.com/LibreTranslate/LibreTranslate/actions/workflows/publish-docker.yml) [![Publish package](https://github.com/LibreTranslate/LibreTranslate/actions/workflows/publish-package.yml/badge.svg)](https://github.com/LibreTranslate/LibreTranslate/actions/workflows/publish-package.yml) [![Awesome Humane Tech](https://raw.githubusercontent.com/humanetech-community/awesome-humane-tech/main/humane-tech-badge.svg?sanitize=true)](https://codeberg.org/teaserbot-labs/delightful-humane-design)

Free and Open Source Machine Translation API, entirely self-hosted. Unlike other APIs, it doesn't rely on proprietary software such as Google or Azure to perform translations. Instead, its translation engine is powered by the open source [Argos Translate](https://github.com/argosopentech/argos-translate) library.

![Translation](https://github.com/user-attachments/assets/457696b5-dbff-40ab-a18e-7bfb152c5121)

## Getting Started

- [Quickstart](https://docs.libretranslate.com/)
- [Usage Instructions](https://docs.libretranslate.com/guides/api_usage/)
- [Community Resources](https://docs.libretranslate.com/community/resources/)

## 校园中俄翻译增强（Campus ZH⇄RU fork）

本仓库是 LibreTranslate 的一个分叉，额外提供面向中外合作办学场景（首发：深圳北理莫斯科大学）
的中俄双语增强能力：**术语库优先翻译、校园噪音保护（课程编号/教室/邮箱/日期等）、
俄语姓名音译、中俄一键对照排版**。完整说明见 [docs/campus-zh-ru.md](docs/campus-zh-ru.md)，
改动清单见 [docs/CHANGES-campus.md](docs/CHANGES-campus.md)。

不需要语言模型即可验证（71 项单元测试 + 离线对照排版演示）：

```bash
python scripts/campus/run_tests.py                                 # 单元测试
python scripts/campus/validate_glossary.py                         # 术语库质检
python scripts/campus/demo.py                                      # 生成 demo_output/notice_zh_ru.md
python scripts/campus/translate_docs.py -i notice.md -o out/pair.md --layout paragraph
```

带模型的完整服务：

```bash
pip install -e .
python main.py --update-models
python main.py --glossary-dir data/glossary --glossary campus_zh_ru --campus
```

```bash
curl -s http://localhost:5000/translate -H 'Content-Type: application/json' -d '{
  "q": "本课程讲授数据结构与操作系统，教室 3-412。",
  "source": "zh", "target": "ru", "campus": true
}'
```

本分叉整体仍以 AGPL-3.0 发布；若作为网络服务提供给他人使用，请按 AGPL 第 13 条
向使用者提供完整源代码（见文档第 7 节）。

## Credits

This work is largely possible thanks to [Argos Translate](https://github.com/argosopentech/argos-translate), which powers the translation engine.

## License

[GNU Affero General Public License v3](https://www.gnu.org/licenses/agpl-3.0.en.html)

## Trademark

See [Trademark Guidelines](https://github.com/LibreTranslate/LibreTranslate/blob/main/TRADEMARK.md)

