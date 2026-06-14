"""
Simple process supervisor — runs as PID 1.
Starts go2rtc and the intercom Flask API, restarts on crash.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [supervisor] %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

OPTIONS_PATH = "/data/options.json"
GO2RTC_CONFIG = "/data/go2rtc.yaml"


def load_options() -> dict:
    try:
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    except Exception:
        return {
            "call_timeout": 30,
            "max_call_duration": 300,
            "log_level": "info",
        }


def generate_go2rtc_config(opts: dict):
    import yaml  # noqa: PLC0415
    template = "/etc/go2rtc.yaml"
    with open(template) as f:
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


class ManagedProcess:
    def __init__(self, name: str, cmd: list, env: dict, restart_delay: float = 3.0):
        self.name = name
        self.cmd = cmd
        self.env = env
        self.restart_delay = restart_delay
        self._proc: subprocess.Popen | None = None

    def start(self):
        log.info("Starting %s: %s", self.name, " ".join(self.cmd))
        self._proc = subprocess.Popen(
            self.cmd,
            env=self.env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def check_restart(self):
        if not self.alive():
            rc = self._proc.returncode if self._proc else -1
            log.warning("%s exited (rc=%d), restarting in %.0fs", self.name, rc, self.restart_delay)
            time.sleep(self.restart_delay)
            self.start()

    def terminate(self):
        if self._proc and self.alive():
            log.info("Stopping %s (pid=%d)", self.name, self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def main():
    log.info("HA Intercom supervisor starting (pid=%d)", os.getpid())
    opts = load_options()

    generate_go2rtc_config(opts)
    env = build_env(opts)

    processes = [
        ManagedProcess("go2rtc", ["/usr/local/bin/go2rtc", "-config", GO2RTC_CONFIG], env),
        ManagedProcess("intercom-api", [sys.executable, "/app/main.py"], env, restart_delay=5.0),
    ]

    # Start go2rtc first, wait briefly for it to bind
    processes[0].start()
    time.sleep(2)
    processes[1].start()

    def _shutdown(signum, _frame):
        log.info("Signal %d received — shutting down", signum)
        for p in reversed(processes):
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("All services started — monitoring")
    while True:
        for p in processes:
            p.check_restart()
        time.sleep(5)


if __name__ == "__main__":
    main()
