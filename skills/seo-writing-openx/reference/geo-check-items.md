# SEO / GEO 必备要素检查项

`scripts/check_geo.py` 的检查项定义。**这份文档与脚本一一对应**——每一条都写明脚本实际怎么判、阈值是多少、不通过怎么办。改判定规则要同时改这两处，否则文档就成了摆设。

范围：A 元数据 / D GEO 要素 / E 结构化数据 / J 站点级。
不在范围内：B 标题结构、C 关键词防蚕食（走 M2/M3 的既有闸）、F 内链（走 M4）、G 视觉与 docx、H 交付卫生、I frontmatter 回写（走 M9）。

## 判定类型

| 类型 | 含义 | 影响退出码 |
|---|---|---|
| `PASS` | 机检通过 | — |
| `FAIL` | 机检不通过，**必须修** | ✅ exit 1 |
| `WARN` | 机检出可疑信号，自己判断要不要改 | ❌ 不阻塞 |
| `MANUAL` | 机器判不了，**要求书面结论** | ✅ 缺答案 exit 1 |
| `SKIP` | 本阶段不适用（如 docx 专属项） | ❌ |

**人工项不是提醒，是闸。** 答案写在 `06-工作区/GEO自检/<article_id>.md`，每项一行 `- D3: <结论>`，
少于 8 个字符视为未回答（填「ok」会被拒）。人工项能被跳过，这道闸就退回散文红线了——
那正是上一版 skill 验证过会失效的形态。

## 工作流

```bash
python3 ~/.claude/skills/seo-writing-openx/scripts/check_geo.py "<文章.md>" --init   # 首次：生成人工项模板
python3 ~/.claude/skills/seo-writing-openx/scripts/check_geo.py "<文章.md>"          # 填完后：正式判定
python3 ~/.claude/skills/seo-writing-openx/scripts/check_geo.py --site               # J 区：按站点跑一次
```

挂在 **M6 通过条件**（元数据写完后、M7 格式整理之前）。退出码 0 才算过 M6。

可选参数：`--vault <path>` 指定 Vault 根；`--no-manual` 只跑机检（人工项降级为提示，**交付前不要用**）。

---

## A · 元数据 / 上稿信息

脚本从文末 `## 上稿用 SEO 資訊` 节解析 `**字段名**` + 后续内容行；带「備選」前缀的行不参与判定。

| # | 检查什么 | 判定标准 | 类型 |
|---|---|---|---|
| A1 | Meta Title | 字段存在；含 `primary_keyword`；宽度 ≤ **30 全形字**（CJK/全角=1，ASCII=0.5，脚本打印算式） | FAIL |
| A2 | Meta Description | 字段存在；含主词；≤ **155 字元**；不含卖关子词（本文將/一起來看/揭秘/往下看…） | FAIL |
| A3 | 文章摘要 | 字段存在；**90–140 字**；独立于 Meta Description | FAIL |
| A4 | Slug | 匹配 `^[a-z0-9]+(-[a-z0-9]+)*$`；不含 `19xx/20xx` 年份 | FAIL |
| A5 | 主题簇 `cluster` | frontmatter 有值；`02-主题簇/<cluster>.md` **文件真实存在** | FAIL |
| A6 | 站点栏目分类 | 取 frontmatter `category` 或上稿节「分類」；须是 6 类之一：`最新消息 / 新手入門 / 策略分析 / 風險管理 / 市場回顧 / 工具教學` | FAIL |
| A7 | 标签 | **6–10 个**（按 `、` `,` `，` 切分） | FAIL |
| A8 | 元数据位置 | 上稿节存在；`**Meta Title**` 等标签**没有泄漏进正文** | FAIL |
| A9 | 前置区块顺序 | docx 导出阶段的事，md 不检查 | SKIP |
| A10 | 主词覆盖 | 主词**同时**出现在 Meta Title 与 Meta Description | FAIL |

A5 与 A6 是**两套并行体系**：簇管内容与内链归属，栏目管站点导航。一篇文章两者都要有，不能互相顶替。

## D · GEO 要素（被 AI 引用的条件）

| # | 检查什么 | 判定标准 | 类型 |
|---|---|---|---|
| D1 | Answer Block | H1 之后第一个块是 `>` 引用块 → 否则 FAIL；内容超过 1 段或不含主词 → WARN（容忍 `**快速解答｜…**` caption 行） | FAIL / WARN |
| D2 | Answer Block 内链禁区 | 块内不得有 `[[wikilink]]` 或 `[]()` | FAIL |
| D3 | 每个 H2 首段即给结论 | 机器判不了。脚本列出**各内容节的首句**供判断（自动排除 FAQ 与「内链清单」「发布前自检」等交付前会删的节） | MANUAL |
| D4 | FAQ | 有 FAQ 节（H2 含「常見問題」或 FAQ）；有 `**Q…**` 格式问题；每题都有答案段 → 否则 FAIL。答案以「上述/這個/因此/它…」开头 → WARN（摘出来会读不懂） | FAIL / WARN。**内容口径（2026-09-18）：FAQ 从正文提取常见问题并总结，每题对应正文已答过的段落，不引入新主张；语义判定由 `seo-geo-check` 的 D4 评审负责** |
| D5 | 可查证数字与日期 | 去重后 **≥10 处**。识别年月日、千分位、百分比、金额、`N 秒/倍/次/筆`、版本号 | FAIL |
| D6 | 信息增益 3 条 | `06-工作区/增益/<article_id>/gain.md` 存在，且 `gate.py gain` 退出码 0（**委托判定，不重写逻辑**） | FAIL |
| D7 | 增益条目落地 | 按 **6 字滑动窗口**比对正文，命中则打印证据。部分未命中 → MANUAL（换个说法写属正常，字面比对不该硬阻塞） | PASS / MANUAL |
| D8 | 一手源 | 无二手转述措辞（據研究表明/業內普遍認為/據悉/相關數據顯示…）；正文至少 1 个外链域名 | FAIL |
| D9 | 承认边界 | 检出「我沒找到/查不到/對不上/口徑不一致/以官方為準…」→ PASS；未检出 → MANUAL（请说明本文是否真的没有不确定处） | PASS / MANUAL |
| D10 | 专有名词定义 | 首次出现的专有名词是否都给了一句定义 | MANUAL |
| D11 | 段落自包含 | 以依赖上文的词开头的段落占比 **>20%** → WARN（AI 摘录以段为单位） | WARN |
| D12 | 结构化呈现 | 表格行 ≥3 **或** 编号步骤 ≥3 → PASS；都没有 → WARN | PASS / WARN |

## E · 结构化数据

md 阶段还没有 JSON-LD，所以 E1/E2 查的是上稿节的**声明**，E3/E4 必须等上稿后人工确认。脚本不假装能校验还不存在的 schema。

| # | 检查什么 | 判定标准 | 类型 |
|---|---|---|---|
| E1 | Schema 三件套 | 上稿节 Schema 字段同时含 `Article`、`FAQPage`、`BreadcrumbList` | FAIL |
| E2 | FAQPage 与正文一致 | Schema 行声明的题数（支持「六題」中文数字）== 正文实际 `**Q…**` 数；未声明题数 → WARN | FAIL / WARN |
| E3 | Article 必填字段 | 上稿后确认 headline / datePublished / dateModified / author / image 齐 | MANUAL |
| E4 | Rich Results Test | 上稿后过一次，无 error | MANUAL |

## J · 站点级（`--site`）

跨文章与线上项，**按站点确认一次，不必每篇跑**。J 区的 MANUAL 项只打印清单，不影响退出码（退出码只看 FAIL）。

| # | 检查什么 | 判定标准 | 类型 |
|---|---|---|---|
| J4 | Meta Title 全站唯一 | 扫 `03-文章/` 全部 md，Meta Title（缺则用 frontmatter title）无重复 | FAIL |
| J2 | 语言矩阵 | 每个 `article_id` 是否出齐 7 语言（hreflang 只能覆盖已存在的版本） | WARN |
| J5 | URL 结构 | 已回填 `url` 的：不含大写、不含查询参数；无已回填 url → SKIP | FAIL |
| J1 | canonical | 每页自指，多语言各指自己 | MANUAL |
| J3 | 列表页可爬分页 | **已确诊的收录瓶颈根因，优先级最高** | MANUAL |
| J6 | 首屏无侵入式弹窗 | 影响 CWV 与移动可用性 | MANUAL |
| J7 | 图片 | 压缩 + WebP + 显式 width/height（防 CLS） | MANUAL |
| J8 | dateModified 可见 | 正文或元信息区显示更新日期 | MANUAL |

---

## 可调常量

全在 `check_geo.py` 顶部。改常量即改判定，不必动逻辑。

| 常量 | 当前值 | 管哪一项 |
|---|---|---|
| `TITLE_MAX_WIDTH` | 30.0 | A1 |
| `DESC_MAX_CHARS` | 155 | A2 |
| `ABSTRACT_RANGE` | (90, 140) | A3 |
| `TAG_RANGE` | (6, 10) | A7 |
| `SITE_CATEGORIES` | 6 类栏目 | A6 |
| `MIN_VERIFIABLE_FACTS` | 10 | D5 |
| `VAGUE_ATTRIBUTION` | 12 条二手转述措辞 | D8 |
| `CLICKBAIT` | 10 条卖关子词 | A2 |
| `DEPENDENT_OPENERS` | 18 条依赖上文的开头词 | D4 / D11 |
| `MANUAL_ITEMS` | D3 / D10 / E3 / E4 | 人工项问法（D7/D9 按条件动态加入） |
| `MIN_ANSWER_CHARS` | 8 | 人工项答案的最短长度 |

## 已知边界

- **答案文件不跟踪文章变更**：文章改了但答案文件没改，脚本认不出来（仍显示已确认）。要根治得加内容哈希或时间戳比对。
- **D7 是字面比对**：6 字滑动窗口只能证明「命中了」，不能证明「没落地」——所以未命中转 MANUAL 而不是 FAIL。
- **E1/E2 只验声明**：真正的 schema 正确性在上稿后，靠 E3/E4 的人工确认与 Rich Results Test。
- **A3 的字数**用中文字计（`han_count`），纯西文标题会退化成字符数计。多语言版本要留意这个差异。
