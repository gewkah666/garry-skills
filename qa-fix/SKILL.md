---
name: qa-fix
description: >
  修复 Notion Tasks 中 Status 为 Needs Fix 的任务。QA 把问题写在任务页的
  `## Test log` 下，每条是一个 `### QA-NN` 项，含复现步骤、实际结果、预期结果和截图。
  本 skill 读懂每条问题，在新分支上复现，先写回归用例再修，按仓库规则复验并通过 PR 合入。
  确认 QA 的复验入口已经包含修复后，在每条 QA 项下写修复记录，再把 Status 改为
  Testing，交回 QA 复验。用于 /qa-fix、「修 Needs Fix 的任务」「把 test log 里的问题修了」
  「处理 QA 提的问题」。Notion 访问、分支、PR、确认和 Docs 规则都沿用 dev-tasks。
---

# QA 修复：Needs Fix → Testing

状态流转：`Done` → QA 测出问题 → `Needs Fix` → **本 skill 修复** → `Testing` → QA 复验 →
`Done`，或者再次 `Needs Fix`。QA 会自动复验进入 `Testing` 的任务。因此只有在修复已经出现在
复验入口时才能转 `Testing`。否则 QA 测到的还是旧代码，任务会马上退回。

## 先读

- **dev-tasks 的 SKILL.md**（同仓库 `../dev-tasks/SKILL.md`）。本 skill 沿用它的以下规则：
  Notion access、Mandatory Git branch、Mandatory promotion pipeline、Confirmation in Notion、
  Document locations、Time rules 和 day index。下文只写本 skill 特有的部分。
- 目标仓库的 `CLAUDE.md` / `AGENTS.md`，以及 workspace 记忆里这个项目的协调规则，例如测试窗口、
  谁来合并、验收环境归谁管。仓库规则优先。

## 脚本

`scripts/qa_fix.py`（只用 REST，token 取自 `$NOTION_TOKEN` 或 `~/.hermes/notion-relay.json`，不打印）：

| 命令 | 作用 |
|---|---|
| `list [--project 名] [--page 页]` | 列出 Needs Fix 任务，以及每条 QA 项的 `state`、优先级和 `claimed`，按优先级排序 |
| `show <页> --out <目录>` | 输出 Goal、Docs、Work log，以及每条 QA 项的字段（保留复验入口链接）、各段内容、修复记录和 `after_fix`；截图下载到目录 |
| `start <页> --text "…"` | 在 Work log 记一行「修复开始」，作为认领 |
| `record <页> <QA-ID> --cause --change --test --retest [--result 已修复\|不修改\|未复现]` | 在该 QA 项末尾插入一个「修复」callout |
| `log <页> --label 标签 --text "…"` | 在 Work log 记一行，顺序跟随页面现有顺序（新的在上或新的在下） |
| `testing <页> [--text "…"] [--dry-run]` | 检查后 Status → Testing，并在 Work log 记「转 Testing」 |
| `watch --state <文件> [--interval 秒] [--project 名]` | 后台轮询（默认 300 秒），出现新的待修 QA 项就打印并退出；见「监控」 |

只有 `### QA-NN` 开头的三级标题才算一条问题；Test log 里别的三级标题（例如 QA 的补测说明）是备注，不算问题项，也不挡 `testing`，但要读一遍，看里面有没有新问题。

QA 项的 `state` 有三种：
- `open`：还没有修复记录。
- `fixed`：修复记录是这一项的最后一块。
- `reopened`：修复记录之后 QA 又写了内容，读 `after_fix` 了解上次为什么没过。

`testing` 只在 Status 为 Needs Fix，且每一项都是 `fixed` 时才执行；其余情况会列出原因并以 exit 2 退出。
Notion 的截图链接一小时后失效，需要时重新跑 `show`。

## 监控

用户要求盯着 Needs Fix 时，在会话里挂一个后台 `watch`：

```
python3 <skill-dir>/scripts/qa_fix.py watch --state ~/.claude/dev-tasks/qa-fix-watch.json
```

- Claude Code 用 Bash 的 `run_in_background` 启动。它一直轮询，直到出现状态文件里没有的待修项：
  新的 `open` 项，或 QA 复验后变成 `reopened` 的项。这时它把这些项打印成 JSON 后退出，会话被唤醒。
- 被唤醒后，按下面的流程处理这些项，然后**马上重新挂上**同一条命令，状态文件不变。
  正在修的时候也要挂着，新到的项排在当前任务之后处理。
- 状态文件不存在时，第一轮把当前所有待修项记为基线，不报警。适合开监控时这些项已经在修、
  或已排进本轮的情况。想让当前的待修项也报一次，就先删掉状态文件。
- 网络断开或 Notion 报错时，它在 stderr 记一行并继续轮询，不会退出。
- 会话结束，监控就停了。不能常驻后台进程的环境（例如 Hermes），用定时任务定期跑 `list`，
  拿结果和上次比较。

## 流程（一次处理一个任务）

1. **选任务。** 用户点名了任务或项目，就只处理那个；否则跑 `list`。`claimed` 不为空，说明有人在修，
   跳过并告诉用户。按优先级排序，在聊天里先列出这次要修的任务和 QA 项。
2. **读懂问题。** 跑 `show <页> --out <scratchpad>/qa-<页 id 末 6 位>`，逐条读字段、复现步骤、
   实际结果和预期结果，并用 Read 查看每张截图。再从 Goal、Docs、Work log 找出仓库、原分支、PR、
   合并提交、worktree 的命名方式，以及作为依据的设计文档。`reopened` 项先读 `after_fix`。
3. **认领。** 跑 `start`，写明 QA 项、分支和 worktree；在 day index 加一行，Status 写 `Needs Fix`，
   注明「修复中」。修复期间 Status 保持 Needs Fix。`Completed On` 始终不动：它记的是原任务的时间，
   修复的起止和用时写在 Work log 里。
4. **分支和 worktree。** 原任务分支已经合并，不要复用。按 dev-tasks 的规则从 `origin/main` 新建
   分支，名字在原分支名的后缀前插入 QA 编号，例如 `task/s3-c6b-225717` → `task/s3-c6b-qa03-225717`。
   worktree 放在仓库现有 worktree 旁边，不要在主检出里改。如果要改文档，另开一个文档 worktree。
5. **复现。** 在自己的 worktree 和环境里，按 QA 给的步骤、视口和数据复现。复验入口往往是别人的
   共享环境，只能浏览，不改数据，不重启。把 QA 的步骤和预期结果写成回归用例（界面问题用浏览器
   用例，逻辑问题用单测），并确认它在修复前失败。复现不了时不要猜：用 `notion_confirm.py ask`
   附上证据提问，选项例如「记为未复现，交回 QA」和「等 QA 补充信息再查」。
6. **定范围。** 预期结果清楚的缺陷直接修。遇到下面几种情况，先写一个简短方案，再走 dev-tasks 的
   Confirmation in Notion（一次只问一项）：
   - 预期结果和设计文档冲突；
   - 需要改 API 契约或新的界面结构；
   - 超出原任务的范围；
   - 打算不修改。

   修复遵守仓库的设计原则。例如 API first：行为错误要在 core 和契约里修，不能只在界面上遮掉。
   同一个组件里的同类问题一起修，并写进回归用例。不相关的新问题只记在 Work log 里，告诉用户，
   不要顺手修。
7. **修复并复验。** 修好后，回归用例应当通过。按仓库规则跑完整复验。然后在自己的环境里，用同样的
   视口和数据实际走一遍 QA 的步骤，把关键数据记下来，例如「390 px 下画布 358 px，标注框完整」。
   改动了有文档记载的行为时，按仓库规则同步更新文档。
8. **合入。** 按 dev-tasks 的 promotion pipeline 和仓库规则开 PR 并合并：没有 dev / staging 环境的
   仓库直接合到 `main`；合并前的复验和协调按项目记忆执行。合入前按 Document locations 核对 `## Docs`。
9. **让复验入口包含修复。** 合入后，确认 QA 的复验入口运行的提交已经包含这次修复。环境归自己管，
   就自己刷新；归别人管，就把合并提交发给负责人，等对方刷新并回复新地址。地址变了，新地址写进
   修复记录。在这一步完成之前，不要转 Testing。
10. **写回 Notion。**
    - 每条 QA 项跑一次 `record`。内容示例：
      - `--cause`：一句话根因；
      - `--change`：改了什么，PR #n，合并提交 `<sha>`，有文档变更的话写上文档 PR；
      - `--test`：回归用例的「文件 + 用例名」；
      - `--retest`：复验入口（写地址），步骤与 QA 的是否相同，环境需要的最低提交，例如「≥ `<sha>`」。

      `不修改` 和 `未复现` 只能在用户确认之后使用，`--cause` 写原因，`--change` 写结论和确认来源。
    - 跑 `log --label 修复完成`，写上 PR、合并提交、复验数字，以及从「修复开始」到现在的实际用时。
    - 跑 `testing`，把 Status 改为 Testing，然后更新 day index。如果开了播报：
      `phantom_notify level=L1 kind=dev message="任务 <标题> 已修复，转 Testing 等复验"`。
11. **汇报。** 在聊天里用一张表列出每条 QA 项：结论、PR 和合并提交、复验入口地址和操作步骤，
    并附上任务页链接。

## 多项与多任务

- 一个任务里的几条 QA 项在同一个仓库时，合用一个分支和一个 PR，但每条各写各的回归用例和修复记录。
  涉及几个仓库时，每个仓库一个分支，每条修复记录写明自己的 PR。
- 多个任务默认按优先级依次处理。并行时一个任务交给一个代理，合并由主代理按顺序进行；派代理时
  遵守用户关于子代理的记忆规则。

## 中途需要用户拍板

用 `../dev-tasks/scripts/notion_confirm.py` 提问：`ask` 把 Status 改为 Pending for Confirm，
`resolve` 再恢复为 Needs Fix。提问块写在 Work log 末尾，不会落进 Test log。等待期间 `testing`
会拒绝执行。在聊天里得到的回答同样有效，处理方式见 dev-tasks。

## 不做的事

- 不在修复合入、复验入口包含修复之前转 Testing。
- 不改、不删 QA 写的文字和截图，只在每条后面追加修复记录。
- 不把任务标成 Done：Done 由 QA 复验通过后设置。
- 不改 `Completed On`，不复用已合并的原分支，不动别人的验收环境。

## 已知仓库

- **immersif-platform**（Notion Project 是 LEDPoint，QA 字段「项目」写 Immersif Platform）：worktree
  放在 `/Users/garry/Projects/ledpoint/.tree-immersif/`，PR 直接到 `main`。复验链、测试窗口和合并
  时机按 workspace 记忆里的阶段协调规则执行。复验入口是阶段 3 的合并验收站，由阶段 3 协调人管理：
  合入后通知对方刷新，以对方回复的新端口为准。文档改动走 `immersif-doc`，按它的 `AGENTS.md` 写
  中英文变更记录。
