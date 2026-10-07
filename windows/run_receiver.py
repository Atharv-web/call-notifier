"""Keep the call receiver running until the next local midnight."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import msvcrt
from pathlib import Path
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta


PROJECT_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_DIR / "runtime"
LOCK_PATH = RUNTIME_DIR / "receiver-launcher.lock"
PYTHON_PATH = PROJECT_DIR / "venv" / "Scripts" / "python.exe"
RECEIVER_PATH = Path(__file__).with_name("receiver.py")
PORT = 45832
RESTART_DELAYS = (5, 15, 60)
STABLE_RUN_SECONDS = 300


def build_logger(name: str, path: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            path,
            maxBytes=1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def next_midnight(now: datetime) -> datetime:
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time()).astimezone()


def take_lock():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_PATH.open("a+b")
    lock_file.seek(0)
    if lock_file.read(1) == b"":
        lock_file.seek(0)
        lock_file.write(b"0")
        lock_file.flush()
    lock_file.seek(0)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        check=False,
    )


def port_owner_pid() -> int | None:
    result = powershell(
        f"$endpoint = Get-NetUDPEndpoint -LocalPort {PORT} -ErrorAction SilentlyContinue "
        "| Select-Object -First 1; if ($endpoint) { $endpoint.OwningProcess }"
    )
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def process_command_line(pid: int) -> str:
    result = powershell(
        f"$process = Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\" "
        "-ErrorAction SilentlyContinue; if ($process) { $process.CommandLine }"
    )
    return result.stdout.strip()


def stop_old_receiver(logger: logging.Logger) -> None:
    pid = port_owner_pid()
    if pid is None:
        return
    command_line = process_command_line(pid).lower()
    receiver_name = str(RECEIVER_PATH).lower()
    if receiver_name not in command_line and "receiver.py" not in command_line:
        raise RuntimeError(f"UDP port {PORT} is held by another process (PID {pid}).")
    logger.warning("Stopping old receiver process PID %s.", pid)
    result = powershell(f"Stop-Process -Id {pid} -Force -ErrorAction Stop")
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown error"
        raise RuntimeError(f"Could not stop old receiver PID {pid}: {detail}")
    for _ in range(20):
        if port_owner_pid() is None:
            return
        time.sleep(0.25)
    raise RuntimeError(f"UDP port {PORT} did not become free.")


def copy_output(stream, logger: logging.Logger) -> None:
    try:
        for line in stream:
            logger.info("%s", line.rstrip())
    finally:
        stream.close()


def start_receiver(receiver_logger: logging.Logger) -> tuple[subprocess.Popen[str], threading.Thread]:
    process = subprocess.Popen(
        [str(PYTHON_PATH), str(RECEIVER_PATH), "--quiet"],
        cwd=PROJECT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert process.stdout is not None
    output_thread = threading.Thread(
        target=copy_output,
        args=(process.stdout, receiver_logger),
        name="receiver-output",
        daemon=True,
    )
    output_thread.start()
    return process, output_thread


def stop_receiver(process: subprocess.Popen[str], logger: logging.Logger) -> None:
    if process.poll() is not None:
        return
    logger.info("Stopping receiver PID %s.", process.pid)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("Receiver did not stop in 10 seconds. Forcing it to stop.")
        process.kill()
        process.wait(timeout=5)


def run() -> int:
    lock_file = take_lock()
    if lock_file is None:
        return 0

    launcher_logger = build_logger("call-notifier.launcher", RUNTIME_DIR / "launcher.log")
    receiver_logger = build_logger("call-notifier.receiver", RUNTIME_DIR / "receiver.log")
    process = None
    try:
        if not PYTHON_PATH.is_file():
            raise FileNotFoundError(f"Virtual environment Python is missing: {PYTHON_PATH}")
        if not RECEIVER_PATH.is_file():
            raise FileNotFoundError(f"Receiver is missing: {RECEIVER_PATH}")

        now = datetime.now().astimezone()
        stop_time = next_midnight(now)
        launcher_logger.info("Launcher started. It will stop at %s.", stop_time.isoformat())
        if now.hour < 8:
            launcher_logger.warning("Launcher started outside 08:00 to 00:00.")
        stop_old_receiver(launcher_logger)

        failure_count = 0
        while datetime.now().astimezone() < stop_time:
            started = time.monotonic()
            process, output_thread = start_receiver(receiver_logger)
            launcher_logger.info("Receiver started with PID %s.", process.pid)

            while process.poll() is None and datetime.now().astimezone() < stop_time:
                time.sleep(1)

            if datetime.now().astimezone() >= stop_time:
                stop_receiver(process, launcher_logger)
                output_thread.join(timeout=2)
                process = None
                break

            exit_code = process.returncode
            output_thread.join(timeout=2)
            process = None
            run_seconds = time.monotonic() - started
            if run_seconds >= STABLE_RUN_SECONDS:
                failure_count = 0
            delay = RESTART_DELAYS[min(failure_count, len(RESTART_DELAYS) - 1)]
            failure_count += 1
            launcher_logger.error(
                "Receiver exited unexpectedly with code %s after %.1f seconds. Restarting in %s seconds.",
                exit_code,
                run_seconds,
                delay,
            )
            remaining = (stop_time - datetime.now().astimezone()).total_seconds()
            if remaining > 0:
                time.sleep(min(delay, remaining))

        launcher_logger.info("Launcher stopped at the daily stop time.")
        return 0
    except Exception:
        launcher_logger.exception("Launcher failed.")
        return 1
    finally:
        if process is not None:
            stop_receiver(process, launcher_logger)
        launcher_logger.info("Launcher stopped.")
        lock_file.close()


if __name__ == "__main__":
    sys.exit(run())
