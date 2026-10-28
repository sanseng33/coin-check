# scheduler.py  [desk] box-side schedule for the pure scripts (no cron on this box: PID 1 is tini, no crond).
# watch.py every 10 min (:00 :10 ...), scan.py every 30 min (:00 :30). Logs in logs/, alerts in alerts.log.
# start/stop with ./scheduler.sh start|stop|status. Does NOT survive a box restart; run ./scheduler.sh start again.
import fcntl, os, subprocess, sys, time

DESK = os.path.dirname(os.path.abspath(__file__))
os.chdir(DESK)
os.makedirs("logs", exist_ok=True)
lock = open("logs/scheduler.lock", "w")
try:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)        # one scheduler at a time
except OSError:
    sys.exit("scheduler already running")
lock.write(str(os.getpid())); lock.flush()


def stamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def say(msg):
    print(f"{stamp()} {msg}", flush=True)


def run(script, timeout, log=None):
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, script] if script.endswith(".py") else [script], capture_output=True, text=True, timeout=timeout)
        out, err, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out, err, code = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout", -1
    with open(log or f"logs/{os.path.basename(script)[:-3]}.log", "a") as f:
        f.write(f"--- {stamp()} exit={code} {time.time() - t0:.0f}s\n{out}{err}")
    say(f"{script} exit={code}")
    return out, code


say(f"scheduler start pid={os.getpid()} XAI_API_KEY visible: {'yes' if os.environ.get('XAI_API_KEY') else 'NO'}"
    f" GITHUB_TOKEN visible: {'yes' if os.environ.get('GITHUB_TOKEN') else 'NO'}")
last_scan = time.time()          # first scan at the next :00/:30 window
while True:
    target = (time.time() // 600 + 1) * 600 + 1              # next 10-minute wall-clock boundary
    while time.time() < target:                              # [desk] short sleeps against the wall clock:
        time.sleep(min(20, max(0.5, target - time.time())))  # the box can pause, and one long monotonic sleep drifts
    minute = time.localtime().tm_min
    out, code = run("watch.py", 300)
    if out.strip():                                          # watch.py prints only when something happened
        with open("alerts.log", "a") as f:
            f.writelines(f"{stamp()} WATCH {l}\n" for l in out.strip().splitlines())
    # [desk] also catch up when the box slept through a :00/:30 window
    if minute < 10 or 30 <= minute < 40 or time.time() - last_scan >= 29 * 60:
        run("scan.py", 1200)                                 # check.py writes its own BUY alerts to alerts.log
        last_scan = time.time()
    run("dashboard/export_dashboard.py", 120, "logs/dashboard.log")   # [desk] observability page data
    if os.path.exists("dashboard/publish.conf") and os.environ.get("DESK_PUBLISH", "1") != "0":
        run("dashboard/publish.sh", 180, "logs/publish.log")         # GitHub Pages; DESK_PUBLISH=0 turns it off
