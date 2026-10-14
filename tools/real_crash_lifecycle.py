"""Real application process crash/restart lifecycle proof.

Starts actual FastAPI uvicorn processes against the network-isolated
MongoDB clone, performs HTTP smoke tests, and kills them to prove
zero economic writes across start/stop/restart/crash cycles.
"""
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse

# We need motor for canonical hash verification
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from motor.motor_asyncio import AsyncIOMotorClient

SOCKET = "/tmp/v3-candidate-mongo-socket/mongodb-27024.sock"
TENANT_DB = "sellerbottel_real_rehearsal_tenant_legacy_owner"
ARCHIVE_DB = "sellerbottel_real_rehearsal_archive"
BACKEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'backend')
PYTHON = "/home/sellerbottelv2/.uat-runtime/venv/bin/python"
HOST = "127.0.0.1"
PORT = "19876"

COLLECTIONS = {
    TENANT_DB: ["bot_users", "store_customers", "counters"],
    ARCHIVE_DB: ["history__inventory_items"],
}

ENV = {
    "PATH": os.environ["PATH"],
    "HOME": os.environ.get("HOME", "/tmp"),
    "PYTHONPATH": BACKEND_DIR,
    "CANDIDATE_READONLY": "1",
    "ENVIRONMENT": "development",
    "MONGO_URL": f"mongodb://{urllib.parse.quote_plus(SOCKET)}",
    "DB_NAME": TENANT_DB,
    "PLATFORM_DB_NAME": "sellerbottel_real_rehearsal_platform",
    "CORS_ORIGINS": "http://localhost:3000",
    "JWT_SECRET": "lifecycle-test-jwt",
    "CANDIDATE_AUTH_SECRET": "lifecycle-test-auth",
    "GOPAY_ENABLED": "0",
    "BOT2_ENABLED": "0",
}


def canonical_hash(docs):
    sd = sorted(docs, key=lambda d: str(d.get("_id", "")))
    raw = json.dumps(sd, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def snapshot():
    uri = f"mongodb://{urllib.parse.quote_plus(SOCKET)}"
    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    result = {}
    for db_name, cols in COLLECTIONS.items():
        db = client[db_name]
        for c in cols:
            docs = await db[c].find().to_list(None)
            key = f"{db_name}.{c}"
            result[key] = {"count": len(docs), "hash": canonical_hash(docs)}
    client.close()
    return result


def start_server():
    """Start uvicorn serving the candidate FastAPI app."""
    proc = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "server:app",
         "--host", HOST, "--port", PORT, "--log-level", "warning"],
        cwd=BACKEND_DIR,
        env=ENV,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def wait_health(timeout=15):
    """Poll health endpoint until ready."""
    import urllib.request
    url = f"http://{HOST}:{PORT}/api/"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError("Server did not become healthy")


def smoke_test():
    """Run HTTP smoke tests against running server."""
    import urllib.request
    base = f"http://{HOST}:{PORT}"
    results = {}

    # Health
    resp = urllib.request.urlopen(f"{base}/api/", timeout=5)
    results["health"] = resp.status

    # Blocked checkout (POST)
    req = urllib.request.Request(f"{base}/api/store/checkout", data=b'{}',
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        results["checkout_blocked"] = False
    except urllib.error.HTTPError as e:
        results["checkout_blocked"] = e.code == 503

    # Blocked deposit
    req = urllib.request.Request(f"{base}/api/store/deposit", data=b'{}',
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        results["deposit_blocked"] = False
    except urllib.error.HTTPError as e:
        results["deposit_blocked"] = e.code == 503

    # Blocked payment
    req = urllib.request.Request(f"{base}/api/payments/create", data=b'{}',
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        results["payment_blocked"] = False
    except urllib.error.HTTPError as e:
        results["payment_blocked"] = e.code == 503

    return results


def graceful_stop(proc, timeout=10):
    """Send SIGTERM and wait for clean exit."""
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return proc.returncode


def crash_kill(proc):
    """Send SIGKILL to simulate crash."""
    pid = proc.pid
    os.kill(pid, signal.SIGKILL)
    proc.wait()
    # Verify process is gone
    try:
        os.kill(pid, 0)
        raise RuntimeError(f"Process {pid} still alive after SIGKILL")
    except ProcessLookupError:
        pass  # expected
    return pid


def main():
    print("=== REAL APPLICATION CRASH/RESTART LIFECYCLE PROOF ===")
    evidence = {"cycles": []}

    # Before snapshot
    before = asyncio.run(snapshot())
    print(f"BEFORE: {json.dumps({k: v['count'] for k, v in before.items()})}")

    # --- CYCLE 1: Start -> Smoke -> Graceful Stop ---
    print("\n--- CYCLE 1: Start -> Smoke -> Graceful Stop ---")
    proc1 = start_server()
    print(f"  Started PID={proc1.pid}")
    wait_health()
    print("  Health: OK")
    smoke1 = smoke_test()
    print(f"  Smoke: {smoke1}")
    rc1 = graceful_stop(proc1)
    print(f"  Stopped (rc={rc1})")
    after1 = asyncio.run(snapshot())
    assert before == after1, "Cycle 1: snapshot changed!"
    print("  ZERO-WRITE: CONFIRMED")
    evidence["cycles"].append({
        "cycle": 1, "type": "start_smoke_graceful_stop",
        "pid": proc1.pid, "smoke": smoke1, "zero_write": True,
        "hashes_match": True})

    # --- CYCLE 2: Restart -> Smoke -> Graceful Stop ---
    print("\n--- CYCLE 2: Restart -> Smoke -> Graceful Stop ---")
    proc2 = start_server()
    print(f"  Started PID={proc2.pid}")
    wait_health()
    print("  Health: OK")
    smoke2 = smoke_test()
    print(f"  Smoke: {smoke2}")
    rc2 = graceful_stop(proc2)
    print(f"  Stopped (rc={rc2})")
    after2 = asyncio.run(snapshot())
    assert before == after2, "Cycle 2: snapshot changed!"
    print("  ZERO-WRITE: CONFIRMED")
    evidence["cycles"].append({
        "cycle": 2, "type": "restart_smoke_graceful_stop",
        "pid": proc2.pid, "smoke": smoke2, "zero_write": True,
        "hashes_match": True})

    # --- CYCLE 3: Start -> Smoke -> SIGKILL crash -> Restart -> Smoke -> Stop ---
    print("\n--- CYCLE 3: Start -> Smoke -> SIGKILL CRASH -> Restart -> Smoke -> Stop ---")
    proc3a = start_server()
    print(f"  Started PID={proc3a.pid}")
    wait_health()
    print("  Health: OK")
    smoke3a = smoke_test()
    print(f"  Pre-crash smoke: {smoke3a}")
    crashed_pid = crash_kill(proc3a)
    print(f"  SIGKILL sent to PID={crashed_pid}, process terminated")
    mid_crash = asyncio.run(snapshot())
    assert before == mid_crash, "After crash: snapshot changed!"
    print("  Post-crash ZERO-WRITE: CONFIRMED")

    # Restart after crash
    time.sleep(1)  # brief pause
    proc3b = start_server()
    print(f"  Restarted PID={proc3b.pid}")
    wait_health()
    print("  Health: OK")
    smoke3b = smoke_test()
    print(f"  Post-crash-restart smoke: {smoke3b}")
    rc3b = graceful_stop(proc3b)
    print(f"  Stopped (rc={rc3b})")
    after3 = asyncio.run(snapshot())
    assert before == after3, "Cycle 3 final: snapshot changed!"
    print("  ZERO-WRITE: CONFIRMED")
    evidence["cycles"].append({
        "cycle": 3, "type": "start_smoke_SIGKILL_restart_smoke_stop",
        "pre_crash_pid": crashed_pid,
        "post_crash_pid": proc3b.pid,
        "pre_crash_smoke": smoke3a,
        "post_crash_smoke": smoke3b,
        "zero_write": True,
        "hashes_match": True})

    # Final comparison
    evidence["status"] = "PASS"
    evidence["before"] = before
    evidence["after_final"] = after3
    evidence["all_hashes_identical"] = before == after3

    out = "/tmp/v3-candidate/real-crash-lifecycle-evidence.json"
    with open(out, "w") as f:
        json.dump(evidence, f, indent=2)
    print(f"\nEvidence saved to {out}")
    print("=== ALL CYCLES PASS ===")


if __name__ == "__main__":
    main()
