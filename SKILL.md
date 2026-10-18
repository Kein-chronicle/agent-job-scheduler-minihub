---
name: operator-supervised-pipeline
description: Run several recurring AI production jobs (content, builds, releases) through ONE supervising agent session that claims a job at a time, delegates to a worker, reads the result, fixes the pipeline when it breaks, and records it. Use when headless scheduled agents keep repeating the same failure, when you need a result contract and single-job-at-a-time discipline, when workers overlap or spawn sub-agents that overwrite each other, or when a job keeps failing because the validator (not the worker) is wrong. Includes a tiny reference hub.
---

# operator-supervised-pipeline

**Why it exists:** launching a fresh headless agent from cron for each run means no context, no ability to
cope with exceptions and no authority to fix the process, so the same problem comes back every day. So: one **operator**
session (a live agent) does the supervising; the **hub** (plain code) only judges and records.

- No operator registered => **nothing runs.** (Be explicit about it.)
- One job at a time. `next` returns `claimed | busy | idle | paused | no-operator`.
- Priority: due production first, then checks/audits; oldest slot first within a kind. Never interrupt a running job.

## Roles

| Hub (code) | Operator (agent session) | Worker (agent, sub-process) |
|---|---|---|
| what is due, switches/gates, result recording, notifications, human-wait list, status UI | claim -> delegate -> supervise -> fix the factory when it breaks -> check -> finish | do the job per its prompt file, write the result file |

## Result contract (worker must write JSON before ending)

`outcome: done | progressed | nothing_to_do | waiting_human | failed`, `summary`, `outputs[]`, `waiting[{item, need, since}]`,
`blocked_by` (gate id, so the hub can detect an over-blocking gate). A missing or malformed file = failure.
`waiting_human` is only for **genuinely external input** (a biometric prompt, an OS password, a physical device, an ambiguous account) and needs a concrete `need`. If the project documents a login procedure, the worker performs it itself.
The fact that the hub handed the job over **is** the permission to run it.

## Operator procedure per claim

1. `next`. `busy` -> check the worker, kill + abort past `limit_min`.
2. Delegate: background sub-agent or background shell process. **Never two workers for one job** ("background work
   still running" means it is not finished). Stop = hub `abort` AND kill the process group.
3. Supervise: read the summary + result file only (operator context cost grows with the square of conversation length).
   If the failure is a gate/tool/prompt defect: **fix the factory (tests, commit), re-instruct the worker**, within the time cap.
   A repeat of the same exception => add a prevention rule/code and write it in that factory's handoff/gates doc.
4. **`check <run>` before `finish`.** Decide whether the worker erred or the hub's validator disagrees. Finishing a
   validator mismatch as a worker failure counts toward auto-pause (3 consecutive failures). If a wrong record already
   exists: `amend` (original is kept in history) and re-enable the job.
5. `finish`, then immediately `next`. Nothing due? Schedule the next slot (below).

## Scheduling traps

- A recurring schedule inside a session can drift or expire. Prefer a **chain of one-shot schedules**: when idle, compute the next due slot and register a
  single timer just after it, keeping the recurring one only as a safety net. Re-create schedules when the timetable changes.
- A worker finishing doesn't wake the operator. Add a 1-minute watcher that only *notifies the registered session* on
  result-file-written or time-cap-hit (once per run), never starting/finishing anything itself.
- Time budget: the last N minutes of each slot are reserved for evidence/handoff. Save progress before the cap.

## Worker rules worth copying

- Workers must **not spawn sub-agents**: children inherit write permission; "read-only" in the prompt doesn't bind them
  (parallel sub-agents can overwrite each other's result files and the shared tree). If needed, a read-only explorer type only.
- Don't bypass a blocked task with a different one. If material is missing => `nothing_to_do`.
- Finish by committing and pushing every repository the job touched (never force-push; skip repos without a remote).
- Don't claim a human reviewed something. Record the reviewer role and what was actually observed.
- Keep one shared browser/automation tool at a time; if a login looks missing, count browser instances first.
- A human's pause overrides everything and only a human resumes: the reference hub has `pause` and `resume`, and `unpause-job NAME` for one job.

## Reference hub

`scripts/minihub.py` implements: add-job, operator-start/stop (second operator refused without `--force`),
`next` (single job, due-by-interval, oldest first), `check`, `finish` (consecutive-failure auto-pause at 3),
`abort` (not a failure), `amend` (keeps history), `pause` / `resume` (whole hub), `unpause-job` (one job). A run can be finished or aborted only while it is `running`; unknown run ids and malformed result files are reported, never crash the hub. `python3 tests/test_minihub.py` covers the contract.
Real hubs add: gates/switches, notifications, web UI, model profiles (one config file picks the model per job;
switch profile for cost, auto-escalate on quality drops).

Concurrent CLI calls are serialized with a separate, stable state-file lock across the entire read/modify/write transaction. State writes use atomic replacement; status/check do not rewrite state. Requires a local filesystem with working POSIX flock (Linux/macOS), and a trusted operator-owned state directory. Symlink state files are rejected. This is coordination, not authentication or a sandbox for untrusted workers.
