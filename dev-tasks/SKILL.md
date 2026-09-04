---
name: dev-tasks
description: >
  Run the user's daily development-task workflow on their Notion "Tasks" database
  (default project: Peppy) via the Notion MCP server. Use to: plan the day (create
  today's tasks each morning); start a task (stamp start time, Status→In Progress);
  log progress into the task's Notion page; finish a task (stamp end time + duration,
  Status→Done); detect when work drifts off the task and offer to create a new one;
  and track several tasks running at once. Triggered by /dev-tasks or any add / list /
  start / finish / log / "plan my day" / "what am I working on" request. Optional
  TTS voice notifications via the miloco-tts skill (xiaomi speakers / TV) — see the
  "Voice notifications" section.
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
- **Done** (finished): `Completed On` = a **range [start, end]** — both datetimes to the
  minute, `end` **estimated from the workload** with **`end − start` ≥ 30 min** (minimum
  block, so tasks don't blur on the calendar); use real elapsed time if longer. State the
  chosen block/duration in one line so the user can override.
    - **Research / investigation task** → place the block **later** (default around **18:00**,
      or ask) so the calendar doesn't read as "just finished". See memory
      `dev-tasks-research-completion-time`.

Also mirror the block in the page `## Work log` (`- **Start** …`, `- **End** … — summary`,
`- **Duration** …`) and the day index — honest prose that stays put even if a research task's
calendar-facing `Completed On` is nudged later. Read the clock with PowerShell
`Get-Date -Format 'yyyy-MM-dd HH:mm'` or Bash `date '+%Y-%m-%d %H:%M'` (local timezone).
Concurrent tasks' blocks may overlap — that's fine.

## "What's active now" — ask Notion, keep no local index

Hermes' Notion MCP can query the data source, so the active set is always a query, never a
file: filter the Tasks data source `3f2616ff-95e7-837b-8444-074b10e56064` by
`Status = In Progress` (and `Project` = Peppy unless told otherwise). Today's plan is the same
query with `Completed On` on today's date. There is no second copy of the truth anywhere.

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
4. Report back the created tasks as a Markdown list with clickable Notion links.
5. **(Optional) Announcement** — if the user has announcements on (see "Announcements"),
   `phantom_notify level=L1 kind=dev message="今天的任务已规划，共 N 个，第一个是 <task 1 title>"`.

## Scenario 2 — Start / execute / finish a task (time-tracked)

**Start:** start time = the current system clock **or** a time the user gives (see Time rules)
→ `notion-update-page` `update_properties`
`{ "Status": "In Progress", "date:Completed On:start": "<YYYY-MM-DDTHH:MM:00>", "date:Completed On:is_datetime": 1 }`
(`Completed On` as a start point) → append to the page `## Work log` `- **Start** <YYYY-MM-DD HH:MM>`
(`insert_content`, `position: end`).
→ **(Optional) Announcement** — if enabled, `phantom_notify level=L1 kind=dev message="开始任务 <task title>"`.

**During:** append progress notes to the task's `## Work log` as bullets (what was done,
decisions, blockers, links). Each entry should make it obvious which task it belongs to when
several are open. Notion is the only system of record.

**Finish:** derive the end per **Time rules** (end = start + workload effort, ≥30 min; read the
`Completed On` start / Work-log Start back via `notion-fetch` if not in context) → append
`- **End** <ts> — <1–3 line summary of what was done>` and `- **Duration** <Xh Ym>` to the Work
log → set `Completed On` as a **range [start, end]** →
`update_properties`
`{ "Status": "Done", "date:Completed On:start": "<startISO>", "date:Completed On:end": "<endISO>", "date:Completed On:is_datetime": 1 }`
(for a **research/investigation** task, place the block **later**, default ~18:00) →
**(Optional) Announcement** — if enabled, `phantom_notify level=L1 kind=dev message="任务 <task title> 完成，用时 <Xh Ym>"`
→ Confirm to the user with the link.

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

## Announcements (optional)

Announcements go through `phantom_notify` (L1 → Feishu; the interruption budget decides
whether now is a good moment, so never bypass it). Opt-in per user: only announce when the
user has said "播报" / "voice on" / "announce", or set a standing preference. When in doubt,
ask once at the start of the day and remember the answer for the day. An announcement is
never in the critical path: if `phantom_notify` reports deferred/denied, the Notion update
still completes and nothing is retried.

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
