#!/usr/bin/env python3
"""
collab_resource.py - 把这趟行程的协作配置吐成 notion-relay 的资源描述（JSON 到 stdout）

管道给 notion-relay 的 deploy.sh，token 就不用落到磁盘上：

  python3 scripts/collab_resource.py output/<slug>/guide.json \
    | ~/Projects/notion-relay/service/deploy.sh --register -

输入来自两个文件（都在 output/<slug>/ 里、都不入库）：
  collab.json     init_collab.py 建表时写的 database_id
  published.json  publish_guide.py --share 写的分享链接（token 在 URL 的 ?t= 里）

资源名 = 分享 slug，所以页面里的 /s/api/n/<slug>/ 和 /s/<slug>/ 对得上。
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

# 同行者能改的字段。键是 Notion 里的属性名，值给页面渲染表单用（类型从 Notion
# 的 schema 读，这里只补人话标签和提示）。想多开一个字段，在 Notion 里建好列，
# 然后加到这里、重新 --register 即可，页面不用改。
FIELDS = {
    "饮食忌口": {"label": "饮食忌口 / 过敏", "placeholder": "例：不吃香菜、海鲜过敏"},
    "住宿偏好": {"label": "住宿偏好"},
    "住宿备注": {"label": "住宿备注", "placeholder": "例：想住安静的一侧"},
    "紧急联系人": {"label": "紧急联系人"},
}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    guide = Path(sys.argv[1])
    d = guide.parent
    collab_p, pub_p = d / "collab.json", d / "published.json"
    if not collab_p.exists():
        sys.exit(f"❌ 缺 {collab_p} —— 先跑 scripts/init_collab.py init")
    if not pub_p.exists():
        sys.exit(f"❌ 缺 {pub_p} —— 先跑 publish_guide.py … --share")

    collab = json.loads(collab_p.read_text())
    share = (json.loads(pub_p.read_text()).get("share") or {})
    slug = share.get("slug") or d.name
    token = urllib.parse.parse_qs(urllib.parse.urlparse(share.get("url", "")).query).get("t", [""])[0]
    if not token:
        sys.exit("❌ published.json 的 share.url 里没有 token —— 先跑 publish_guide.py … --share")

    json.dump({
        "name": slug,
        "token": token,
        "database_id": collab["database_id"],
        "title": "姓名",
        # admin 在 Notion 里勾「已加入」才会出现在认领下拉里，也才准读写
        "gate": {"property": "已加入", "equals": True},
        "fields": FIELDS,
        "children": {"add": True, "delete": True},
    }, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
