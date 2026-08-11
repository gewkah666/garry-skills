---
name: dev-tasks
description: >
  Run the user's daily development-task workflow on their Notion "Tasks" database
  (default project: Peppy) via the Notion MCP server. Use to: plan the day (create
  today's tasks each morning); start a task (stamp start time, Status→In Progress);
  log progress into the task's Notion page; finish a task (stamp end time + duration,
  Status→Done); detect when work drifts off the task and offer to create a new one;
  and track several tasks running at once. Triggered by /dev-tasks or any add / list /
  start / finish / log / "plan my day" / "what am I working on" request. Every task
  status change — plus mid-task problems/blockers, phase completions and key findings/discoveries — is announced
  by TTS on the study speaker via the miloco-tts skill (default on) — see the "Voice
  notifications" section.
---

# Dev Tasks (Notion) — daily workflow

Manage the user's development tasks in the Notion **Tasks** database using the `notionApi`
MCP server (tools `mcp__plugin_Notion_notion__notion-*`, deferred — load with `ToolSearch`
`select:<tool-name>` before first use each session).

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
| **Peppy** project page (default `Project` relation) | `https://app.notion.com/p/33b616ff95e780fbbe8dcfa7273e3c86` |
| **Projects** data source (to target another project) | `collection://8aa616ff-95e7-8268-b269-0789ff95e092` |

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
- `Project` — relation (JSON array of page URLs). Default `["…33b616ff95e780fbbe8dcfa7273e3c86"]` (Peppy).
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
| Task | Notion URL | Status | Start | End | Dur | Project |
|---|---|---|---|---|---|---|
| Fix SSE reconnect | https://app.notion.com/p/… | In Progress | 09:12 |  |  | Peppy |
```

At the start of a working session, read today's file (if present) to recover the active
set. If it's missing but the user has clearly been mid-work, offer to reconstruct it.

---

## Task granularity — keep it coarse (~30 min+)

One task = one meaningful chunk of work, **roughly half an hour or more**. Do **not** split
work into many small tasks — on the Notion board they blur together and become noise. Group
related small steps under a single task and record the steps as Work-log bullets (or a
checklist in the page body), **not** as separate tasks. If the user's plan lists lots of
micro-items, propose merging them into a handful of ~30-min+ tasks before creating. Err
toward fewer, larger tasks. (This is about task size only — start/end times are still stamped
to the minute.)

## Scenario 1 — Morning planning ("plan my day" / a list of todos)

1. Gather the day's intended tasks from the user (ask briefly if the list is vague). Keep
   them **coarse** (see Task granularity) — if the user lists many micro-items, propose
   merging them into a few ~30-min+ tasks before creating.
2. For **each**, capture a one-line **Goal/scope** — this is the yardstick drift is measured
   against later. Ask for it if the task title alone is ambiguous.
3. Batch-create them with `notion-create-pages`, parent
   `{ type: "data_source_id", data_source_id: "3f2616ff-95e7-837b-8444-074b10e56064" }`,
   each with: `Task name`, `Status: "Not Started"`, `Project: [Peppy]`, `Completed On` = today
   (date only), `Priority` if the user implies one, dev `Tags` when clearly applicable. Put the Goal/scope
   in the page `content` under a `## Goal` heading, and add an empty `## Work log` heading.
4. Create/refresh the local day index with a row per task (Status `Not Started`).
5. Report back the created tasks as a Markdown list with clickable Notion links.
6. **Voice announcement** (default on — see "Voice notifications"): call the miloco-tts
   script to announce the plan, e.g.
   `python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 今天的任务已规划，共 N 个，第一个是 <task 1 title>"`.

## Scenario 2 — Start / execute / finish a task (time-tracked)

**Start:** start time = the current system clock **or** a time the user gives (see Time rules)
→ `notion-update-page` `update_properties`
`{ "Status": "In Progress", "date:Completed On:start": "<YYYY-MM-DDTHH:MM:00>", "date:Completed On:is_datetime": 1 }`
(`Completed On` as a start point) → append to the page `## Work log` `- **Start** <YYYY-MM-DD HH:MM>`
(`insert_content`, `position: end`) → set the day-index row Status `In Progress` and Start time.
→ **Voice announcement** (default on):
`python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 开始任务 <task title>"`.

**During:** append progress notes to the task's `## Work log` as bullets (what was done,
decisions, blockers, links). Each entry should make it obvious which task it belongs to when
several are open. Keep the system of record in Notion; keep the day index in sync for status.
Three kinds of mid-task events also get a **voice announcement** (default on), right after the
Work-log line is written:

- **Problem / blocker hit** — an error that stops progress, a missing credential/permission,
  a failing build, an unexpected dead end:
  `python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 任务 <task title> 遇到问题：<一句话问题>"`
- **Phase completion** — a distinct sub-deliverable done while the task keeps running
  (e.g. 调研完成开始写方案 / 后端通了开始联调):
  `python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 任务 <task title> 阶段性完成：<一句话成果>"`
- **Key finding / discovery** — evidence that changes the picture: a root cause pinned down,
  data that overturns an assumption, an unexpected decisive measurement (e.g. 根因锁定 /
  实测推翻假设 / 关键实证出炉). Announce it the moment it lands, not at task end:
  `python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 任务 <task title> 关键发现：<一句话发现>"`

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
day-index row (End, Dur, Status Done) → **Voice announcement** (default on):
`python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 任务 <task title> 完成，用时 <Xh Ym>"`
(or "研究完成" for a research/investigation task) → Confirm to the user with the link.

**Any other status change** (→ Blocked / Testing / Review / back to Not Started / …):
update Notion + the day index as usual, then announce it too —
`python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 任务 <task title> 状态变为 <中文状态>"`
(e.g. 已阻塞 / 测试中 / 待评审). Every status transition gets a voice reminder.

## Scenario 3 — Drift detection

While one or more tasks are In Progress, continuously sanity-check the work against each
active task's **Goal/scope**. When a substantial new thread appears that isn't serving any
active task's goal (e.g. the user starts fixing an unrelated bug, or scope balloons well past
the stated goal), **pause and ask**, concretely:

> "This looks outside **'<active task>'** (goal: <goal>). Want me to open a new task for
> *<the new thing>* — and should I pause/keep the current one running?"

→ **Voice announcement** (default on):
`python <skills-dir>/miloco-tts/scripts/miloco_tts.py "对书房说 任务 <active task> 似乎跑偏了，目标是 <goal>，需要开新任务吗"`.

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
`notion-create-pages`, `data_source_id` parent as above. Example page:
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

## Another project
Default is Peppy. To file under a different project, find its page URL in the Projects data
source (`collection://8aa616ff-95e7-8268-b269-0789ff95e092`) and use that as `Project`.

---

## Voice notifications (miloco-tts skill) — ON by default: every status change, problem, phase completion, key finding

**Every task status change is announced out loud** on the study speaker: plan created,
start (→ In Progress), finish (→ Done), and any other transition (→ Blocked / Testing /
Review / …) — plus three mid-task events: **a problem/blocker hit**, **a phase completion**
and **a key finding/discovery** (see Scenario 2 "During"). This is the **default behavior — announce without asking**. Suppress only
per "When NOT to voice" below (focus block, explicit "no voice"/"别播", or TTS failure).

### How to call

The script lives in the miloco-tts skill — `~/.claude/skills/miloco-tts/scripts/miloco_tts.py`
(a link to the garry-skills repo; same file everywhere).

```bash
# Windows: python / macOS: python3
python <skills-dir>/miloco-tts/scripts/miloco_tts.py "<natural-language command>"
```

Backend is **Home Assistant** (needs the `HASS_TOKEN` env var — see miloco-tts SKILL.md).
The script auto-detects the target device from keywords like "对书房说", strips the
device + action words, and plays the text via the HA notify play-text entity.

### Default phrases (Chinese — adapt if user prefers English)

| Event | Phrase to speak |
|---|---|
| Plan my day done | "对书房说 今天的任务已规划，共 N 个，第一个是 <task 1 title>" |
| Start task | "对书房说 开始任务 <task title>" |
| Finish task | "对书房说 任务 <task title> 完成，用时 <Xh Ym>" |
| Finish research | "对书房说 研究任务 <task title> 完成，耗时 <Xh Ym>" |
| Problem / blocker hit | "对书房说 任务 <task title> 遇到问题：<一句话问题>" |
| Phase completion | "对书房说 任务 <task title> 阶段性完成：<一句话成果>" |
| Key finding / discovery | "对书房说 任务 <task title> 关键发现：<一句话发现>" |
| Other status change | "对书房说 任务 <task title> 状态变为 <中文状态>"（已阻塞/测试中/待评审/…） |
| Drift detection | "对书房说 任务 <active task> 似乎跑偏了，目标是 <goal>，需要开新任务吗" |

**Fixed target: 书房 (总管 mini) only.** All dev-tasks announcements go to the study
speaker — always phrase as "对书房说 …". Never target 卧室 / 客厅 / 电视 for dev-tasks
voice, even if other devices are available, unless the user explicitly changes this rule.

### When NOT to voice

- During a **silent / focus** block the user has set — skip the announcement and just
  write the Notion update.
- When the user explicitly says "no voice" / "别播" / "silent" — turn off voice for the
  rest of the session.
- When the TTS script fails (HA not reachable, `HASS_TOKEN` missing, device offline) —
  log a one-line warning in the work log and continue silently; never block the
  dev-tasks flow on TTS.

### Failures must never break the workflow

Voice is a nice-to-have. Wrap the TTS invocation so that any failure (network, device
busy, script not found) is logged to the work log as `- ⚠ voice skipped: <reason>` and
the underlying Notion update still completes. Voice is never in the critical path.
