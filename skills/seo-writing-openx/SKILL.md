---
name: seo-writing-openx
description: OpenX 站多语言 SEO 文章的端到端产文编排 skill（beta）。串起「选题立项 → 关键词审核 → SERP 与大纲 → 内链设计 → 正文写作 → SEO 元数据 → 格式整理 → 质检 → 回写索引」九个模块，正文委托 human-writing-AYI 写、审核委托 OpenX 文章系统（Obsidian Vault）判，本 skill 只负责编排与交接。触发词：写 OpenX 文章、OpenX SEO 文章、OpenX 产文、给 OpenX 写一篇、/seo-writing-openx。区别于 seo-article-builder（那是 1000X 台湾站的独立一条龙）：本 skill 强制过 OpenX 文章系统的三道闸，做全站关键词防蚕食与内链矩阵管理。
---

# OpenX SEO 产文流水线 0.3.0-beta

这是**编排层**，不是写作层。它自己不定文风、不判关键词，只负责让九个模块按顺序交接、每个交接点的输入输出对得上。

- 正文怎么说话 → `human-writing-AYI` 说了算；本篇用哪套牌 → `pick_profile.py` 按跨篇日志算
- 关键词能不能用、内链插哪 → OpenX 文章系统的 SOP 说了算
- 谁在什么时候交给谁、交什么 → 本 skill 说了算

## 开工第一件事（不许跳）

读这个文件：

```
<VAULT_ROOT>/AGENTS.md
```

下称 **Vault**。它是关键词与内链的唯一规范来源。本 skill 里所有「查 X 表」「跑 Y 脚本」都指 Vault 内的路径。

## 断点续跑

流程位置记在文章自己的 frontmatter 里，**不另建状态文件**：

```yaml
pipeline_stage: M4        # M1…M9 或 done
```

被打断后重新进入：读目标文章的 `pipeline_stage`，从下一个模块继续。
没有 `article_id` 就是全新选题，从 M1 开始。

---

## 三阶段九模块

| 阶段 | 模块 | 做什么 | 谁做 |
|---|---|---|---|
| **一 · 选题** | M1 | 选题输入与关键词候选 | 本 skill |
| | M2 | **闸 1** 关键词冲突审核 | Vault SOP-1 |
| | M3 | **闸 1.5** 信息增益 + SERP 与 H2/H3 大纲 | 本 skill + `gate.py` |
| **二 · 写作** | M4 | **闸 2** 内链设计 | Vault SOP-2 |
| | M5 | 正文撰写 | `human-writing-AYI`（先取档案）+ `seo-geo-check` |
| | M6 | SEO 元数据与 GEO 要素 | 本 skill + `check_geo.py` |
| **三 · 整理** | M7 | 格式整理与视觉优化 | `article-visual-polish` |
| | M8 | 质检与去 AI 味 | `check_ayi.py` + `article-quality-checker` |
| | M9 | **闸 3** 回写索引与交付 | Vault SOP-2 B |

每个模块的输入 / 输出 / 通过条件 / 委托边界，全部写在 [reference/module-contracts.md](reference/module-contracts.md)。
**改任何单个模块，只改契约文件里那一节，不动本文件。**

---

## 流程

### M1 · 选题输入

从用户拿到的可能是：一个 H1、一个关键词、一个模糊话题，或者一句「写点什么」。

- 只给了话题 → 先查 Vault `02-主题簇/*.md` 的**待写选题池**。那里的候选是上一篇文章的内链缺口，需求已经被验证过，优先于凭空想题。
- 一个题目只能有**一个**主关键词。说不出唯一的那个词，回去拆题。
- 同时定：3–8 个副关键词、搜索意图、语言、所属簇。

### M2 · 闸 1 关键词冲突审核

按 Vault `05-SOP/SOP-1-选题与关键词审核.md` 执行。先跑机械检查：

```bash
cd "<Vault>" && python3 "工具/openx_audit.py" keyword --lang zh-Hant --primary "候选主词" --secondary "副词1,副词2"
```

**L1 或未解决的 L2 → 停在这里，不准往下写。** 脚本说通过也只是字面通过，语义判断按 SOP-1 Step 3 走。

过闸后建文件（这步不能省，不建文件下一篇会漏判）：

```bash
cd "<Vault>" && python3 "工具/new_article.py" --lang zh-Hant --title "标题" --primary "主词" \
  --secondary "副词1,副词2" --cluster "簇名" --slug "url-slug" --intent 信息型
```

脚本会分配 `article_id`、建 idea 文件、递增 ID 台账、写两张索引表。输出 `article_id` 和文件路径。

### M3 · SERP 分析与大纲

#### 闸 1.5 · 信息增益（写大纲之前，不许跳）

**全流程唯一一道朝外看的闸。** 闸 1 查的是新文跟**站内**旧文撞不撞，
它从不问「SERP 前 10 已经写得多好、这篇有什么是他们没有的」。
少了这一道，M1–M9 能一路绿灯产出一篇结构完美、元数据齐全、而内容前 10 名全都有的文章。

```bash
mkdir -p "<Vault>/06-工作区/增益/OX-xxxx"
# 按模块契约写至少 1 条增益，附可追溯来源与读者价值
python3 ~/.claude/skills/seo-writing-orange/scripts/gate.py gain "<Vault>/06-工作区/增益/OX-xxxx" --min-items 1
```

一手来源指官方文档 / GitHub / 公告原文；自己实测的写明日志或截图出处。
「据研究表明」「业内普遍认为」不算。**未满足至少 1 条可追溯增益 → exit 1**，三个选择：
回 M1 补研究 ／ 缩题（H1 一起改）／ 明确告诉主人这篇不建议写。**不许凑数硬写。**

#### 大纲

见 [reference/serp-and-outline.md](reference/serp-and-outline.md)。产出 H2/H3 骨架 + 每个 H2 一句话结论，写进文章文件。
**大纲定稿后立刻走 M4，不要跳到 M5 写正文。**

### M4 · 闸 2 内链设计

按 Vault `05-SOP/SOP-2-内链设计.md`。这一步必须在大纲之后、正文之前——内链要长在内容骨头上，写完再塞位置总落段尾。

```bash
cd "<Vault>" && python3 "工具/openx_audit.py" links --lang zh-Hant --cluster "簇名" --keywords "主词,副词1"
cd "<Vault>" && python3 "工具/openx_audit.py" backlink --lang zh-Hant --target <本文ID> --keyword "本文主词"
```

产出两张表写进文章文件的「内链清单」节：

- **新文 → 旧文**：目标 ID、插入 H2、触发词、锚文本（取目标的 `anchor_offers`）
- **旧文 → 新文**：待改旧文、行号、原句、锚文本 —— 这批进 Vault `内链矩阵` 的待补队列，M9 执行

密度约束：每 800 字 ≤2 条、单篇出链 3–8 条、同一目标全文只链一次。

### M5 · 正文撰写

**先取本篇的稿件档案，再调 `human-writing-AYI`。**

```bash
python3 ~/.claude/skills/human-writing-AYI/scripts/pick_profile.py pick \
  --genre 教程 --title "<本篇标题>" --length 长文 \
  --log "<Vault>/01-索引/series-log.jsonl"
```

`--genre` 按本篇主导结构选：分步教你做 → `教程`；对着一个说法或一份报告逐条核 → `拆解观点`；
讲自己一段经历的复盘 → `复盘叙事`。`--length` 按 M3 定的目标字数选。

**这一步不能跳。** 不跑它，AYI 每篇都会上同一套动作、同一个节奏、同一种结尾，
50 篇下来会长出一种「这个 skill 自己的 AI 味」。档案由脚本按最近五篇算出来，
模型不自选——选择权交回给模型，它就会稳定挑它偏好的那几个。

交给 AYI 的输入：

1. **稿件档案**（上面那条命令的输出）—— 节奏档、人称档、本篇只用的三到五个动作、
   开头类型、结尾类型、小标题体例、立场、可用比喻域。**照单执行，不自行改选。**
2. 大纲（M3）
3. 内链清单（M4）—— 位置精确到 H2 + 触发词，让它写的时候就把链接嵌进句子，而不是事后插
4. 材料清单 —— AYI 版硬要求：至少一个可核对的数字锚点 + 至少一处作者自己撞出来的细节。**材料不够就先补材料，不许用重复解释灌字数。**
5. **GEO 结构要求** —— 调 `seo-geo-check` 的 brief 入口取得（D1、D3、D4、D7–D20；D2 已并入 D1、D5 已删除，以 `seo-geo-check/reference/check-items.md` 为准）。
   这些是**结构**要求（开头独立速答块、每节首段先给结论、文末来源逐条可点击），不是文风规则。
   **写前给，比写完再补有效得多**——Answer Block 和「每节先给结论」事后补是硬塞。
   但**把要求做进句子里，不要写成标签**：不许出现「快速解答｜」「先給結論：」这类字样，
   也不许拿「冷水」当小标题。闸检查的是结构，写标签只是把脚手架留在了成稿里。
   详见 module-contracts.md M5 节「结构要求不是标签」。

本 skill 不复述 AYI 的任何文风规则。档案与 GEO 结构都是**流程编排**，不是文风规则——
怎么说话仍然归 AYI，本 skill 只负责让它每篇换一套牌、并把结构要求提前交底。

内链在源稿保留 Obsidian `[[wikilink]]`；M7 用 `工具/openx_ops.py export` 按目标同语言已发布 URL 生成副本，规则见模块契约。

**写完先过 D 区审核**（委托 `seo-geo-check`，只审正文；A 区元数据与 E 区 Schema 是 M6 的产出，此刻还不存在）：

```bash
python3 ~/.claude/skills/seo-geo-check/scripts/audit_d.py "<文章.md>" --stage scan
#   ↑ 机检 + 写出评审任务，然后 spawn 独立评审 subagent（只给成稿与任务文件）
python3 ~/.claude/skills/seo-geo-check/scripts/audit_d.py "<文章.md>" --stage verify
```

不通过 → 带失败项打回本模块改稿，**上限 2 轮，第 3 轮仍不过停下来问主人**。
**审核方不许改稿**——它改了就同时是作者和评审。

### M6 · SEO 元数据与 GEO

产出 meta title / description / slug / 分类 / 标签 / Schema / GEO 要素，写进文章文件末尾的「上稿用 SEO 資訊」节。
必产项清单见 [reference/module-contracts.md](reference/module-contracts.md) M6 节，逐项判定规则见
[reference/geo-check-items.md](reference/geo-check-items.md)。

```bash
python3 ~/.claude/skills/seo-writing-openx/scripts/check_geo.py "<文章.md>" --init   # 首次：生成人工项模板
python3 ~/.claude/skills/seo-writing-openx/scripts/check_geo.py "<文章.md>"          # 填完后：正式判定
```

脚本逐项检查 A（元数据）/ D（GEO 要素）/ E（Schema），每项打印实测值与判定依据。
判不了的项要求在 `06-工作区/GEO自检/<article_id>.md` 留书面结论，
**缺答案或答案少于 8 字符照样 exit 1**——人工项能被跳过，这道闸就退回散文红线了。

站点级的 J 区（canonical / hreflang / 分页 / 全站 title 唯一）走 `check_geo.py --site`，按站点确认一次，不必每篇跑。

### M7 · 格式整理与输出

**源文件是 Vault 里的 md**，这是唯一事实来源。docx 是可选导出。

- 站内视觉强调（加粗、黄底高亮）→ 调 `article-visual-polish`
- 需要 docx → 同上，走它的 `marked_text_to_docx.py`
- 多语言版本 → 调对应的 `web3-zh-*-translation`，内链按 Vault SOP-4 处理（目标语言版本不存在就删链，不硬翻）

### M8 · 质检与去 AI

**先做内容准确性复核，再做文风检查**（2026-09-18 加，细节见 module-contracts.md M8 节）：
spawn 一个只拿成稿与原始数据的内容复核 subagent，问三件事——结论是否超出来源、读者能否按正文完成任务且案例不含事后信息、
案例价位与时序断言能否逐根核上；同时 `audit_d.py --stage scan` 的 D18／D19／D20 是这一步的机检半边。
文风检查一律跑 `scripts/deliver_copy.py` 生成的交付态副本。


```bash
python3 ~/.claude/skills/human-writing-AYI/scripts/check_ayi.py <文章路径> \
  --profile <节奏档>:<人称档> --series "<Vault>/01-索引/series-log.jsonl"
```

`--profile` 填 M5 那份档案给的两档，脚本按该档区间判，不再拿全语料点值套。
`--series` 开跨篇检查，报最近五篇里重复的开头、结尾、立场、动作和比喻域。
**单篇怎么看都合格，同质化只在放一起看时才显形，这个参数就是为它加的。**

再走 `article-quality-checker` 做四维诊断。AI 味超标 → 回 M5 让 AYI 改稿，不要自己动手改文风。

**还要回头核对 M3 的每条信息增益**：逐条在成稿里找到对应段落，且**来路写进了正文**（读者看得到出处，
不是只有作者知道）。找不到 → 不是文风问题，是这篇少了当初立项的理由：
要么补写那一段，要么承认差异化没做出来，回 M3 重新想。

**质检通过后立刻回写文风日志**（一篇只写一行，打回改稿不重复写）：

```bash
python3 ~/.claude/skills/human-writing-AYI/scripts/pick_profile.py log \
  --log "<Vault>/01-索引/series-log.jsonl" --title "<标题>" --genre <文体> \
  --tempo <节奏档> --voice <人称档> --length <篇幅档> \
  --moves "<实际用到的动作，逗号分隔>" --opening <开头类型> --ending <结尾类型> \
  --subtitle-style <小标题体例> --stance <立场> --domains "<用到的比喻域>" \
  --thesis "<本篇的核心判断，一句话>" [--portable]
```

`--thesis` 先自查：把这句里的主题词换成上一篇的主题，**如果还读得通就加 `--portable`**，
下一篇会被强制换立场。不回写，下一篇就没有记忆，整套轮换等于没装。

### M9 · 闸 3 回写与交付

**这是最容易烂掉的一环。不回写，下一篇的审核就是基于过期数据在判断。**

结构性回写走脚本（幂等，可重复跑；先 `--dry-run` 看 diff）：

```bash
cd "<Vault>" && python3 "工具/writeback.py" --article OX-xxxx --lang <lang> \
  --status published --url "https://..." --publish-date YYYY-MM-DD \
  --outbound "OX-aaaa,OX-bbbb" --stage done --anchors "锚1,锚2,锚3"
```

它做掉：文章 frontmatter（status / url / publish_date / updated / pipeline_stage / outbound_links）、
**对端文章的 inbound_links**（保证对称，scan 第 4 项查这个）、文章总表三处（主记录状态 / 语言矩阵 / URL 登记）、
关键词登记表主词状态、锚文本池。

它**不做**、并会在结尾逐条列出来的三件事（都需要语义判断，不该由脚本做）：

1. 旧文正文里真的插进那条 wikilink —— 锚文本要嵌进句子里
2. 内链矩阵「已落实链接」明细行 —— 插入位置与锚文本只存在于正文里
3. 内链矩阵「待补链接队列」勾销 —— 得先确认旧文真的改了

**这三件必须真的做完，M9 才算完成。** 脚本跑完不等于闸 3 过了。

收尾体检：

```bash
cd "<Vault>" && python3 "工具/openx_audit.py" scan
```

---

## 红线

1. **不许跳闸。** M2 未过不写大纲，**闸 1.5（信息增益）未过不写大纲**，M4 未做不写正文，M9 未做不算交付。
   M5 未取稿件档案不动笔，M8 未回写文风日志不进 M9——**日志断一篇，后面所有篇的轮换都从那里错位。**
2. **不许在本 skill 里重写文风规则。** 正文一律走 AYI。
3. **不许绕过建文件。** M2 过闸后必须建出 idea 文件，否则这篇对系统不存在。
4. **不许链到不存在的页面。** 目标文章的目标语言版本没有，就删掉那条链接并登记待补。
5. **本篇可执行的待补链接须完成。** 尚未立项、未发布或缺目标语言的依赖保留为待补，写清原因；不得假勾销，也不得因远期选题阻塞全流程。

## 已知边界（beta）

- `工具/writeback.py` 已实现（幂等 + diff + dry-run），但只覆盖**结构性**回写。内链矩阵的明细行、待补队列勾销、旧文正文插链仍需人工，脚本会逐条列出待办。
- 已有发布导出映射工具，依据真实 URL，不猜域名或路由；正式域名、CMS 和上稿方式未提供时，仅交付 ready 源稿及缺口清单。
- 1000X 迁移路线已于 2026-09-17 取消，不再等待旧站回填；M2 审核范围是 OpenX 实际在库文章，外站素材不冒充本站存量。

## 系统维护与版本日志

本仓库 `skills/` 是发行源；安装可用 `--agents` 为代理创建共享入口，不另复制规则。
修改规则、脚本或流程后，必须遵循 Vault `工具/系统维护.md`，并在 Vault 根目录 `版本更新日志.md` 追加版本、原因、改动、验证、未完成依赖和回滚记录。无日志不得宣称更新完成。
