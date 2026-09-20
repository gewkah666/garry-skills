---
name: dev-tasks
description: >
  Run the user's daily development-task workflow on their Notion "Tasks" database
  via the Notion MCP server (no default project — resolve it from the repo / cwd / task
  wording, see "Which project"). Use to: plan the day (create
  today's tasks each morning and immediately create a matching Git branch for every
  task); start a task (stamp start time, Status→In Progress);
  log progress into the task's Notion page; finish a task (stamp end time + duration,
  Status→Done); detect when work drifts off the task and offer to create a new one;
  track several tasks running at once; and remove a task's dedicated Git worktree after
  its Review is explicitly approved. Triggered by /dev-tasks or any add / list / start /
  finish / log / review / "plan my day" / "what am I working on" request. Optional
  announcements via `phantom_notify` (see the "Announcements" section).
---

# Dev Tasks (Notion) — daily workflow

Manage the user's development tasks in the Notion **Tasks** database through Hermes' Notion
MCP server (`notion`: search / fetch / query-data-source / create-pages / update-page /
move-page). This skill runs on **Hermes (Phantom)**; Claude Code no longer owns it.

This skill is a **workflow**, not just CRUD. The four scenarios it serves:
1. **Morning planning** — turn the user's spoken plan into real Notion tasks for today.
2. **Time-tracked execution** — stamp a start time when a task begins and an end time when
   it finishes, and record what happened into that task's Notion page.
3. **Drift detection** — while a task is running, notice when the work stops matching the
   task's goal and ask the user whether to create a new task for the new thread.
4. **Concurrency** — several tasks may be In Progress at the same time; always know which
   task any action or log belongs to.

## Fixed IDs (use directly; don't re-discover)

| Thing | Value |
|---|---|
| Tasks **data source** (create + SQL) | `collection://3f2616ff-95e7-837b-8444-074b10e56064` |
| Tasks data source **id** (`data_source_id` parent) | `3f2616ff-95e7-837b-8444-074b10e56064` |
| Tasks **database** URL | `https://app.notion.com/p/33b616ff95e780f7891ee221b0c8605d` |
| **Board** view (grouped by Status, filtered to Peppy) | `…?v=33b616ff95e780ff942c000c9ce8fe81` |
| **Projects** data source (resolve the `Project` relation here) | `collection://8aa616ff-95e7-8268-b269-0789ff95e092` |
| **Peppy** project page (mmWave radar: `mmwave-*`, `D:\Projects\peppy`) | `https://app.notion.com/p/33b616ff95e780fbbe8dcfa7273e3c86` |
| **Phantom** project page (Hermes / phantom-app / phantom-core / `~/Projects/phantom`) | `https://app.notion.com/p/Phantom-3b8616ff95e780b09023c078fa90bd57` |
| **Arc** project page (posture / fitness: `arc*`, MotionCoach) | `https://app.notion.com/p/Arc-341616ff95e781e29df7f2ad58f6498b` |

## Property schema & allowed values

Property values are **SQLite values** (string / number / null). Relation and multi-select
values are **JSON-encoded strings** (e.g. `"[\"…\"]"`).

- `Task name` — **title** (string). Required on create.
- `Status` — `Backlog`, `Not Started`, `Planning`, `Approved`, `In Progress`, `Testing`,
  `Review`, `Blocked`, `Rejected`, `Done`, `Archived`.
- `Priority` — use `Low` / `Medium` / `High` (ignore the legacy `中`/`高` dupes).
- `Completed On` — **the only time field that matters** (the user's Notion calendar sorts by
  it). It can be a **point** or a **range**: `date:Completed On:start`, `date:Completed On:end`
  (range only — omit for a point), `date:Completed On:is_datetime` (`1` for a datetime
  `YYYY-MM-DDTHH:MM:00`, `0` for a date). See **Time rules**.
- `Due` — date (`date:Due:start`, `date:Due:is_datetime`). **Optional / not the calendar
  field** — set only if the user explicitly asks for a separate deadline.
- `Tags` — multi-select JSON array. Dev options: `开发`, `测试`, `Code`, `技术方案`,
  `测试方案`, `Improvement`, `Research`, `workflow`, `automation`, `test`.
- `Project` — relation (JSON array of page URLs). **Required, never defaulted** — see
  "Which project".
- `Parent-task` / `Sub-tasks` — relations (JSON array of task URLs).
- `Agent` (`Benimaru`/`Shuna`/`Raphael`), `Assignee` (person id array) — only if asked.
- `Delay` — formula, **read-only**; never write.

Page **content** is Notion-flavored Markdown. Basic Markdown (headings, bullets, bold,
paragraphs) works directly; for anything richer read the MCP resource
`notion://docs/enhanced-markdown-spec` first — don't guess syntax.

## Time rules — `Completed On` is the only time field

`Completed On` is the **single time field this skill manages** — the user's Notion **calendar
sorts and displays by it** (not `Due`). It can be a **point** (one datetime, or a date) **or a
range** (`start`–`end`). Set it with the expanded keys: `date:Completed On:start`,
`date:Completed On:end` (range only — omit for a point), `date:Completed On:is_datetime`
(`1` for a datetime `YYYY-MM-DDTHH:MM:00`, `0` for a date). Don't manage `Due` unless the user
asks for a separate deadline.

By task state:
- **Not started** (planned): `Completed On` = **date only** (`is_datetime = 0`, no `end`) —
  the planned day, no time-of-day.
- **In progress** (started): `Completed On` = **start datetime**, a point to the minute
  (`is_datetime = 1`) = the **current system clock** (read it — never invent) **or a time the
  user specifies**.
- **Done** (finished): `Completed On` = a **range [start, end]** at the **actual times** —
  `start` = the real start, `end` = the real finish read from the **current system clock**
  (never invent, never estimate from workload). If real elapsed < 30 min, extend the
  calendar-facing `end` to `start + 30 min` (display floor so tasks don't blur on the
  calendar), but the Work-log `Duration` line always records the **real** elapsed minutes.
  **Never** move the block to a different time of day — it sits where the work actually
  happened (user correction 2026-08-10; the old "estimate end from workload" and "nudge
  research tasks to ~18:00" rules are retired).

Also mirror the times in the page `## Work log` (`- **Start** …`, `- **End** … — summary`,
`- **Duration** …` = real elapsed, minutes-honest) and the day index. The **only** allowed
divergence from reality is the 30-min calendar display floor above. Read the clock with PowerShell
`Get-Date -Format 'yyyy-MM-dd HH:mm'` or Bash `date '+%Y-%m-%d %H:%M'` (local timezone).
Concurrent tasks' blocks may overlap — that's fine.

## Local day index (the "what's active now" tracker)

Because `query-data-sources` is unavailable on this plan (see List/review), Notion can't be
asked "which tasks are In Progress?". Maintain a small local file as the durable index of
today's plan and active set. **The Notion page is the system of record for the full log;
this file is only a fast index.**

Path: `C:\Users\echoG\.claude\dev-tasks\<YYYY-MM-DD>.md` (create the folder if missing).
Format — one row per task, updated as tasks start/finish:

```
# Dev tasks — 2026-07-14
| Task | Notion URL | Status | Start | End | Dur | Project | Repo | Branch |
|---|---|---|---|---|---|---|---|---|
| Fix SSE reconnect | https://app.notion.com/p/… | In Progress | 09:12 |  |  | Peppy | mmwave-dashboard | task/fix-sse-a1b2c3 |
```

At the start of a working session, read today's file (if present) to recover the active
set. If it's missing but the user has clearly been mid-work, offer to reconstruct it. When
updating an older index without `Repo` / `Branch` columns, add them and preserve its rows.

---

## Task granularity — keep it coarse (~30 min+)

One task = one meaningful chunk of work, **roughly half an hour or more**. Do **not** split
work into many small tasks — on the Notion board they blur together and become noise. Group
related small steps under a single task and record the steps as Work-log bullets (or a
checklist in the page body), **not** as separate tasks. If the user's plan lists lots of
micro-items, propose merging them into a handful of ~30-min+ tasks before creating. Err
toward fewer, larger tasks. (This is about task size only — start/end times are still stamped
to the minute.)

## Mandatory Git branch at Notion task creation

Every Notion task created by this skill must immediately receive its own Git branch. There
are no branchless task exceptions in this workflow. The Notion page and branch are one
logical creation operation: do not report the task as created, announce a successful plan,
or proceed to work until both exist.

1. Before writing to Notion, resolve the exact repository and intended base branch for each
   task. Prefer the repository already in scope and its configured integration branch; if
   several repositories are plausible or none is known, ask before creating the task.
2. Create the Notion page first so its page ID can make the branch unique. Follow the
   repository's branch convention; when none exists, use
   `task/<ascii-task-slug>-<short-unique-page-id-suffix>` (at least 6 characters; extend it
   on collision). Never reuse another task's branch.
3. Create the branch without switching or modifying the user's primary worktree. Fetch the
   intended remote base when available, then use an explicit start point, for example:
   `git -C <repo-root> branch <branch> origin/<base>`. If there is no remote, use the verified
   local base. Confirm the ref resolves with `git show-ref --verify refs/heads/<branch>`.
4. Append `- **Branch** <branch> — repo <absolute repo root>; base <start point>` to the
   Notion Work log and store the repository and branch in the local day index.

If branch creation or verification fails after the Notion page exists, set that page to
`Blocked`, append the exact failure to its Work log, update the day index, and announce the
blocker. Do not silently use the base branch, create changes in the primary worktree, or call
the task successfully created. Retry the same intended branch after resolving the problem.

## Scenario 1 — Morning planning ("plan my day" / a list of todos)

1. Gather the day's intended tasks from the user (ask briefly if the list is vague). Keep
   them **coarse** (see Task granularity) — if the user lists many micro-items, propose
   merging them into a few ~30-min+ tasks before creating.
2. For **each**, capture a one-line **Goal/scope** and resolve its repository/base branch per
   **Mandatory Git branch at Notion task creation**. Ask if either is ambiguous.
3. Batch-create them with `notion-create-pages`, parent
   `{ type: "data_source_id", data_source_id: "3f2616ff-95e7-837b-8444-074b10e56064" }`,
   each with: `Task name`, `Status: "Not Started"`, `Project` (resolved per "Which project"), `Completed On` = today
   (date only), `Priority` if the user implies one, dev `Tags` when clearly applicable. Put the Goal/scope
   in the page `content` under a `## Goal` heading, and add an empty `## Work log` heading.
4. Immediately create and verify one dedicated branch per returned Notion page (per
   **Mandatory Git branch at Notion task creation**), then write the branch/repository to
   the page Work log and local day index. Handle any failure as `Blocked`; never leave it
   unreported as a successful task creation.
5. Report back the successfully created task+branch pairs as a Markdown list with clickable
   Notion links. List blocked pairs separately with the failure.
6. **(Optional) Announcement** — if announcements are on (see "Announcements"), only after
   all branch attempts finish, announce the accurate result. Use the normal success phrase
   only when every requested pair succeeded; otherwise announce the success count and the
   blocked tasks. Normal success:
   `phantom_notify level=L1 kind=dev message="今天的任务已规划，共 N 个，第一个是 <task 1 title>"`.

## Scenario 2 — Start / execute / finish a task (time-tracked)

**Start:** start time = the current system clock **or** a time the user gives (see Time rules)
→ `notion-update-page` `update_properties`
`{ "Status": "In Progress", "date:Completed On:start": "<YYYY-MM-DDTHH:MM:00>", "date:Completed On:is_datetime": 1 }`
(`Completed On` as a start point) → append to the page `## Work log` `- **Start** <YYYY-MM-DD HH:MM>`
(`insert_content`, `position: end`) → set the day-index row Status `In Progress` and Start time.
→ **(Optional) Announcement** — if enabled, `phantom_notify level=L1 kind=dev message="开始任务 <task title>"`.

**During:** append progress notes to the task's `## Work log` as bullets (what was done,
decisions, blockers, links). Each entry should make it obvious which task it belongs to when
several are open. Keep the system of record in Notion; keep the day index in sync for status.
Three kinds of mid-task events are worth an **announcement** (optional — see "Announcements"),
right after the Work-log line is written:

- **Problem / blocker hit** — an error that stops progress, a missing credential/permission,
  a failing build, an unexpected dead end:
  `phantom_notify level=L1 kind=dev message="任务 <task title> 遇到问题：<一句话问题>"`
- **Phase completion** — a distinct sub-deliverable done while the task keeps running
  (e.g. 调研完成开始写方案 / 后端通了开始联调):
  `phantom_notify level=L1 kind=dev message="任务 <task title> 阶段性完成：<一句话成果>"`
- **Key finding / discovery** — evidence that changes the picture: a root cause pinned down,
  data that overturns an assumption, an unexpected decisive measurement (e.g. 根因锁定 /
  实测推翻假设 / 关键实证出炉). Announce it the moment it lands, not at task end:
  `phantom_notify level=L1 kind=dev message="任务 <task title> 关键发现：<一句话发现>"`

Announce genuine events, not every log line — a problem worth interrupting the user for, a
phase worth a checkpoint, a finding that changes what happens next. Routine progress bullets
stay silent.

**Finish:** end = the **current system clock** (read it; see Time rules — `Duration` is real
elapsed, the calendar range gets the 30-min display floor; read the `Completed On` start /
Work-log Start back via `notion-fetch` if not in context) → append
`- **End** <ts> — <1–3 line summary of what was done>` and `- **Duration** <Xh Ym>` to the Work
log → set `Completed On` as a **range [start, end]** →
`update_properties`
`{ "Status": "Done", "date:Completed On:start": "<startISO>", "date:Completed On:end": "<endISO>", "date:Completed On:is_datetime": 1 }`
(the block stays at the actual working time — no repositioning for any task type) → update the
day-index row (End, Dur, Status Done) → **(Optional) Announcement** — if enabled:
`phantom_notify level=L1 kind=dev message="任务 <task title> 完成，用时 <Xh Ym>"`
→ Confirm to the user with the link.

**Any other status change** (→ Blocked / Testing / Review / back to Not Started / …):
update Notion + the day index as usual, then announce it too (optional, if enabled) —
`phantom_notify level=L1 kind=dev message="任务 <task title> 状态变为 <中文状态>"`
(e.g. 已阻塞 / 测试中 / 待评审).

**Review approved → remove the task worktree:** explicit user approval of a task in
`Review` (for example, “Review 通过” / “验收通过” / “LGTM”) is the authorization to
remove that task's dedicated Git worktree; do not ask for a second confirmation. Perform
cleanup before marking the task `Done`:

1. Resolve the worktree from the task's Work log/current task context and verify it with
   `git worktree list --porcelain`. The target must be the reviewed task's dedicated
   worktree, normally `<repo-root>/.tree/<task-slug>`; never remove the repository's primary
   worktree or a path whose task/branch association is ambiguous. If the current working
   directory is inside the target, first leave it and run cleanup from the repository root.
2. Check `git status --short` in that worktree. Also verify the reviewed commits are merged
   into the intended integration branch or are preserved on the expected remote branch.
   If there are modified/untracked files, local-only commits, or uncertain integration,
   **do not remove or force-remove** the worktree. Keep the task in `Review`, append a
   blocker to the Work log, announce the problem, and tell the user exactly what remains.
3. For a clean, verified target, run
   `git -C <repo-root> worktree remove <absolute-worktree-path>` without `--force`, then
   `git -C <repo-root> worktree prune`. Verify the path is absent from both the filesystem
   and `git worktree list --porcelain`.
4. Append `- **Worktree removed** <absolute path> — review approved; branch <branch> preserved`
   to the Work log, then complete the normal `Done` status/day-index/announcement update.
   Removing the worktree does **not** authorize deleting its local or remote branch; delete
   a branch only when the user separately asks.

For a task with no dedicated worktree, log that cleanup was not applicable and proceed to
`Done`. A worktree-removal failure must not be hidden or bypassed with raw filesystem deletion.

## Scenario 3 — Drift detection

While one or more tasks are In Progress, continuously sanity-check the work against each
active task's **Goal/scope**. When a substantial new thread appears that isn't serving any
active task's goal (e.g. the user starts fixing an unrelated bug, or scope balloons well past
the stated goal), **pause and ask**, concretely:

> "This looks outside **'<active task>'** (goal: <goal>). Want me to open a new task for
> *<the new thing>* — and should I pause/keep the current one running?"

→ **(Optional) Announcement** — if enabled, `phantom_notify level=L1 kind=dev message="任务 <active task> 似乎跑偏了，目标是 <goal>，需要开新任务吗"`.

- If yes → create the new task (Scenario 1 mechanics; `Status` `Not Started` or, if starting
  it now, run Start), and optionally note the digression in the current task's Work log.
- If no → note it as in-scope (append a Work-log line so the scope decision is recorded) and
  continue.
Only propose a **new task** when the new thread is itself a coarse chunk (~30 min+ of distinct
work); smaller tangents just get a Work-log line under the current task. Don't nag on tiny
tangents; flag genuine scope changes. If unsure, ask rather than reclassify silently.

## Scenario 4 — Concurrency (several tasks at once)

- The day index may show multiple `In Progress` rows — that's expected.
- Every start/log/finish action must be attributed to a **specific** task. When the user's
  instruction is ambiguous and more than one task is active, list the active tasks and ask
  which one (don't guess).
- When logging, name the task in the Work-log entry so parallel timelines stay untangled.
- "What am I working on / status?" → render the day index (active tasks first) as a compact
  table with links, not raw JSON.

---

## Building-block operations

### Add task(s)
Use **Mandatory Git branch at Notion task creation** for every task; a Notion
page without its verified branch is incomplete. Call `notion-create-pages` with the
`data_source_id` parent as above. Example page:
```json
{
  "properties": {
    "Task name": "Wire SSE reconnect backoff",
    "Status": "Not Started",
    "Priority": "High",
    "date:Completed On:start": "2026-07-16",
    "date:Completed On:is_datetime": 0,
    "Tags": "[\"开发\",\"Code\"]",
    "Project": "[\"https://app.notion.com/p/33b616ff95e780fbbe8dcfa7273e3c86\"]"
  },
  "content": "## Goal\nBackoff + auto-resume for the live SSE stream.\n\n## Work log\n"
}
```
Batch multiple via the `pages` array (≤100).

### Update / append to a page
- Properties (status/priority/due/completed): `notion-update-page` `command: "update_properties"`.
- Append a log line: `notion-update-page` `command: "insert_content"`, `position: {"type":"end"}`,
  `content: "- **Start** 2026-07-14 09:12\n"`.

### Find a task the user names (to get `page_id`/url)
`notion-search` scoped to the data source (see below). If several match, list and ask before
mutating. (Local day index is usually faster — check it first.)

## List / review (read-only)

> **Plan note:** this workspace is **not** on a Business plan with Notion AI, so
> `notion-query-data-sources` (SQL **and** view mode) returns 400 `entitlement_required`.
> Don't use it unless the user says they've upgraded.

- **What's active today / "what am I working on"** → render the **local day index** (fastest,
  accurate for today).
- **Find a specific task** → `notion-search`
  `{ query: "<keywords>", query_type: "internal", data_source_url: "collection://3f2616ff-95e7-837b-8444-074b10e56064", page_size: 10 }`.
  Results are semantic/ranked (not exhaustive), span **all projects**, and carry only
  title+url — `notion-fetch` a page for its fields. Only fetch the few that matter.
- **Full, correctly-filtered board** → point the user to the Board view link (grouped by
  Status, filtered to Peppy). Be honest a complete in-chat board needs the Business + AI
  upgrade.
- **If upgraded:** prefer view mode (auto-applies the Peppy filter) with the Board view URL,
  or SQL against the data source, e.g.:
  ```sql
  SELECT "Task name", Status, Priority, "date:Due:start" AS due, url
  FROM "collection://3f2616ff-95e7-837b-8444-074b10e56064"
  WHERE Status IN ('Not Started','Planning','In Progress','Testing','Blocked')
  ORDER BY CASE Priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, due
  ```

## Conventions

- Resolve relative dates ("today/tomorrow/Friday") to concrete `YYYY-MM-DD`; ask if unknown.
- Task names: short, imperative. Detail goes in the page body, not the title.
- Just-do-it for add and single-task updates; **confirm first** for bulk/destructive changes
  (archiving, completing several at once). Always report the task's clickable Notion URL.
- Keep the Notion page and the local day index consistent; Notion wins if they disagree.

## Which project — resolve it, never default

There is **no default project**. Every task must be filed under the project it actually belongs
to, decided from evidence, in this order:

1. **The user names it** ("给 Phantom 加个任务", "Peppy 的雷达…") → that project.
2. **The repo / working directory** the work happens in: `phantom`, `phantom-app`, `phantom-core`,
   `~/.hermes`, `~/Projects/phantom` → **Phantom**; `mmwave-*`, `D:\Projects\peppy`,
   radar / IWRL6844 / dashboard-for-radar work → **Peppy**; `arc*`, posture / MotionCoach → **Arc**.
3. **The task wording** (iOS app / Hermes / 御主 tooling → Phantom; 雷达 / 点云 / 固件 → Peppy;
   健身动作 / 姿态 → Arc).
4. Still ambiguous → **ask** before creating. Do not guess and do not fall back to Peppy.

New project → look it up in the Projects data source (`collection://8aa616ff-95e7-8268-b269-0789ff95e092`)
and use that page URL. Also fix the relation on an existing task if you notice it is filed wrong
(2026-08: a batch of phantom-app tasks had been silently filed under Peppy).

---

## Announcements (optional)

Announcements go through `phantom_notify` (L1 → Feishu; the interruption budget decides
whether now is a good moment, so never bypass it). Opt-in per user: only announce when the
user has said "播报" / "voice on" / "announce", or set a standing preference. When in doubt,
ask once at the start of the day and remember the answer for the day. An announcement is
never in the critical path: if `phantom_notify` reports deferred/denied, the Notion update
still completes and nothing is retried.

Announceable events (see the scenarios): plan created, task started, task finished (研究
完成 for research tasks), any other status transition, problem/blocker hit, phase
completion, key finding/discovery, and drift detection.

---

## Strong reminders (must-do enforcement)

When the user says a task is **strong / mandatory / 强提醒 / 必须要做**, hand it to
`phantom_escalate` — the reminder that insists until confirmed and climbs the interruption
ladder (Feishu → Bark → speaker) under the budget:

```
phantom_escalate action=start
  what="吃药"  message="饭后 30 分钟了，该吃药了。吃了回一个字。"
  level=L1  ladder=[{after:"5m",level:"L2"},{after:"10m",level:"L2"},{after:"20m",level:"L3"}]   # adapt the interval the user asked for
  expires="2h"  confirm_keywords=["完成","吃了","done"]  kind=dev
```

- The user silences it by replying with a confirm keyword (the hook attributes it) or by
  asking you to `phantom_escalate action=cancel`.
- A recurring strong reminder (e.g. weekly cleaning) is a Hermes cron whose prompt runs the
  `start` above — no wrapper scripts, no state files.
- Confirmed / expired reminders show up in the nightly review and the audit view.

The old `enforce.py` daemon (own state file, own TTS + Feishu loop) is kept under `legacy/`
for reference only. Do not run it.
