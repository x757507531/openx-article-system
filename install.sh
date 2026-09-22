#!/usr/bin/env bash
# 安装发行快照；可选共享代理入口。已有目录仅在 --force 时备份后替换。
set -e
OPENX_SOURCE_ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 - "$OPENX_SOURCE_ROOT" "$@" <<'PY'
import argparse
import datetime
import os
import re
import shlex
from pathlib import Path
import shutil
import sys
import tempfile

parser = argparse.ArgumentParser(description="安装 OpenX skills，--force 备份后更新；--agents 创建共享代理入口")
parser.add_argument("--force", action="store_true")
parser.add_argument("--agents", action="store_true")
parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".claude/skills")
parser.add_argument("--agents-dir", type=Path, help="自定义代理入口目录，同时启用共享入口")
args = parser.parse_args(sys.argv[2:])
source = Path(sys.argv[1]).resolve()
dest = args.skills_dir.expanduser().resolve()
agent_dir = (args.agents_dir or Path.home() / ".agents/skills").expanduser().resolve()
names = ("seo-writing-openx", "seo-geo-check", "human-writing-AYI", "seo-writing-orange")
shared = names[:2] if args.agents or args.agents_dir else ()
# 在创建目录或改文件之前检查不安全的目录关系与代理冲突。
for directory in ([dest] + ([agent_dir] if shared else [])):
    if directory == source or source in directory.parents or directory in source.parents:
        parser.error("安装目录不能与仓库源目录相互包含")
if shared and (agent_dir == dest or dest in agent_dir.parents or agent_dir in dest.parents):
    parser.error("技能目录与代理入口目录不能相同或相互包含")
for name in shared:
    link = agent_dir / name
    same = link.is_symlink() and link.resolve() == (dest / name).resolve()
    if os.path.lexists(link) and not same and not args.force:
        parser.error(f"代理入口 {link} 已存在；保留原件，使用 --force 才会备份后替换")
for name in names:
    required = "scripts/gate.py" if name == "seo-writing-orange" else "SKILL.md"
    if not (source / "skills" / name / required).is_file():
        parser.error(f"发行源缺少 {name}/{required}")

backup_dir = None

def backup(path):
    global backup_dir
    if backup_dir is None:
        base = dest.parent / ".openx-install-backups"
        base.mkdir(parents=True, exist_ok=True)
        backup_dir = Path(tempfile.mkdtemp(prefix=datetime.datetime.now().strftime("%Y%m%d-%H%M%S-"), dir=base))
    target = backup_dir / ("agents-" + path.name if path.parent == agent_dir else "skills-" + path.name)
    path.rename(target)
    print(f"已备份 {path} → {target}")

dest.mkdir(parents=True, exist_ok=True)
for name in names:
    target = dest / name
    if os.path.lexists(target) and not args.force:
        print(f"跳过 {name}（已存在，加 --force 备份后更新）")
        continue
    if os.path.lexists(target):
        backup(target)
    shutil.copytree(source / "skills" / name, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for file in target.rglob("*"):
        if file.is_file() and file.suffix in (".md", ".py"):
            text = file.read_text(encoding="utf-8")
            # Python 源码中的路径必须使用字符串转义，支持空格、引号与反斜杠。
            replacement = str(source) if file.suffix == ".md" else str(source).replace("\\", "\\\\").replace('"', '\\"')
            text = text.replace("<VAULT_ROOT>", replacement)
            # 脚本以相邻技能目录定位依赖；文档同步自定义安装位置。
            if file.suffix == ".md":
                text = re.sub(r"(?m)(python3?\s+)(~/.claude/skills/[^\s`\"\']+)",
                              lambda m: m[1] + shlex.quote(str(dest) + m[2][len("~/.claude/skills"):]), text)
                text = text.replace("~/.claude/skills", str(dest))
            file.write_text(text, encoding="utf-8")
    print(f"已安装 {name} → {target}")
if shared:
    agent_dir.mkdir(parents=True, exist_ok=True)
    for name in shared:
        link, target = agent_dir / name, dest / name
        if link.is_symlink() and link.resolve() == target.resolve():
            continue
        if os.path.lexists(link):
            backup(link)
        link.symlink_to(target, target_is_directory=True)
        print(f"共享入口 {link} → {target}")
print("完成。读仓库 AGENTS.md，填写真实作者资料；可设置 OPENX_VAULT。仓库源文件未改写。")
PY
