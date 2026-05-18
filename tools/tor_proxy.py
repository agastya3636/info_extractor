import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

SOCKS5_HOST = "127.0.0.1"
SOCKS5_PORT = 9050
CONTROL_PORT = 9051
_TOR_COOLDOWN = 11.0


def is_tor_running() -> bool:
    try:
        with socket.create_connection((SOCKS5_HOST, SOCKS5_PORT), timeout=2):
            return True
    except OSError:
        return False


def rotate_exit_node() -> bool:
    """
    Request a new Tor exit node on the system Tor instance (port 9051).
    Blocks for Tor's NEWNYM cooldown (~10s).
    Reads TOR_CONTROL_PASSWORD from env; leave blank for CookieAuthentication.
    """
    try:
        from stem import Signal
        from stem.control import Controller

        password = os.environ.get("TOR_CONTROL_PASSWORD", "")
        with Controller.from_port(port=CONTROL_PORT) as c:
            c.authenticate(password=password)
            c.signal(Signal.NEWNYM)
            wait = c.get_newnym_wait()
            if wait:
                time.sleep(wait)
        return True
    except Exception:
        return False


def proxy_args() -> dict:
    return {"server": f"socks5://{SOCKS5_HOST}:{SOCKS5_PORT}"}


# ---------------------------------------------------------------------------
# Per-worker Tor instances for parallel rotation
# ---------------------------------------------------------------------------

class TorInstance:
    """
    A self-contained Tor process on dedicated ports.
    Supports independent circuit rotation with no shared lock across workers.
    """

    def __init__(self, index: int):
        # Use ports starting at 19050 to avoid clashing with system Tor on 9050
        self.socks_port = 19050 + index * 2
        self.control_port = 19051 + index * 2
        self._proc: subprocess.Popen | None = None
        self._datadir: str | None = None
        self._lock = threading.Lock()
        self._last_rotation: float = 0.0

    def start(self, timeout: int = 60) -> bool:
        """Launch Tor and block until the SOCKS port is accepting connections."""
        self._datadir = tempfile.mkdtemp(prefix=f"tor_{self.socks_port}_")
        try:
            self._proc = subprocess.Popen(
                [
                    "tor",
                    "--SocksPort", str(self.socks_port),
                    "--ControlPort", str(self.control_port),
                    "--DataDirectory", self._datadir,
                    "--CookieAuthentication", "1",
                    "--Log", "err stderr",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.socks_port), timeout=1):
                    return True
            except OSError:
                time.sleep(1)
        return False

    def stop(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._datadir:
            shutil.rmtree(self._datadir, ignore_errors=True)
            self._datadir = None

    def rotate(self) -> bool:
        """Request a new circuit. Thread-safe with per-instance cooldown."""
        with self._lock:
            wait = _TOR_COOLDOWN - (time.time() - self._last_rotation)
            if wait > 0:
                time.sleep(wait)
            try:
                from stem import Signal
                from stem.control import Controller

                cookie_path = os.path.join(self._datadir, "control_auth_cookie")
                with open(cookie_path, "rb") as f:
                    cookie = f.read()
                with Controller.from_port(port=self.control_port) as c:
                    c.authenticate(cookie)
                    c.signal(Signal.NEWNYM)
                self._last_rotation = time.time()
                return True
            except Exception:
                return False

    def proxy_args(self) -> dict:
        return {"server": f"socks5://127.0.0.1:{self.socks_port}"}

    def __repr__(self):
        return f"TorInstance(socks={self.socks_port}, ctrl={self.control_port})"


class TorPool:
    """
    Manages N independent TorInstance processes — one per batch worker.
    Use as a context manager so instances are cleanly stopped on exit.
    """

    def __init__(self, size: int):
        self.instances = [TorInstance(i) for i in range(size)]

    def start(self, timeout: int = 60) -> bool:
        """Start all instances in parallel and return True if all succeeded."""
        ok = [False] * len(self.instances)

        def _start(i, inst):
            ok[i] = inst.start(timeout)
            status = "ready" if ok[i] else "FAILED"
            print(f"  Tor instance {i} (:{inst.socks_port}) {status}")

        threads = [threading.Thread(target=_start, args=(i, inst), daemon=True)
                   for i, inst in enumerate(self.instances)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        return all(ok)

    def stop(self):
        for inst in self.instances:
            inst.stop()

    def get(self, worker_id: int) -> TorInstance:
        return self.instances[worker_id % len(self.instances)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop()
