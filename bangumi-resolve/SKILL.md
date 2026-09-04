---
name: bangumi-resolve
description: >
  Resolve anime/manga/game metadata from Bangumi API (api.bgm.tv) to determine completion
  status, episode counts, and Chinese names. No API key required (public access).
  Use when the user wants to know whether a series has finished, how many episodes it has,
  or its Bangumi subject ID. Especially useful for "追剧" workflows: given a list of
  shows on the NAS, identify which are still airing (未完结 / 追剧中).
---

# Bangumi Resolve

通过 Bangumi API（无需 API Key）解析 ACG 元数据。

## 数据源

- **API**：https://api.bgm.tv/v0/
- **鉴权**：**无需注册、无需 Key**
- **UA 要求**：必须带 `User-Agent: <name>/<version>` 否则 412

## 脚本

| 脚本 | 用途 |
|------|------|
| `scripts/bg_search.py` | 按剧名搜 subject（返回 id/中文名/连载状态） |
| `scripts/bg_subject.py` | 查 subject 详情（总集数/完结/评分） |
| `scripts/bg_ongoing.py` | 给定剧名列表，识别哪些"追剧中"（series=true） |

## 决策表

| 想知道什么 | 怎么用 |
|-----------|--------|
| 「转生史莱姆」的 Bangumi ID | `python scripts/bg_search.py "转生史莱姆"` |
| subject_id 245454 的详情 | `python scripts/bg_subject.py 245454` |
| 哪些剧还在连载 | `python scripts/bg_ongoing.py "转生史莱姆" "高木同学" "怪奇物语"` |

## 类型编码

| type | 含义 |
|------|------|
| 1 | 书籍 |
| 2 | 动画 |
| 3 | 音乐 |
| 4 | 游戏 |
| 6 | 三次元（美剧/日剧/电影） |

## 关键字段（搜索结果）

- `series` (bool): true = 连载中（**未完结**），false = 已完结
- `eps` (int): 当前已发布集数
- `total_episodes` (int): 总集数
- `name_cn`: 中文名
- `rating.score`: Bangumi 评分

## 与下游集成

输出可管道到 dmhy-search：

```bash
python ~/.hermes/skills/bangumi-resolve/scripts/bg_subject.py 388134 --json \
  | jq '.name_cn'
```

## 已知限制

- 命中率依赖 Bangumi 数据库完整性（中文 ACG 覆盖最佳，欧美剧次之）
- 同名搜索需精确关键词（如"史莱姆"返回多个结果）
- 限速未公开，但建议加 0.5s 间隔以免被临时 ban