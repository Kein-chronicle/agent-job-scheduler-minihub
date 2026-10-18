#!/usr/bin/env python3
"""minihub: a tiny job hub for an OPERATOR-SUPERVISED pipeline. The hub only judges and records;
an operator (a live agent session) claims one job at a time, delegates it to a worker, supervises, then finishes it.
Nothing runs without a registered operator.
state file = JSON. usage: minihub.py --state S.json <cmd> [args]   (use --now ISO for deterministic tests)
cmds: add-job NAME EVERY_MIN [LIMIT_MIN] | operator-start SESSION [--force] | operator-stop | next
      check RUN_ID | finish RUN_ID | abort RUN_ID REASON | amend RUN_ID OUTCOME REASON | status | pause | resume | unpause-job NAME"""
import argparse, json, os, sys, uuid, fcntl, tempfile, stat
from datetime import datetime, timedelta, timezone

OUTCOMES = {"done", "progressed", "nothing_to_do", "waiting_human", "failed"}
FAILURE_LIMIT = 3      # consecutive failures that auto-pause a job

class StateError(Exception): pass

def load(p):
    if not os.path.exists(p): return {"jobs": {}, "runs": {}, "operator": None, "paused": False}
    try:
        s = json.load(open(p)); assert isinstance(s, dict) and all(k in s for k in ("jobs", "runs", "operator", "paused"))
        return s
    except (OSError, ValueError, AssertionError): raise StateError(f"the state file {p} is unreadable or not a minihub state file: refusing to continue (and to overwrite it)")

def save(p, s):
    fd, temporary = tempfile.mkstemp(prefix=".minihub-", dir=os.path.dirname(os.path.abspath(p)))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(s, f, indent=1); f.flush(); os.fsync(f.fileno())
        os.replace(temporary, p)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
def parse(t): return datetime.fromisoformat(t)

def validate_result(path):
    """The result contract. Missing/invalid file is a FAILURE, never silently accepted."""
    try: r = json.load(open(path))
    except Exception as e: return False, f"result file unreadable: {e}"
    if not isinstance(r, dict): return False, "result must be a JSON object"
    if not isinstance(r.get("outcome"), str) or r.get("outcome") not in OUTCOMES: return False, f"outcome must be one of {sorted(OUTCOMES)}"
    if not str(r.get("summary", "")).strip(): return False, "summary required"
    if r["outcome"] == "waiting_human":
        w = r.get("waiting") or []
        if not isinstance(w, list) or not w or not all(isinstance(x, dict) and x.get("item") and x.get("need") for x in w): return False, "waiting_human needs waiting[{item, need}] - only genuine external input"
    return True, "ok"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--state", required=True); ap.add_argument("--now")
    ap.add_argument("cmd"); ap.add_argument("args", nargs="*"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    try: now = parse(a.now) if a.now else datetime.now(timezone.utc)
    except ValueError: print("error: --now must be an ISO 8601 timestamp with a UTC offset, e.g. 2026-01-01T09:00:00+00:00"); return 2
    if now.tzinfo is None: print("error: --now needs a UTC offset, e.g. +00:00"); return 2
    # Keep the lock inode stable while the JSON state is atomically replaced.
    a.state = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(a.state))), os.path.basename(a.state))
    try:
        if os.path.islink(a.state): raise StateError("linked state files are not supported")
        fd = os.open(a.state + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode): raise StateError("lock must be a regular file")
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            s = load(a.state)
            try: return dispatch(a, s, a.cmd, a.args, now)
            except (KeyError, IndexError, ValueError):
                print(f"error: unknown job/run id or missing/invalid arguments for '{a.cmd}' (see --help)"); return 2
    except (OSError, StateError) as e:
        print(f"error: {e}"); return 2

def dispatch(a, s, c, A, now):
    out = None
    if c == "add-job":
        if A[0] in s["jobs"]: print(f"error: job '{A[0]}' already exists (re-adding would reset its history); remove it from the state file by hand if you really mean to"); return 2
        s["jobs"][A[0]] = {"every_min": int(A[1]), "limit_min": int(A[2]) if len(A) > 2 else 60, "last_start": None, "fails": 0, "paused": False}; out = "added"
    elif c == "operator-start":
        if s["operator"] and not a.force: out = f"refused: operator '{s['operator']}' already registered (use --force after asking the user)"; print(out); return 1
        s["operator"] = A[0]; out = "operator registered; call `next`"
    elif c == "operator-stop": s["operator"] = None; out = "operator stopped: nothing will run now"
    elif c == "resume": s["paused"] = False; out = "resumed (only when the human asked)"
    elif c == "next":
        if not s["operator"]: out = "no-operator"
        elif s["paused"]: out = "paused"
        else:
            busy = [r for r, v in s["runs"].items() if v["state"] == "running"]
            if busy:
                run_ = s["runs"][busy[0]]; over = now - parse(run_["started"]) > timedelta(minutes=run_["limit_min"])
                out = f"busy:{run_['job']}" + (f" (OVERDUE: over its {run_['limit_min']} min limit; the operator should abort run {busy[0]})" if over else "")
            else:
                due = []
                for n, j in s["jobs"].items():
                    if j["paused"]: continue
                    ls = parse(j["last_start"]) if j["last_start"] else None
                    if ls is None or now - ls >= timedelta(minutes=j["every_min"]): due.append((ls or datetime.min.replace(tzinfo=timezone.utc), n))
                if not due: out = "idle"
                else:
                    due.sort(); n = due[0][1]; rid = uuid.uuid4().hex[:8]; j = s["jobs"][n]; j["last_start"] = now.isoformat()
                    sf = os.path.join(os.path.dirname(os.path.abspath(a.state)), f"{rid}.result.json")
                    s["runs"][rid] = {"job": n, "state": "running", "started": now.isoformat(), "status_file": sf, "limit_min": j["limit_min"]}
                    out = json.dumps({"claimed": n, "run_id": rid, "status_file": sf, "limit_min": j["limit_min"]})
    elif c == "check":
        ok, why = validate_result(s["runs"][A[0]]["status_file"]); out = json.dumps({"valid": ok, "why": why})
    elif c == "finish":
        r = s["runs"][A[0]]
        if r["state"] != "running": print(f"error: run {A[0]} is already '{r['state']}'; use amend to correct a record"); return 2
        ok, why = validate_result(r["status_file"]); j = s["jobs"][r["job"]]
        if not ok:
            j["fails"] += 1; r["state"] = "failed"; r["why"] = why
        else:
            res = json.load(open(r["status_file"])); r["state"] = res["outcome"]
            j["fails"] = j["fails"] + 1 if res["outcome"] == "failed" else 0
        if j["fails"] >= FAILURE_LIMIT: j["paused"] = True; out = f"recorded {r['state']}; JOB PAUSED after {j['fails']} consecutive failures"
        else: out = f"recorded {r['state']}" + ("" if ok else f" ({why})")
    elif c == "abort":
        r = s["runs"][A[0]]
        if r["state"] != "running": print(f"error: run {A[0]} is already '{r['state']}'"); return 2
        r["state"] = "cancelled"; r["why"] = A[1]; out = "cancelled (does not count as a failure)"
    elif c == "amend":
        if A[1] not in OUTCOMES | {"cancelled"}: print(f"error: outcome must be one of {sorted(OUTCOMES | {'cancelled'})}"); return 2
        if len(A) < 3 or not str(A[2]).strip(): print("error: amend needs a non-empty reason (it rewrites a record)"); return 2
        r = s["runs"][A[0]]
        if r["state"] == "running": print("error: a run that is still running cannot be amended: finish or abort it first"); return 2
        j = s["jobs"][r["job"]]; was_fail = r["state"] in ("failed",)
        r.setdefault("amendments", []).append({"was": r["state"], "now": A[1], "reason": A[2]})
        r["state"] = A[1]
        if was_fail and A[1] != "failed":                                   # correcting a wrong failure undoes only the failure that record had added
            j["fails"] = max(0, j["fails"] - 1)
            if j["paused"] and j["fails"] < FAILURE_LIMIT: j["paused"] = False    # and re-enables the job only if that was what paused it
        out = "amended (original kept in history)"
    elif c == "pause": s["paused"] = True; out = "hub paused: `next` returns 'paused' until `resume`"
    elif c == "unpause-job": j = s["jobs"][A[0]]; j["paused"] = False; j["fails"] = 0; out = f"job {A[0]} re-enabled"
    elif c == "status": out = json.dumps({"operator": s["operator"], "paused": s["paused"], "jobs": {n: {"fails": j["fails"], "paused": j["paused"]} for n, j in s["jobs"].items()}})
    else: print(__doc__); return 2
    if c not in {"status", "check"}: save(a.state, s)
    print(out); return 0

if __name__ == "__main__":
    sys.exit(main())
