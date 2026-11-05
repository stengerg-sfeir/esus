#!/usr/bin/env python3
"""Run the whole pipeline on one prompt file: extract, check, generate.

    python3 main.py prompts/prompt_library_system.txt

The intermediate messages of `extract_arch.py` and `generator.py` are hidden.
Their full output is saved in the output folder (`logs/extract.log`,
`logs/generate.log`, plus the extractor's own `run.log`), and the terminal shows
the major steps with an ok/KO status and a rolling spinner while one runs.

By default the extraction is unreviewed (`--no-chat`), because the review asks
questions and a hidden run cannot answer them; the readiness line says so. Pass
`--review` to run the extraction attached to the terminal, so its questions can
be answered, and `--verbose` to see every message instead of the spinner.

Exit codes: 0 done, 1 extraction or readiness failed, 2 generation failed,
3 bad inputs, 130 interrupted.
"""

import argparse
import ast
import itertools
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_SERVER = "http://127.0.0.1:8080"
DEFAULT_MLX = os.environ.get(
    "MLX_MODEL", "mlx-community/Qwen3-4B-Instruct-2507-4bit"
)

EXTRACT_STEPS = ("intentions", "data_models", "errors", "invariants",
                 "components", "service_contracts", "pattern_matches",
                 "interaction_adapters", "persistence_ports")

# A step's model call finishes with `[name] N tokens in Ts`; the pattern step
# has no such line and announces itself as `[ok] step patterns`.
STEP_DONE = re.compile(
    r"^\[(intentions|data_models|errors|invariants|components|"
    r"service_contracts|interaction_adapters|persistence_ports)\] \d+ tokens")
PATTERN_DONE = re.compile(r"^\[ok\] step patterns")
RUN_SUMMARY = re.compile(r"^\[run\] (\d+) steps, (\d+) generated tokens in")
LLM_TOTAL = re.compile(r"^llm: (\d+) refused stub\(s\)")
LLM_CURRENT = re.compile(r"^llm: (\S+) \.\.\.$")
SUMMARY_MARK = "==== SUMMARY ===="
VERDICT = re.compile(r"^GENERATABLE: (YES|NO)(.*)$", re.M)
COUNTS = re.compile(r"^blockers: (\d+), open tie\(s\): (\d+)", re.M)
BLOCKER = re.compile(r"^\s+- \[(\w+)\] (.+)$", re.M)


# --------------------------------------------------------------------------
# reading the two scripts' output
# --------------------------------------------------------------------------

def parse_verdict(text):
    """The last extraction summary as a dict, or None when there is none.

    `extract_arch.py` exits 0 even when its own verdict is `GENERATABLE: NO`,
    so the verdict is read from the summary it prints, never from the code.
    """
    start = text.rfind(SUMMARY_MARK)
    block = text[start:] if start != -1 else text
    verdicts = VERDICT.findall(block)
    if not verdicts:
        return None
    answer, rest = verdicts[-1]
    counts = COUNTS.findall(block)
    blockers, ties = (int(counts[-1][0]), int(counts[-1][1])) if counts else (None, None)
    return {
        "generatable": answer == "YES",
        "unreviewed": "UNREVIEWED" in rest,
        "blockers": blockers,
        "ties": ties,
        "reasons": [f"[{rule}] {message}"
                    for rule, message in BLOCKER.findall(block)],
    }


def extract_progress(line, done):
    """Record a finished extraction step in `done`; return a label or None.

    A prompt may legitimately skip steps (no persistence, say), so the label
    counts finished steps without promising a total.
    """
    match = STEP_DONE.match(line)
    if match:
        done.add(match.group(1))
    elif PATTERN_DONE.match(line):
        done.add("pattern_matches")
    else:
        return None
    return f"{len(done)} step{'s' if len(done) != 1 else ''} done"


def count_methods(generated):
    """`(methods, written_by_the_model, stubs_left)` in the generated package."""
    total = written = stubs = 0
    for name in ("repositories.py", "services.py"):
        path = Path(generated) / name
        if not path.is_file():
            continue
        for cls in (n for n in ast.walk(ast.parse(path.read_text("utf-8")))
                    if isinstance(n, ast.ClassDef)):
            for method in cls.body:
                if not isinstance(method, ast.FunctionDef) \
                        or method.name.startswith("_"):
                    continue
                total += 1
                if "llm-written" in (ast.get_docstring(method) or ""):
                    written += 1
                if any(isinstance(node, ast.Raise) and _raises_not_implemented(node)
                       for node in ast.walk(method)):
                    stubs += 1
    return total, written, stubs


def _raises_not_implemented(node):
    target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    return getattr(target, "id", None) == "NotImplementedError"


def generated_summary(generated):
    """`(ok, detail)` describing what the generator produced."""
    methods, written, stubs = count_methods(generated)
    if methods:
        return True, (f"{methods} methods, {written} written by the model "
                      f"(provisional), {stubs} stubs left")
    if (Path(generated) / "app.py").is_file():
        return True, ("app.py written directly from the requirements "
                      "(the architecture was empty); review it carefully")
    return False, "the generator produced no program files"


def default_output(prompt):
    """`out/<name>` for `prompts/prompt_<name>.txt`."""
    stem = Path(prompt).stem
    return ROOT / "out" / (stem[len("prompt_"):] if stem.startswith("prompt_") else stem)


def duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


# --------------------------------------------------------------------------
# the terminal: major steps, ok/KO, a rolling spinner
# --------------------------------------------------------------------------

class Display:
    """Step lines with a rolling spinner on a terminal, plain lines elsewhere."""

    def __init__(self, out=None, tty=None, color=None, interval=0.1):
        self.out = out or sys.stdout
        self.tty = self.out.isatty() if tty is None else tty
        self.color = (self.tty and "NO_COLOR" not in os.environ
                      if color is None else color)
        encoding = (getattr(self.out, "encoding", None) or "").lower()
        self.frames = (itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏") if "utf" in encoding
                       else itertools.cycle("|/-\\"))
        self.interval = interval
        self.lock = threading.Lock()
        self.label = self.detail = ""
        self.started = 0.0
        self.running = False
        self.stream = False
        self.thread = None

    def begin(self, label, stream=False):
        self.label, self.detail, self.started = label, "", time.monotonic()
        self.stream = stream
        if stream or not self.tty:
            self._write(f"\n-> {label}\n" if stream else f"-> {label}\n")
            return
        self.running = True
        self._write("\033[?25l")
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def set_detail(self, text):
        self.detail = text

    def end(self, ok, detail=""):
        elapsed = time.monotonic() - self.started
        self._stop()
        mark = "ok" if ok else "KO"
        if self.color:
            mark = f"\033[{'32' if ok else '31'};1m{mark}\033[0m"
        self._write(f"[ {mark} ] {self.label:<22} {duration(elapsed):>7}  {detail}\n")

    def line(self, text):
        self._write(text + "\n")

    def close(self):
        self._stop()

    def _stop(self):
        if self.running:
            self.running = False
            self.thread.join()
            self._write("\r\033[K\033[?25h")

    def _spin(self):
        while self.running:
            elapsed = duration(time.monotonic() - self.started)
            text = f"{next(self.frames)} {self.label}  {self.detail}  {elapsed}"
            width = shutil.get_terminal_size((80, 24)).columns - 1
            self._write(f"\r\033[K{text[:width]}")
            time.sleep(self.interval)

    def _write(self, text):
        with self.lock:
            self.out.write(text)
            self.out.flush()


# --------------------------------------------------------------------------
# running a child process, logging everything it prints
# --------------------------------------------------------------------------

def run_command(command, log_path, on_line=None, env=None, interactive=False,
                echo=None):
    """Run `command`, writing all its output to `log_path`; return (code, tail).

    `interactive` keeps the child on the terminal's stdin and in its process
    group, so a question it asks can be answered; the output is then echoed as
    it arrives, prompts without a newline included.
    """
    with open(log_path, "wb", buffering=0) as log:
        log.write(f"$ {shlex.join(command)}\n".encode())
        process = subprocess.Popen(
            command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=None if interactive else subprocess.DEVNULL,
            start_new_session=not interactive)
        tail, pending = deque(maxlen=400), ""
        try:
            while True:
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                log.write(chunk)
                text = chunk.decode("utf-8", "replace")
                if echo:
                    echo(text)
                pending += text
                *lines, pending = pending.split("\n")
                for line in lines:
                    tail.append(line)
                    if on_line:
                        on_line(line)
            if pending:
                tail.append(pending)
            code = process.wait()
        except BaseException:
            _terminate(process, own_group=not interactive)
            raise
        finally:
            process.stdout.close()
    return code, list(tail)


def _terminate(process, own_group):
    """Stop the child (and its own children when it leads a process group)."""
    if process.poll() is not None:
        return

    def send(signum):
        try:
            if own_group:
                os.killpg(process.pid, signum)  # pid == pgid under start_new_session
            else:
                process.send_signal(signum)
        except ProcessLookupError:
            pass

    send(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------

def check_inputs(prompt, model, server_url):
    """`(ok, detail)` for the prompt file and the model it will use."""
    if not prompt.is_file():
        return False, f"prompt file not found: {prompt}"
    if not prompt.read_text("utf-8").strip():
        return False, f"prompt file is empty: {prompt}"
    if model == "mlx":
        try:
            import mlx_lm  # noqa: F401
        except ImportError:
            return False, ("mlx-lm is not installed; run this pipeline with "
                           "the MLX virtualenv (see requirements-mlx.txt)")
        return True, f"model: MLX {DEFAULT_MLX}"
    if model == "server":
        try:
            with urllib.request.urlopen(server_url + "/health", timeout=3) as reply:
                if reply.status != 200 or b"ok" not in reply.read():
                    return False, f"llama-server at {server_url} is not ready"
        except (urllib.error.URLError, OSError) as error:
            return False, (f"llama-server not reachable at {server_url} "
                           f"({getattr(error, 'reason', error)}); start it, set "
                           "--server-url, or pass --model PATH.gguf")
        return True, f"model: llama-server {server_url}"
    if not Path(model).is_file():
        return False, f"model file not found: {model}"
    return True, f"model: {model}"


def echo(text):
    """Pass child output through as it arrives, prompts without a newline too."""
    sys.stdout.write(text)
    sys.stdout.flush()


def build_extract_command(prompt, output, model, review):
    return [sys.executable, "-u", str(ROOT / "extract_arch.py"),
            "--model", model, "--output", str(output),
            "--requirements", str(prompt), "--chat" if review else "--no-chat"]


def build_generate_command(output, model):
    return [sys.executable, "-u", str(ROOT / "generator.py"), str(output),
            "--model", model, "--verbose"]


def fail(display, detail, lines=(), log=None):
    display.end(False, detail)
    lines = list(lines)
    for line in lines[:5]:
        display.line(f"         {line}")
    if len(lines) > 5:
        display.line(f"         ... and {len(lines) - 5} more (see the log)")
    if log:
        display.line(f"         full log: {log}")


def run_pipeline(args, display):
    prompt = Path(args.prompt).resolve()
    output = Path(args.output).resolve() if args.output else default_output(prompt)
    logs = output / "logs"
    server_url = args.server_url or os.environ.get("LLAMA_SERVER_URL", DEFAULT_SERVER)
    env = dict(os.environ, LLAMA_SERVER_URL=server_url, PYTHONUNBUFFERED="1")
    stream = args.verbose or args.review
    started = time.monotonic()
    display.line(f"ESUS  {prompt.name}  ->  {_shown(output)}")

    display.begin("Check inputs")
    ok, detail = check_inputs(prompt, args.model, server_url)
    if not ok:
        fail(display, detail)
        return 3
    display.end(True, detail)
    logs.mkdir(parents=True, exist_ok=True)

    # 1. extraction
    done, ran = set(), {}
    extract_log = logs / "extract.log"
    display.begin("Extract architecture", stream)

    def on_extract(line):
        summary = RUN_SUMMARY.match(line)
        if summary:
            ran["steps"], ran["tokens"] = int(summary.group(1)), int(summary.group(2))
        label = extract_progress(line, done)
        if label:
            display.set_detail(label)
        elif line.startswith("chat:"):
            display.set_detail(line[5:].strip()[:50])

    code, tail = run_command(
        build_extract_command(prompt, output, args.model, args.review),
        extract_log, on_extract, env, interactive=args.review,
        echo=echo if stream else None)
    if code != 0:
        fail(display, f"extract_arch.py exited with {code}",
             [line for line in tail if line.strip()][-3:], _shown(extract_log))
        return 1
    steps = ran.get("steps", len(done))
    display.end(True, f"{steps} steps" + (f", {ran['tokens']:,} tokens"
                                          if "tokens" in ran else ""))

    # 2. readiness, read from the extraction's own summary
    verdict = parse_verdict("\n".join(tail))
    display.begin("Readiness")
    if verdict is None:
        fail(display, "no verdict in the extraction output", log=_shown(extract_log))
        return 1
    if not verdict["generatable"]:
        fail(display, f"{verdict['blockers']} blocker(s), "
                      f"{verdict['ties']} open tie(s)",
             verdict["reasons"], _shown(extract_log))
        display.line("         to answer the open questions, run again with --review")
        return 1
    display.end(True, f"{verdict['blockers']} blockers"
                + (" (unreviewed: no human review ran)" if verdict["unreviewed"] else ""))

    # 3. generation
    generate_log = logs / "generate.log"
    display.begin("Generate code", args.verbose)
    progress = {"total": 0, "seen": 0}

    def on_generate(line):
        match = LLM_TOTAL.match(line)
        if match:
            progress["total"] = int(match.group(1))
        match = LLM_CURRENT.match(line)
        if match:
            progress["seen"] += 1
            display.set_detail(f"writing {match.group(1)} "
                               f"({progress['seen']}/{progress['total']})"[:60])

    code, tail = run_command(
        build_generate_command(output, args.model), generate_log, on_generate,
        env, echo=echo if args.verbose else None)
    if code != 0:
        fail(display, f"generator.py exited with {code}",
             [line for line in tail if line.strip()][-3:], _shown(generate_log))
        return 2
    ok, detail = generated_summary(output / "generated")
    if not ok:
        fail(display, detail, log=_shown(generate_log))
        return 2
    display.end(True, detail)
    summary = (f"Done in {duration(time.monotonic() - started)}\n"
               f"  program: {_shown(output / 'generated')}\n"
               f"  logs:    {_shown(logs)}  (+ {_shown(output / 'run.log')})")
    display.line(summary)
    (logs / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    return 0


def _shown(path):
    """A path relative to the working directory when it is inside it."""
    try:
        return str(Path(path).resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract an architecture from a prompt file and, if it is "
                    "ready, generate the program. Output goes to out/<name> "
                    "unless --output says otherwise; an existing folder is "
                    "re-extracted in place and keeps its recorded decisions.",
        epilog="exit codes: 0 done, 1 extraction or readiness failed, "
               "2 generation failed, 3 bad inputs, 130 interrupted")
    parser.add_argument("prompt", help="requirements file, e.g. prompts/prompt_hello_world.txt")
    parser.add_argument("-o", "--output", help="output folder (default: out/<prompt name>)")
    parser.add_argument("--model", default="server",
                        help="`server` (a running llama-server, the default), "
                             "`mlx` (in-process Apple Silicon backend), or "
                             "the path of a GGUF model")
    parser.add_argument("--server-url", help="llama-server URL (default: "
                        f"$LLAMA_SERVER_URL or {DEFAULT_SERVER})")
    parser.add_argument("--review", action="store_true",
                        help="answer the review questions on the terminal "
                             "(shows the extraction's output instead of a spinner)")
    parser.add_argument("--verbose", action="store_true",
                        help="show every message instead of the spinner")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    display = Display()
    try:
        return run_pipeline(args, display)
    except KeyboardInterrupt:
        display.close()
        display.line("\ninterrupted")
        return 130
    finally:
        display.close()


if __name__ == "__main__":
    sys.exit(main())
