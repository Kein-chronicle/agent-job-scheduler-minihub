import json, os, subprocess, sys, tempfile
H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "minihub.py")
d = tempfile.mkdtemp(); S = os.path.join(d, "s.json"); ok = True
def hub(*a, now="2026-01-01T09:00:00+00:00"):
    p = subprocess.run([sys.executable, H, "--state", S, "--now", now, *a], capture_output=True, text=True); return p.returncode, p.stdout.strip()
def expect(n, got, want, contains=False):
    global ok; g = (want in got) if contains else got == want; ok &= g; print(("ok   " if g else "FAIL ") + f"{n}: {got}")
def claim(now):
    rc, o = hub("next", now=now); return json.loads(o) if o.startswith("{") else o

hub("add-job", "blog", "60", "30"); hub("add-job", "video", "120")
expect("nothing runs without an operator", hub("next")[1], "no-operator")
hub("operator-start", "session-A")
expect("second operator refused without --force", hub("operator-start", "session-B")[1], "refused", True)
c = claim("2026-01-01T09:00:00+00:00"); expect("first due job claimed", c["claimed"], "blog")
expect("only one job at a time (busy)", hub("next", now="2026-01-01T09:01:00+00:00")[1], "busy:blog")
# worker forgets the result file => failure, not silent success
rc, o = hub("check", c["run_id"]); expect("missing result file is invalid", json.loads(o)["valid"], False)
json.dump({"outcome": "waiting_human", "summary": "login", "waiting": []}, open(c["status_file"], "w"))
expect("waiting_human without a concrete need is invalid", json.loads(hub("check", c["run_id"])[1])["valid"], False)
json.dump({"outcome": "done", "summary": "published a post"}, open(c["status_file"], "w"))
expect("valid result accepted", json.loads(hub("check", c["run_id"])[1])["valid"], True)
expect("finish records outcome", hub("finish", c["run_id"])[1], "recorded done")
c2 = claim("2026-01-01T09:05:00+00:00"); expect("next claims the other due job", c2["claimed"], "video")
expect("abort does not count as failure", hub("abort", c2["run_id"], "user stopped")[1], "cancelled", True)
expect("not due again before its interval", hub("next", now="2026-01-01T09:30:00+00:00")[1], "idle")

# three consecutive failures auto-pause a job, amend() reverses a wrong record and keeps history
msgs = []
for i in range(6):                     # two jobs alternate, so each accumulates 3 consecutive failures
    t = f"2026-01-{2+i:02d}T10:00:00+00:00"; cc = claim(t)
    json.dump({"outcome": "failed", "summary": "gate blocked"}, open(cc["status_file"], "w")); msgs.append(hub("finish", cc["run_id"])[1])
r = " | ".join(msgs)
expect("3rd consecutive failure pauses the job", r, "JOB PAUSED", True)
expect("both jobs paused => nothing is claimed", hub("next", now="2026-01-20T10:00:00+00:00")[1], "idle")
expect("amend keeps history and unpauses", hub("amend", cc["run_id"], "progressed", "validator mismatch, not worker fault")[1], "amended", True)
st = json.loads(hub("status")[1]); expect("amended job is unpaused", st["jobs"][cc["claimed"]]["paused"], False)
hub("operator-stop"); expect("operator stop halts everything", hub("next", now="2026-02-01T00:00:00+00:00")[1], "no-operator")
# robustness found in review: malformed result files, unknown ids, double finish, bad amend
hub("add-job", "robust", "5"); hub("operator-start", "r", "--force"); cx = claim("2026-02-01T09:00:00+00:00")
if isinstance(cx, dict):
    json.dump([], open(cx["status_file"], "w"))
    expect("a result that is not an object is invalid, not a crash", json.loads(hub("check", cx["run_id"])[1])["valid"], False)
    json.dump({"outcome": "waiting_human", "summary": "s", "waiting": ["x"]}, open(cx["status_file"], "w"))
    expect("waiting entries that are not objects are invalid", json.loads(hub("check", cx["run_id"])[1])["valid"], False)
    json.dump({"outcome": "done", "summary": "ok"}, open(cx["status_file"], "w")); hub("finish", cx["run_id"])
    rc, o = hub("finish", cx["run_id"]); expect("a second finish is refused", rc, 2)
    rc, o = hub("amend", cx["run_id"], "garbage", "why"); expect("amend rejects an unknown outcome", rc, 2)
rc, o = hub("check", "nosuchrun"); expect("unknown run id is exit 2, not a traceback", (rc, "Traceback" in o), (2, False))
rc, o = hub("add-job"); expect("missing arguments are exit 2", rc, 2)
# --- second review round
hub("add-job", "rb2", "5"); hub("operator-start", "r2", "--force"); c3 = claim("2026-03-01T09:00:00+00:00")
if isinstance(c3, dict):
    json.dump({"outcome": ["done"], "summary": "x"}, open(c3["status_file"], "w"))
    rc, o = hub("check", c3["run_id"]); expect("an outcome that is a list is invalid, not a TypeError", (rc, json.loads(o)["valid"] if o.startswith("{") else None), (0, False))
    rc, o = hub("amend", c3["run_id"], "done", "x"); expect("a still-running run cannot be amended", rc, 2)
    rc, o = hub("next", now="2026-03-01T12:00:00+00:00"); expect("an overdue running run is called out", "OVERDUE" in o, True)
    json.dump({"outcome": "failed", "summary": "x"}, open(c3["status_file"], "w")); hub("finish", c3["run_id"])
    rc, o = hub("amend", c3["run_id"], "done", ""); expect("amend needs a non-empty reason", rc, 2)
rc, o = hub("add-job", "rb2", "5"); expect("re-adding an existing job is refused (it would wipe its history)", rc, 2)
bad_state = os.path.join(d, "bad-state.json"); open(bad_state, "w").write("{garbage")
p = subprocess.run([sys.executable, H, "--state", bad_state, "status"], capture_output=True, text=True); expect("a corrupt state file is exit 2 and is not overwritten", (p.returncode, open(bad_state).read()), (2, "{garbage"))
p = subprocess.run([sys.executable, H, "--state", S, "--now", "yesterday", "status"], capture_output=True, text=True); expect("a bad --now is exit 2", p.returncode, 2)
# Simultaneous CLI callers must serialize the entire state transaction.
S = os.path.join(d, "concurrent.json")
hub("add-job", "synthetic", "60"); hub("operator-start", "test-operator")
children = [subprocess.Popen([sys.executable, H, "--state", S, "next"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(12)]
outputs = [p.communicate(timeout=20) for p in children]
expect("concurrent next succeeds without corrupt state", [p.returncode for p in children], [0]*12)
expect("concurrent next issues exactly one claim", sum('"claimed"' in out for out, _ in outputs), 1)
expect("remaining concurrent callers see busy", sum(out.strip() == 'busy:synthetic' for out, _ in outputs), 11)
expect("exactly one run persisted", len(json.load(open(S))["runs"]), 1)
before = os.stat(S).st_mtime_ns; hub("status")
expect("read-only status does not rewrite state", os.stat(S).st_mtime_ns, before)
linked = os.path.join(d, "linked.json"); os.symlink(S, linked)
r = subprocess.run([sys.executable, H, "--state", linked, "status"], capture_output=True, text=True)
expect("linked state is refused", r.returncode, 2)
import shutil
shutil.rmtree(d)
sys.exit(0 if ok else 1)

