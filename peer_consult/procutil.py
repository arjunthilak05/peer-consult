"""Subprocess execution: argv arrays only (shell=False), bounded capture,
stderr heartbeats, timeout/cancel with whole-process-tree cleanup.

Provides both synchronous ``run()`` and asynchronous ``async_run()`` using
``asyncio.create_subprocess_exec`` without shell interpolation.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = os.name == "nt"


@dataclass
class ProcResult:
    returncode: int | None
    stdout: str
    stderr: str
    elapsed: float
    timed_out: bool = False
    cancelled: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    pid: int | None = None
    extra: dict = field(default_factory=dict)


def log(msg: str) -> None:
    print(f"[peer-consult] {msg}", file=sys.stderr, flush=True)


# ---------- executable resolution ----------

class ExecutableError(Exception):
    pass


def resolve_command(name: str, configured: list[str]) -> list[str]:
    """Return an argv prefix for the CLI. Never routes through cmd.exe.

    npm installs a ``codex.cmd`` batch shim on Windows. Batch files re-parse
    arguments through cmd.exe, so instead we run the package's JS entry point
    with node directly.
    """
    if configured:
        exe = shutil.which(configured[0]) or configured[0]
        if not Path(exe).exists():
            raise ExecutableError(f"configured {name} command not found: {configured[0]}")
        return [exe, *configured[1:]]
    found = shutil.which(name)
    if not found:
        raise ExecutableError(f"'{name}' executable not found on PATH; install it or set [{name}].command in the config")
    p = Path(found)
    if p.suffix.lower() in (".cmd", ".bat"):
        if name == "codex":
            js = p.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            node = p.parent / "node.exe"
            node_s = str(node) if node.exists() else shutil.which("node")
            if js.exists() and node_s:
                return [node_s, str(js)]
        raise ExecutableError(
            f"{found} is a batch shim; refusing to pass arguments through cmd.exe. "
            f"Set [{name}].command in the config to the real executable."
        )
    return [str(p)]


# ---------- process tree control ----------

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IOCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _ExtLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IOCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    # Explicit signatures so 64-bit HANDLE values are never truncated to C int.
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.GetExitCodeProcess.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.CloseHandle.restype = wintypes.BOOL

    def _make_job():
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            _k32.CloseHandle(job)  # without KILL_ON_JOB_CLOSE the job adds nothing; use taskkill only
            return None
        return job

    def _assign(job, pid) -> bool:
        h = _k32.OpenProcess(0x0001 | 0x0100, False, pid)  # PROCESS_TERMINATE | PROCESS_SET_QUOTA
        if not h:
            return False
        ok = bool(_k32.AssignProcessToJobObject(job, h))
        _k32.CloseHandle(h)
        return ok

    def pid_alive(pid: int) -> bool:
        h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = wintypes.DWORD()
        ok = _k32.GetExitCodeProcess(h, ctypes.byref(code))
        _k32.CloseHandle(h)
        return (not ok) or code.value == 259  # STILL_ACTIVE; unknown counts as alive
else:
    def pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def _proc_running(proc) -> bool:
    if hasattr(proc, "poll"):
        return proc.poll() is None
    return getattr(proc, "returncode", None) is None


class _Tree:
    def __init__(self, proc):
        self.proc = proc
        self.job = None
        if IS_WINDOWS:
            self.job = _make_job()
            if self.job and not _assign(self.job, proc.pid):
                _k32.CloseHandle(self.job)
                self.job = None

    def kill(self) -> None:
        if IS_WINDOWS:
            # Walk the tree while the root is still alive (catches anything that escaped the
            # job, e.g. spawned before assignment), then terminate every job member.
            if _proc_running(self.proc):
                try:
                    subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   shell=False, timeout=15)
                except subprocess.TimeoutExpired:
                    pass
            if self.job is not None:
                _k32.TerminateJobObject(self.job, 1)
            if _proc_running(self.proc):
                try:
                    self.proc.kill()
                except OSError:
                    pass
        else:
            self._killpg(graceful=True)
        if hasattr(self.proc, "poll"):
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

    def _killpg(self, graceful: bool) -> None:
        try:
            if graceful:
                os.killpg(self.proc.pid, signal.SIGTERM)
                time.sleep(1.5)
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def close(self) -> None:
        """Always called, including after a normal exit: reap same-group/job stragglers."""
        if IS_WINDOWS:
            if self.job is not None:
                # KILL_ON_JOB_CLOSE: any straggler children die with the handle.
                _k32.CloseHandle(self.job)
                self.job = None
        else:
            self._killpg(graceful=False)


def _reader(stream, cap: int, keep_tail: bool, out: dict, key: str) -> None:
    buf = bytearray()
    truncated = False
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        buf += chunk
        if len(buf) > cap:
            truncated = True
            if keep_tail:
                del buf[: len(buf) - cap]
            else:
                del buf[cap:]
    out[key] = bytes(buf)
    out[key + "_truncated"] = truncated


def run(argv: list[str], *, stdin_text: str, env: dict, cwd: str, timeout: float,
        max_stdout: int, max_stderr: int, heartbeat: float, label: str) -> ProcResult:
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=cwd, env=env, shell=False, **kwargs)
    tree = _Tree(proc)
    got: dict = {}
    t_out = threading.Thread(target=_reader, args=(proc.stdout, max_stdout, False, got, "stdout"), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, max_stderr, True, got, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    def feed():
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    t_in = threading.Thread(target=feed, daemon=True)
    t_in.start()
    timed_out = cancelled = False
    next_beat = start + heartbeat
    try:
        while True:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            if now - start > timeout:
                timed_out = True
                log(f"{label}: timeout after {int(now - start)}s; terminating process tree")
                tree.kill()
                break
            if now >= next_beat:
                log(f"{label}: still consulting ({int(now - start)}s elapsed, timeout {int(timeout)}s)")
                next_beat = now + heartbeat
    except KeyboardInterrupt:
        cancelled = True
        log(f"{label}: cancelled; terminating process tree")
        tree.kill()
    finally:
        tree.close()
    t_out.join(timeout=10)
    t_err.join(timeout=10)
    res = ProcResult(
        returncode=proc.returncode,
        stdout=got.get("stdout", b"").decode("utf-8", errors="replace"),
        stderr=got.get("stderr", b"").decode("utf-8", errors="replace"),
        elapsed=round(time.monotonic() - start, 2),
        timed_out=timed_out, cancelled=cancelled,
        stdout_truncated=got.get("stdout_truncated", False),
        stderr_truncated=got.get("stderr_truncated", False),
        pid=proc.pid,
    )
    if cancelled:
        raise KeyboardInterrupt
    return res


async def _async_reader(
    stream: asyncio.StreamReader | None,
    cap: int,
    keep_tail: bool,
    out: dict,
    key: str,
    on_line: Callable[[str], None] | None = None,
) -> None:
    buf = bytearray()
    line_buf = bytearray()
    truncated = False
    if stream is None:
        out[key] = b""
        out[key + "_truncated"] = False
        return
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        if on_line is not None:
            line_buf += chunk
            while b"\n" in line_buf:
                idx = line_buf.index(b"\n")
                raw_line = bytes(line_buf[:idx])
                del line_buf[: idx + 1]
                try:
                    on_line(raw_line.decode("utf-8", errors="replace").strip())
                except Exception:
                    pass
        buf += chunk
        if len(buf) > cap:
            truncated = True
            if keep_tail:
                del buf[: len(buf) - cap]
            else:
                del buf[cap:]
    if on_line is not None and line_buf:
        try:
            on_line(bytes(line_buf).decode("utf-8", errors="replace").strip())
        except Exception:
            pass
    out[key] = bytes(buf)
    out[key + "_truncated"] = truncated


async def async_run(
    argv: list[str],
    *,
    stdin_text: str,
    env: dict,
    cwd: str,
    timeout: float,
    max_stdout: int,
    max_stderr: int,
    heartbeat: float,
    label: str,
    on_stdout_line: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> ProcResult:
    """Execute ``argv`` asynchronously without shell interpolation and with full process-tree cleanup."""
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        **kwargs,
    )
    tree = _Tree(proc)
    got: dict = {}
    t_out = asyncio.create_task(_async_reader(proc.stdout, max_stdout, False, got, "stdout", on_stdout_line))
    t_err = asyncio.create_task(_async_reader(proc.stderr, max_stderr, True, got, "stderr", None))

    async def _feed():
        if proc.stdin is None:
            return
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    t_in = asyncio.create_task(_feed())
    timed_out = cancelled = False
    next_beat = start + heartbeat
    wait_task = asyncio.create_task(proc.wait())
    try:
        while not wait_task.done():
            done, _ = await asyncio.wait({wait_task}, timeout=0.35)
            if done:
                break
            if cancel_check is not None and cancel_check():
                cancelled = True
                log(f"{label}: cancel requested; terminating process tree")
                await asyncio.to_thread(tree.kill)
                break
            now = time.monotonic()
            if now - start > timeout:
                timed_out = True
                log(f"{label}: timeout after {int(now - start)}s; terminating process tree")
                await asyncio.to_thread(tree.kill)
                break
            if now >= next_beat:
                log(f"{label}: still running ({int(now - start)}s elapsed, timeout {int(timeout)}s)")
                next_beat = now + heartbeat
    except ( asyncio.CancelledError, KeyboardInterrupt ):
        cancelled = True
        log(f"{label}: cancelled; terminating process tree")
        await asyncio.to_thread(tree.kill)
        raise
    finally:
        if not wait_task.done():
            wait_task.cancel()
            try:
                await wait_task
            except (asyncio.CancelledError, Exception):
                pass
        await asyncio.to_thread(tree.close)
    try:
        await asyncio.wait_for(asyncio.gather(t_in, t_out, t_err, return_exceptions=True), timeout=10.0)
    except TimeoutError:
        pass
    return ProcResult(
        returncode=proc.returncode,
        stdout=got.get("stdout", b"").decode("utf-8", errors="replace"),
        stderr=got.get("stderr", b"").decode("utf-8", errors="replace"),
        elapsed=round(time.monotonic() - start, 2),
        timed_out=timed_out,
        cancelled=cancelled,
        stdout_truncated=got.get("stdout_truncated", False),
        stderr_truncated=got.get("stderr_truncated", False),
        pid=proc.pid,
    )
