"""One local job per process group; cancellation owns its renderer children too."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys


class ProcessCleanupError(RuntimeError):
    """Do not release generation capacity until recovery confirms termination."""


def _identity(pid):
    if sys.platform.startswith("linux"):
        item = _linux_processes().get(pid)
        return item[2] if item else None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        api = ctypes.windll.kernel32
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        try:
            exit_code = wintypes.DWORD()
            if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                raise RuntimeError("Cannot establish worker process state")
            if exit_code.value != 259:  # STILL_ACTIVE; Windows retains exited process handles.
                return None
            if not api.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                raise RuntimeError("Cannot establish worker process identity")
            return f"{times[0].dwHighDateTime}:{times[0].dwLowDateTime}"
        finally:
            api.CloseHandle(handle)
    raise RuntimeError("Isolated job recovery supports Linux and Windows")


def _linux_processes():
    result = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
            result[int(path.name)] = (int(fields[1]), int(fields[2]), fields[19])
        except (OSError, ValueError, IndexError):
            continue
    return result


def _stop_linux_tree(pid, *, include_root=True, marker=None, birth=None):
    # Chromium can create another process group. Freeze the root and descendants
    # before killing so no renderer can fork/reparent during the tree walk.
    root = _linux_processes().get(pid)
    if root is None or (birth is not None and root[2] != birth):
        return {}
    known = {pid: root}
    is_self = pid == os.getpid()
    if not is_self:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGSTOP)
    while True:
        processes = _linux_processes()
        owned = {child for child, identity in known.items()
                 if child in processes and processes[child][2] == identity[2]}
        root_alive = pid in owned
        while True:
            added = {child for child, (parent, group, _) in processes.items()
                     if parent in owned or (root_alive and group == pid)} - owned
            if not added:
                break
            owned.update(added)
        discovered = {child: processes[child] for child in owned if child in processes and child not in known}
        if not discovered:
            break
        for child, identity in discovered.items():
            if child == os.getpid():
                continue
            # The birth timestamp prevents signalling a recycled PID.
            if (_linux_processes().get(child) or (None, None, None))[2] == identity[2]:
                with suppress(ProcessLookupError):
                    os.kill(child, signal.SIGSTOP)
        known.update(discovered)
    if marker is not None and marker.exists() and known:
        saved = json.loads(marker.read_text(encoding="utf-8"))
        saved["processes"] = {**saved.get("processes", {}),
                              **{str(child): identity[2] for child, identity in known.items()}}
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved), encoding="utf-8")
        temporary.replace(marker)
    for child, identity in sorted(known.items(), key=lambda pair: pair[0] == pid):
        if child == pid and not include_root:
            continue
        if (_linux_processes().get(child) or (None, None, None))[2] == identity[2]:
            with suppress(ProcessLookupError):
                os.kill(child, signal.SIGKILL)
    return {child: identity for child, identity in known.items() if include_root or child != pid}


async def _confirm_linux_stopped(known):
    for _ in range(200):
        current = _linux_processes()
        alive = []
        for pid, identity in known.items():
            if pid in current and current[pid][2] == identity[2]:
                try:
                    state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                except (OSError, IndexError):
                    continue
                if state != "Z":
                    alive.append(pid)
        if not alive:
            return
        await asyncio.sleep(.05)
    raise ProcessCleanupError("Worker descendants have not stopped; generation remains locked")


async def recover_workers(output_dir, *, only_marker=None):
    """Reconcile a previous API owner's children before admitting any new job."""
    root = Path(output_dir).resolve()
    for path in [only_marker] if only_marker is not None else root.glob("*/.worker-process.json"):
        if not path.exists():
            continue
        if path.is_symlink() or path.parent.is_symlink() or path.resolve().parent.parent != root:
            raise RuntimeError("Invalid worker ownership file")
        data = json.loads(path.read_text(encoding="utf-8"))
        identities = {str(data["pid"]): data["birth"], **data.get("processes", {})}
        for raw_pid, born in identities.items():
            pid = int(raw_pid)
            if pid <= 1 or pid == os.getpid():
                raise RuntimeError("Invalid worker process identity")
            if _identity(pid) != born:
                continue
            if sys.platform.startswith("linux"):
                await _confirm_linux_stopped(_stop_linux_tree(pid, marker=path, birth=born))
            else:
                killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                await killer.wait()
                for _ in range(200):
                    if _identity(pid) != born:
                        break
                    await asyncio.sleep(.05)
                else:
                    raise RuntimeError("Previous worker has not stopped")
        path.unlink(missing_ok=True)


async def stop_process_tree(process: asyncio.subprocess.Process, *, grace: float = 1.0, marker=None):
    if os.name == "nt":
        if process.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
    elif sys.platform.startswith("linux"):
        born = json.loads(marker.read_text())["birth"] if marker is not None and marker.exists() else None
        if process.returncode is None or (born is not None and _identity(process.pid) == born):
            await _confirm_linux_stopped(_stop_linux_tree(process.pid, marker=marker, birth=born))
    else:
        # The group was created solely for this job (start_new_session=True).
        # Kill remaining children even if their parent already exited.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if process.returncode is None:
            with suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(process.wait()), grace)
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    await process.wait()


async def run_isolated(settings, job_id: str, *, command: list[str] | None = None) -> int:
    values = settings.model_dump(mode="json")
    for name in type(settings).model_fields:
        value = getattr(settings, name)
        if hasattr(value, "get_secret_value"):
            values[name] = value.get_secret_value()
    # A private stdin pipe preserves per-job settings without credentials in
    # process arguments, logs, temporary files, or public artifacts.
    payload = json.dumps(values).encode("utf-8")
    env = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    spawning = asyncio.create_task(asyncio.create_subprocess_exec(
        *(command or [sys.executable, "-m", "api.job_runner", job_id]),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL, cwd=settings.project_root, env=env, **options,
    ))
    process = None
    marker = Path(settings.output_dir) / job_id / ".worker-process.json"
    try:
        process = await asyncio.shield(spawning)
        marker.parent.mkdir(parents=True, exist_ok=True)
        birth = _identity(process.pid)
        if birth is not None:
            temporary = marker.with_suffix(".tmp")
            temporary.write_text(json.dumps({"pid": process.pid, "birth": birth}), encoding="utf-8")
            temporary.replace(marker)
        await process.communicate(payload)
        return process.returncode
    finally:
        # Cancellation during spawn must not lose the just-created process.
        if process is None:
            with suppress(Exception):
                process = await spawning
        if process is not None:
            async def clean():
                try:
                    await stop_process_tree(process, marker=marker)
                    await recover_workers(settings.output_dir, only_marker=marker)
                except Exception as exc:
                    raise ProcessCleanupError("Worker cleanup could not be confirmed") from exc
            cleanup = asyncio.create_task(clean())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

