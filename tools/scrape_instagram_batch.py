import json
import os
import time
import threading
from queue import Queue, Empty
from tools.scrape_instagram import scrape_instagram
from tools.tor_proxy import TorPool, rotate_exit_node, is_tor_running

# Fallback shared rotation lock for when TorPool isn't used (single system Tor)
_shared_tor_lock = threading.Lock()
_shared_last_rotation: float = 0.0
_TOR_COOLDOWN = 11.0


def _shared_rotate():
    global _shared_last_rotation
    with _shared_tor_lock:
        wait = _TOR_COOLDOWN - (time.time() - _shared_last_rotation)
        if wait > 0:
            time.sleep(wait)
        rotate_exit_node()
        _shared_last_rotation = time.time()


def _load_checkpoint(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed": [], "results": [], "failed": []}


def _save_checkpoint(path: str, state: dict, lock: threading.Lock):
    with lock:
        with open(path, "w") as f:
            json.dump(state, f, indent=2)


def scrape_instagram_batch(
    urls: list[str],
    checkpoint_path: str = "instagram_batch_progress.json",
    use_tor: bool = False,
    workers: int = 3,
    delay: float = 3.0,
    max_retries: int = 2,
    on_result=None,
) -> list[dict]:
    """
    Scrape a list of Instagram profile URLs with parallel workers, retry on block,
    and checkpoint/resume support.

    When use_tor=True, spins up one independent Tor process per worker so circuit
    rotations happen in parallel (no shared lock). Pre-rotation overlap hides the
    11s Tor cooldown behind the ~8s scrape, cutting per-account time by ~40%.

    Resumes automatically from checkpoint_path if a previous run was interrupted.

    Args:
        urls: List of Instagram profile URLs to scrape.
        checkpoint_path: JSON file to save/resume progress.
        use_tor: Route requests through per-worker Tor instances with circuit rotation.
        workers: Number of parallel browser contexts (default 3).
        delay: Seconds to wait between requests per worker (default 3.0).
        max_retries: Retry attempts on block before marking failed (default 2).
        on_result: Optional callback(result, done_count, total) after each scrape.

    Returns:
        List of result dicts (same format as scrape_instagram).
    """
    if use_tor and not is_tor_running():
        raise RuntimeError("Tor is not running. Start with: sudo service tor start")

    state = _load_checkpoint(checkpoint_path)
    completed_set = set(state["completed"])
    pending = [u for u in urls if u not in completed_set]
    total = len(urls)
    already_done = len(completed_set)

    if not pending:
        print(f"All {total} accounts already done (loaded from checkpoint).")
        return state["results"]

    # Start per-worker Tor pool for parallel independent rotation
    tor_pool: TorPool | None = None
    if use_tor:
        print(f"Starting {workers} Tor instances (one per worker)...")
        tor_pool = TorPool(workers)
        if not tor_pool.start(timeout=60):
            print("Warning: some Tor instances failed — falling back to shared rotation")
            tor_pool.stop()
            tor_pool = None

    print(f"Scraping {len(pending)} accounts ({already_done} already done) | "
          f"workers={workers} tor={'pool' if tor_pool else 'shared' if use_tor else 'off'} delay={delay}s")
    print("-" * 72)

    q: Queue = Queue()
    for url in pending:
        q.put(url)

    state_lock = threading.Lock()
    print_lock = threading.Lock()
    counter = {"done": already_done, "ok": already_done, "failed": 0}

    def worker(wid: int):
        tor_inst = tor_pool.get(wid) if tor_pool else None
        # Pre-rotation thread: runs in background while current scrape is happening
        pending_rotation: threading.Thread | None = None

        # Kick off the very first rotation before we start scraping
        if tor_inst:
            tor_inst.rotate()
        elif use_tor:
            _shared_rotate()

        while True:
            try:
                url = q.get(timeout=2)
            except Empty:
                # Drain any in-flight rotation before exiting
                if pending_rotation:
                    pending_rotation.join()
                break

            # Wait for background rotation started during the previous scrape
            if pending_rotation:
                pending_rotation.join()
                pending_rotation = None

            attempt = 0
            while attempt <= max_retries:
                t0 = time.time()

                # Start next rotation in background — overlaps with this scrape
                if tor_inst:
                    pending_rotation = threading.Thread(
                        target=tor_inst.rotate, daemon=True
                    )
                    pending_rotation.start()
                elif use_tor:
                    pending_rotation = threading.Thread(
                        target=_shared_rotate, daemon=True
                    )
                    pending_rotation.start()

                result = scrape_instagram(
                    url,
                    use_tor=False,          # proxy injected directly below
                    rotate_tor=False,
                    proxy=tor_inst.proxy_args() if tor_inst else None,
                )
                elapsed = round(time.time() - t0, 1)

                blocked = result.get("status") == "blocked" or (
                    "login" in str(result.get("error", "")).lower()
                )

                if blocked and attempt < max_retries:
                    # On retry: cancel running rotation, wait for fresh one
                    if pending_rotation:
                        pending_rotation.join()
                        pending_rotation = None
                    with print_lock:
                        print(f"  [W{wid}] blocked on {url.rstrip('/').split('/')[-1]} "
                              f"— retry {attempt + 1}/{max_retries}")
                    attempt += 1
                    time.sleep(5 * attempt)
                    # Force a fresh rotation before retry
                    if tor_inst:
                        tor_inst.rotate()
                    elif use_tor:
                        _shared_rotate()
                    continue

                with state_lock:
                    counter["done"] += 1
                    if blocked:
                        counter["failed"] += 1
                        state["failed"].append(url)
                        result["_batch_status"] = "failed_after_retries"
                    else:
                        counter["ok"] += 1
                        state["results"].append(result)
                    state["completed"].append(url)

                _save_checkpoint(checkpoint_path, state, state_lock)

                with print_lock:
                    tag = "FAIL" if blocked else ("ERR " if result.get("error") else "ok  ")
                    followers = result.get("followers", "—")
                    name = (result.get("name") or "—")[:22]
                    pct = round(counter["done"] / total * 100)
                    print(f"  [{counter['done']:03d}/{total} {pct:2d}%] W{wid} "
                          f"{url.rstrip('/').split('/')[-1]:<22} {tag}  "
                          f"followers={str(followers):<12} {name}  ({elapsed}s)")

                if on_result:
                    on_result(result, counter["done"], total)

                break

            time.sleep(delay)
            q.task_done()

    threads = [
        threading.Thread(target=worker, args=(i,), daemon=True)
        for i in range(min(workers, len(pending)))
    ]
    t_start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if tor_pool:
        tor_pool.stop()

    total_time = round(time.time() - t_start)
    mins, secs = divmod(total_time, 60)
    print("-" * 72)
    print(f"Done in {mins}m {secs}s | {counter['ok']} ok | {counter['failed']} failed")
    print(f"Checkpoint: {os.path.abspath(checkpoint_path)}")
    return state["results"]
