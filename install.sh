#!/usr/bin/env bash
# OpenX 文章系统安装：复制 skills 到 ~/.claude/skills，并把本仓库绝对路径写进引用处。
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
FORCE=0; [ "${1:-}" = "--force" ] && FORCE=1
DEST="$HOME/.claude/skills"; mkdir -p "$DEST"
for s in seo-writing-openx seo-geo-check human-writing-AYI seo-writing-orange; do
  if [ -d "$DEST/$s" ] && [ $FORCE -eq 0 ]; then echo "跳过 $s（已存在，加 --force 覆盖）"; continue; fi
  rm -rf "$DEST/$s"; cp -R "$HERE/skills/$s" "$DEST/$s"; echo "已安装 $s → $DEST/$s"
done
for f in "$HERE/CLAUDE.md" "$HERE/AGENTS.md" "$DEST/seo-writing-openx/SKILL.md" "$DEST/seo-writing-openx/reference/module-contracts.md" "$DEST/seo-writing-openx/scripts/check_geo.py"; do
  [ -f "$f" ] && sed -i.bak "s#<VAULT_ROOT>#$HERE#g" "$f" && rm -f "$f.bak"
done
echo
echo "完成。接下来："
echo "  1. 填 01-索引/作者资料.md，并 export OPENX_AUTHOR / OPENX_AUTHOR_CREDENTIALS"
echo "  2. （可选）export OPENX_VAULT=\"$HERE\"；不设也行，脚本会从文章路径向上找 Vault"
echo "  3. pip3 install opencc-python-reimplemented matplotlib"
echo "  4. 读 CLAUDE.md，建第一个主题簇与 pillar，然后跑闸 1"
