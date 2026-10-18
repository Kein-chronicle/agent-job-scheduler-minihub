# agent-job-scheduler-minihub

**A minimal job hub for supervised agent runs: one job at a time, an operator must be present, results validated, failures auto-pause.**

[![test](https://github.com/Kein-chronicle/agent-job-scheduler-minihub/actions/workflows/test.yml/badge.svg)](https://github.com/Kein-chronicle/agent-job-scheduler-minihub/actions/workflows/test.yml) ![license](https://img.shields.io/badge/license-MIT-blue.svg) ![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

## Why

Unattended agent pipelines fail quietly. This hub only hands out work while a named operator session is registered, runs one job at a time, requires a valid result file from the worker, and pauses a job after repeated failures.

## Install

**As a Claude Code skill** (Claude uses it when the task matches the skill description):

```sh
git clone https://github.com/Kein-chronicle/agent-job-scheduler-minihub.git ~/.claude/skills/operator-supervised-pipeline
```

For a single project, clone into `<project>/.claude/skills/operator-supervised-pipeline` instead, then start a new Claude Code session.

**As plain scripts:**

```sh
git clone https://github.com/Kein-chronicle/agent-job-scheduler-minihub.git
cd agent-job-scheduler-minihub
```

**Requires:** Python 3.10+.

## Quick start

Add jobs and claim one:

```console
$ bash examples/demo.sh
$ minihub add-job blog 60 30
added
[exit 0]

$ minihub add-job video 120
added
[exit 0]

# Nothing runs unless an operator session is registered
$ minihub next
no-operator
[exit 0]

$ minihub operator-start session-A
operator registered; call `next`
[exit 0]

# The first due job is claimed; only one job runs at a time
$ minihub next
{"claimed": "blog", "run_id": "12c07dbe", "status_file": "/private./.demo-tmp/12c07dbe.result.json", "limit_min": 30}
[exit 0]

$ minihub next
busy:blog
[exit 0]
```

The output above is real: it is produced by the files in `examples/`.

## Use it on your own files

```sh
python3 scripts/minihub.py --state hub.json add-job blog 60 30   # name, every N minutes, time limit in minutes
python3 scripts/minihub.py --state hub.json operator-start my-session
python3 scripts/minihub.py --state hub.json next
```

Sample inputs for every file format are in `examples/` and `tests/`; the details are in [SKILL.md](SKILL.md).

## What it checks

- `add-job`, `operator-start`, `next` (claim), `check` (validate the result file), `finish`, `abort`, `amend`.
- A missing result file or a `waiting_human` outcome without a concrete need is invalid.
- Three consecutive failures auto-pause a job; abort does not count as a failure.
- State is one JSON file; `--now` makes it fully testable.

## Limits

- A reference implementation, not a production scheduler.

## Related projects

These solve neighbouring problems; use them when they fit better.

- **cron / Airflow / Temporal**: run unattended; this one refuses to run without a supervising session

## More from the same collection

Small, tested tools that grew out of running AI agents and game/app pipelines for months:

- [**claude-code-memory-lint**](https://github.com/Kein-chronicle/claude-code-memory-lint): Lint a Claude Code memory folder: orphan files, missing files, oversized index lines, and the index lines that are silently cut at load.
- [**claude-code-session-cost**](https://github.com/Kein-chronicle/claude-code-session-cost): Estimate what a Claude Code project cost from its session logs, sub-agents included, with both cache-TTL price assumptions shown.
- [**claude-code-launchd-loops**](https://github.com/Kein-chronicle/claude-code-launchd-loops): Generate a macOS launchd job that runs Claude Code headless on a schedule, from one command.

## Development

```sh
python3 tests/test_minihub.py
```

The tests include inputs that are supposed to be rejected, so a green run also shows the checks can fail. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).

If this saved you a debugging session, a star helps other people find it. Bug reports and failing test cases are even better.

<sub>Keywords: ai-agents, agent-skills, claude-code, claude-skills, job-scheduler, orchestration, automation, supervision</sub>
