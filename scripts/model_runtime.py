#!/usr/bin/env python3
"""Own the llama-server lifecycle for writer and verifier phases.

Only one model is resident at a time. The Mac profile is one slot with 16k
total context; the Kaggle profile is two slots with 32k total context. The
manager starts the requested server, waits for /health, and always stops the
child it started. It never kills an unrelated process on the port.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = ROOT / "out" / "runtime"
DEFAULT_MODEL_ROOT = Path.home() / "Documents" / "models"
WRITER_MODEL = "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
VERIFIER_MODEL = "Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"

MAC_PROFILE = {"slots": 1, "context": 16384}
KAGGLE_PROFILE = {"slots": 2, "context": 32768}


@dataclass
class ServerProfile:
    role: str
    model_path: Path
    port: int = 8080
    context: int = 16384
    slots: int = 1
    binary: str = ""
    state_dir: Path = DEFAULT_STATE
    log_path: Path | None = None
    cache_ram: int = 4096
    threads: int = 6
    extra_args: list[str] = field(default_factory=list)

    def command(self) -> list[str]:
        binary = self.binary or shutil.which("llama-server")
        if not binary:
            raise FileNotFoundError(
                "llama-server not found; install llama.cpp or set LLAMA_SERVER_BIN")
        args = [
            binary,
            "-m", str(self.model_path),
            "-c", str(self.context),
            "-ngl", "99",
            "-t", str(self.threads),
            "-fa", "on",
            "-ub", "1024",
            "-b", "1024",
            "--port", str(self.port),
            "-np", str(self.slots),
            "--metrics",
            "--context-shift",
            "--kv-unified",
        ]
        if self.cache_ram:
            args += ["--cache-ram", str(self.cache_ram)]
        args += self.extra_args
        return args

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def state_path(self) -> Path:
        return self.state_dir / f"{self.role}.json"

    @property
    def default_log_path(self) -> Path:
        return self.state_dir / f"{self.role}.log"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class LlamaServer:
    def __init__(self, profile: ServerProfile):
        self.profile = profile
        self.process: subprocess.Popen | None = None
        self._log = None
        self._owned = False

    def start(self, timeout: float = 180.0) -> "LlamaServer":
        profile = self.profile
        if not profile.model_path.is_file():
            raise FileNotFoundError(f"model not found: {profile.model_path}")
        if _port_open(profile.port):
            raise RuntimeError(
                f"port {profile.port} is already in use; refusing to kill a "
                "process this manager did not start")
        profile.state_dir.mkdir(parents=True, exist_ok=True)
        log_path = profile.log_path or profile.default_log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = log_path.open("w", encoding="utf-8")
        command = profile.command()
        self.process = subprocess.Popen(
            command,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._owned = True
        profile.state_path.write_text(json.dumps({
            "role": profile.role,
            "pid": self.process.pid,
            "port": profile.port,
            "context": profile.context,
            "slots": profile.slots,
            "model": str(profile.model_path),
            "base_url": profile.base_url,
            "started": time.time(),
        }, indent=2) + "\n", encoding="utf-8")
        try:
            self.wait_healthy(timeout=timeout)
        except BaseException:
            self.stop()
            raise
        return self

    def wait_healthy(self, timeout: float = 180.0) -> None:
        deadline = time.monotonic() + timeout
        url = self.profile.base_url + "/health"
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"llama-server exited with {self.process.returncode}; "
                    f"see {self.profile.log_path or self.profile.default_log_path}")
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(1)
        raise TimeoutError(
            f"llama-server for {self.profile.role} did not become healthy "
            f"within {timeout:.0f}s")

    def stop(self, timeout: float = 30.0) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        if self._log is not None:
            self._log.flush()
            self._log.close()
            self._log = None
        if self._owned:
            try:
                self.profile.state_path.unlink()
            except FileNotFoundError:
                pass
        self.process = None
        self._owned = False

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False


def _model(name: str) -> Path:
    return DEFAULT_MODEL_ROOT / name


def profile_for(role: str, context: int | None = None,
                slots: int | None = None, port: int = 8080,
                model_path: str | None = None,
                state_dir: Path = DEFAULT_STATE,
                environment: str = "mac") -> ServerProfile:
    if environment not in ("mac", "kaggle"):
        raise ValueError(f"unknown environment {environment!r}")
    defaults = MAC_PROFILE if environment == "mac" else KAGGLE_PROFILE
    if role == "writer":
        model = Path(model_path) if model_path else _model(
            os.environ.get("ESUS_WRITER_MODEL", WRITER_MODEL))
    elif role == "verifier":
        model = Path(model_path) if model_path else _model(
            os.environ.get("ESUS_VERIFIER_MODEL", VERIFIER_MODEL))
    else:
        raise ValueError(f"unknown role {role!r}")
    return ServerProfile(
        role=role,
        model_path=model,
        port=int(os.environ.get("ESUS_MODEL_PORT", port)),
        context=int(os.environ.get(
            "ESUS_MODEL_CONTEXT", context or defaults["context"])),
        slots=int(os.environ.get(
            "ESUS_MODEL_SLOTS", slots or defaults["slots"])),
        state_dir=state_dir,
    )


def status(state_dir: Path = DEFAULT_STATE) -> list[dict]:
    records = []
    for path in sorted(Path(state_dir).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pid = record.get("pid")
        alive = False
        if isinstance(pid, int):
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        record["alive"] = alive
        records.append(record)
    return records


def stop_role(role: str, state_dir: Path = DEFAULT_STATE) -> bool:
    path = Path(state_dir) / f"{role}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pid = record.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        path.unlink(missing_ok=True)
        return False
    # A pid file is only trusted for the process the manager wrote; the
    # command line must still name llama-server.
    try:
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, check=False).stdout
    except OSError:
        command = ""
    if "llama-server" not in command:
        path.unlink(missing_ok=True)
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            path.unlink(missing_ok=True)
            return True
        time.sleep(0.5)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    path.unlink(missing_ok=True)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("start", "stop", "status"))
    parser.add_argument("role", nargs="?", choices=("writer", "verifier"))
    parser.add_argument("--context", type=int, default=None)
    parser.add_argument("--slots", type=int, default=None)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--model", default=None)
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--environment", choices=("mac", "kaggle"),
                        default=os.environ.get("ESUS_MODEL_ENV", "mac"))
    args = parser.parse_args(argv)
    state_dir = Path(args.state_dir)

    if args.command == "status":
        print(json.dumps(status(state_dir), indent=2))
        return 0
    if args.command == "stop":
        if not args.role:
            parser.error("stop requires a role")
        stopped = stop_role(args.role, state_dir)
        print(f"{args.role}: {'stopped' if stopped else 'not running'}")
        return 0 if stopped else 1
    if not args.role:
        parser.error("start requires a role")
    profile = profile_for(args.role, args.context, args.slots, args.port,
                          args.model, state_dir, args.environment)
    server = LlamaServer(profile)
    server.start(timeout=args.timeout)
    print(json.dumps({
        "role": profile.role,
        "pid": server.process.pid if server.process else None,
        "url": profile.base_url,
        "context": profile.context,
        "slots": profile.slots,
        "log": str(profile.log_path or profile.default_log_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
