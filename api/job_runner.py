"""Private subprocess entry point; configuration arrives only through stdin."""
import asyncio
import json
import os
import sys

from harness.orchestrator import Orchestrator
from harness.settings import Settings
from storage.repository import JobRepository


def main():
    if sys.platform.startswith("linux"):
        import ctypes
        from api.job_process import _stop_linux_tree
        # Orphaned grandchildren (e.g. detached browser processes) remain owned
        # by this worker rather than disappearing into the container's init.
        if ctypes.CDLL(None, use_errno=True).prctl(36, 1) != 0:
            raise RuntimeError("Cannot establish worker descendant ownership")
    # Before the API persists PID identity it sends no bytes. A pre-marker API
    # crash therefore gives EOF/invalid JSON and cannot launch any production.
    settings = Settings(_env_file=None, **json.loads(sys.stdin.buffer.read()))
    repository = JobRepository(settings.database_url)
    try:
        job_id = sys.argv[1]
        record = repository.get(job_id)
        if record is None or record.status in {"cancelling", "cancelled"}:
            return
        asyncio.run(Orchestrator(settings, repository).run(job_id))
    finally:
        try:
            if sys.platform.startswith("linux"):
                from api.job_process import _confirm_linux_stopped
                marker = settings.output_dir / sys.argv[1] / ".worker-process.json"
                stopped = _stop_linux_tree(os.getpid(), include_root=False, marker=marker)
                asyncio.run(_confirm_linux_stopped(stopped))
        finally:
            repository.close()


if __name__ == "__main__":
    main()
