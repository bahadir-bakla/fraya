"""External 900-second watchdog for the one parent-approved CPU run.

Does not edit the reviewed trainer/runtime/plan, corpus or previous models.
Launches this Python 3.11 interpreter directly; the child has network socket
connections blocked in memory and runs the exact reviewed --run entry point.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PLAN_SHA = "2f76ef93a36e629d96442c86250856c9f40bff65809f8cd74a3d3c46766e7c51"
AUTHORIZATION = ROOT / "analysis/day2-parent-pretrained-cpu-authorization.json"
authorization_bytes = AUTHORIZATION.read_bytes()
authorization = json.loads(authorization_bytes)
assert authorization["plan_sha256"] == PLAN_SHA
assert authorization["gpu"] is False and authorization["cloud"] is False and authorization["deployment"] is False
assert sys.version_info[:2] == (3, 11)
for name in ["day2_pretrained_head.json", "day2_pretrained_freeze.json"]:
    assert not (ROOT / "integrations/learned-dialogue" / name).exists(), "No rerun permitted"
for name in ["day2-pretrained-baseline.json", "day2-pretrained-baseline-eval-once.json", "day2-pretrained-baseline-grant.json", "day2-pretrained-baseline-watchdog.json"]:
    assert not (ROOT / "analysis" / name).exists(), "No rerun permitted"
grant = "Parent execution approval in analysis/day2-parent-pretrained-cpu-authorization.json under the user's standing explicit training instruction; not a new human click."
trainer = ROOT / "integrations/learned-dialogue/day2_pretrained_train.py"
bootstrap = """import runpy, socket, sys
def deny_network(*args, **kwargs):
    raise RuntimeError('Network connections forbidden in approved offline CPU run')
socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
argv = [sys.executable, "-I", "-B", "-u", "-c", bootstrap, str(trainer), "--run", "--grant", grant, "--plan-sha256", PLAN_SHA]
log_path = ROOT / "analysis/day2-pretrained-baseline-run.log"
log = log_path.open("x", encoding="utf-8", newline="\n")
started_at = datetime.now(timezone.utc).isoformat()
start = time.monotonic()
process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)


def stream_output():
    for line in process.stdout:
        log.write(line)
        log.flush()
        print(line, end="", flush=True)


reader = threading.Thread(target=stream_output, daemon=True)
reader.start()
timed_out = False
print("External watchdog started: one approved CPU --run; hard limit 900 seconds; socket network disabled.", flush=True)
try:
    code = process.wait(timeout=900)
except subprocess.TimeoutExpired:
    timed_out = True
    process.kill()
    code = process.wait(timeout=15)
reader.join(timeout=5)
log.close()
report = {"status": "timeout_killed" if timed_out else "completed" if code == 0 else "failed", "exit_code": code, "timed_out": timed_out, "wall_seconds": time.monotonic() - start, "limit_seconds": 900, "started_at_utc": started_at, "finished_at_utc": datetime.now(timezone.utc).isoformat(), "plan_sha256": PLAN_SHA, "authorization_sha256": hashlib.sha256(authorization_bytes).hexdigest(), "grant": grant, "socket_network_blocked": True, "cpu_only": True, "attempts": 1, "log_path": log_path.relative_to(ROOT).as_posix()}
(ROOT / "analysis/day2-pretrained-baseline-watchdog.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, sort_keys=True), flush=True)
sys.exit(124 if timed_out else code)
