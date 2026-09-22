# skills/

四个 skill 的发行快照，`install.sh` 会把它们复制到 `~/.claude/skills/`。

| skill | 角色 |
|---|---|
| `seo-writing-openx` | 产文编排 M1–M9；`scripts/check_geo.py`（A/D/E/J 区机检）、`scripts/deliver_copy.py`（交付态副本） |
| `seo-geo-check` | D 区正文 GEO 检查：`reference/check-items.md` 是全部检查项的唯一事实来源，`scripts/audit_d.py` 做机检、生成独立评审任务并回验证据 |
| `human-writing-AYI` | 正文写作文风与稿件档案轮换（`pick_profile.py` / `check_ayi.py`），通用 skill，不含站点信息 |
| `seo-writing-orange/scripts/gate.py` | 闸 1.5 信息增益与大纲检查所依赖的脚本（仅收录该脚本） |

默认安装到 `~/.claude/skills/`，可用 `--skills-dir` 指定目录。两个 SEO 脚本以相邻目录定位依赖。`--agents` 为这两个 skill 创建共享入口，避免两份安装规则漂移；已有冲突需 `--force`，会先备份再替换。仓库快照不受安装时路径替换影响。
