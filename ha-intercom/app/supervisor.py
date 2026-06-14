"""
Simple process supervisor — runs as PID 1.
Starts go2rtc and the intercom Flask API, restarts on crash.
Implements watchdog: if the health endpoint stops responding, restarts the API.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [supervisor] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"
GO2RTC_CONFIG = "/data/go2rtc.yaml"
HEALTH_URL = "http://localhost:8099/health"
GO2RTC_HEALTH_URL = "http://localhost:1984/api"
WATCHDOG_INTERVAL = 30   # seconds between health checks
WATCHDOG_FAILURES = 3    # consecutive failures before restart


def load_options() -> dict:
    try:
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"call_timeout": 30, "max_call_duration": 300, "log_level": "info"}


def generate_go2rtc_config(opts: dict):
    import yaml
    with open("/etc/go2rtc.yaml") as f:
        config = yaml.safe_load(f)
    config.setdefault("log", {})["level"] = opts.get("log_level", "info")
    with open(GO2RTC_CONFIG, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    log.info("go2rtc config written to %s", GO2RTC_CONFIG)


def build_env(opts: dict) -> dict:
    env = os.environ.copy()
    env.update({
        "HA_TOKEN": env.get("SUPERVISOR_TOKEN", ""),
        "HA_URL": "http://supervisor/core",
        "GO2RTC_URL": "http://localhost:1984",
        "CALL_TIMEOUT": str(opts.get("call_timeout", 30)),
        "MAX_CALL_DURATION": str(opts.get("max_call_duration", 300)),
        "LOG_LEVEL": opts.get("log_level", "info"),
        "OPTIONS_PATH": OPTIONS_PATH,
    })
    return env


def http_ok(url: str, timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


class ManagedProcess:
    def __init__(self, name: str, cmd: list, env: dict, restart_delay: float = 3.0):
        self.name = name
        self.cmd = cmd
        self.env = env
        self.restart_delay = restart_delay
        self._proc: subprocess.Popen | None = None
        self._restarts = 0

    def start(self):
        log.info("Starting %s: %s", self.name, " ".join(self.cmd))
        self._proc = subprocess.Popen(
            self.cmd, env=self.env, stdout=sys.stdout, stderr=sys.stderr,
        )

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def restart(self, reason: str = "crash"):
        self._restarts += 1
        rc = self._proc.returncode if self._proc else -1
        log.warning(
            "%s %s (rc=%s, restart #%d), waiting %.0fs",
            self.name, reason, rc, self._restarts, self.restart_delay,
        )
        if self._proc and self.alive():
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        time.sleep(self.restart_delay)
        self.start()

    def check_alive(self):
        if not self.alive():
            self.restart("exited unexpectedly")

    def terminate(self):
        if self._proc and self.alive():
            log.info("Stopping %s (pid=%d)", self.name, self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


class Watchdog:
    """Monitors the Flask API via HTTP health check and restarts if unhealthy."""

    def __init__(self, url: str, interval: int, max_failures: int, target: ManagedProcess):
        self._url = url
        self._interval = interval
        self._max_failures = max_failures
        self._target = target
        self._failures = 0
        self._last_check = 0.0
        self._ready = False
        self._ready_at: float | None = None

    def mark_ready(self):
        if not self._ready:
            self._ready = True
            self._ready_at = time.time()
            log.info("Watchdog armed for %s", self._target.name)

    def tick(self):
        now = time.time()
        if now - self._last_check < self._interval:
            return
        self._last_check = now

        if not self._ready:
            # Wait until the process has been up for at least 15s before checking
            if self._target.alive() and self._target._proc:
                if now - (self._ready_at or now) > 15 or self._ready_at is None:
                    self.mark_ready()
            return

        if http_ok(self._url):
            if self._failures > 0:
                log.info("Watchdog: %s recovered", self._target.name)
            self._failures = 0
        else:
            self._failures += 1
            log.warning(
                "Watchdog: %s health check failed (%d/%d)",
                self._target.name, self._failures, self._max_failures,
            )
            if self._failures >= self._max_failures:
                log.error("Watchdog: restarting %s after %d failures", self._target.name, self._failures)
                self._failures = 0
                self._target.restart("watchdog-triggered")


def main():
    log.info("HA Intercom supervisor starting (pid=%d)", os.getpid())
    opts = load_options()
    generate_go2rtc_config(opts)
    env = build_env(opts)

    go2rtc = ManagedProcess(
        "go2rtc",
        ["/usr/local/bin/go2rtc", "-config", GO2RTC_CONFIG],
        env,
        restart_delay=3.0,
    )
    api = ManagedProcess(
        "intercom-api",
        [sys.executable, "/app/main.py"],
        env,
        restart_delay=5.0,
    )

    go2rtc.start()
    time.sleep(2)
    api.start()

    watchdog = Watchdog(HEALTH_URL, WATCHDOG_INTERVAL, WATCHDOG_FAILURES, api)
    # Give the API time to start before arming watchdog
    time.sleep(5)
    watchdog.mark_ready()

    def _shutdown(signum, _frame):
        log.info("Signal %d received — shutting down", signum)
        for p in [api, go2rtc]:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("All services started — monitoring (watchdog every %ds)", WATCHDOG_INTERVAL)
    while True:
        go2rtc.check_alive()
        api.check_alive()
        watchdog.tick()
        time.sleep(5)


if __name__ == "__main__":
    main()
