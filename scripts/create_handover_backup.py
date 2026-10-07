"""Private full-value application backup, verified via an isolated Mongo restore.

Run with the backend Python environment and permission to read deployment files
and operate Docker. Does not stop, reset, restore, or write to production MongoDB.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from datetime import datetime, timezone

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
DEST = ROOT / "backups" / ("handover-" + STAMP)
SOURCE = "sellerbottel-mongodb"
VERIFY = "idse-backup-verify-" + STAMP.lower()
os.umask(0o077)
DEST.mkdir(parents=True, exist_ok=False, mode=0o700)

SNAPSHOT_JS = r'''
const database = db.getSiblingDB("sellerbottel");
const crypto = require("crypto");
function sorted(x) {
  if (Array.isArray(x)) return x.map(sorted);
  if (x !== null && typeof x === "object") return Object.fromEntries(Object.keys(x).sort().map(k => [k, sorted(x[k])]));
  return x;
}
function canonical(x) { return JSON.stringify(sorted(EJSON.serialize(x, {relaxed:false}))); }
function hash(x) { return crypto.createHash("sha256").update(canonical(x)).digest("hex"); }
const result = {};
for (const info of database.getCollectionInfos().sort((a,b)=>a.name.localeCompare(b.name))) {
  const collection = database.getCollection(info.name);
  const digest = crypto.createHash("sha256");
  let count = 0;
  collection.find({}).sort({_id:1}).forEach(doc => { digest.update(canonical(doc)+"\n"); count++; });
  const indexes = info.type === "view" ? [] : collection.getIndexes().map(x => { delete x.ns; return x; }).sort((a,b)=>a.name.localeCompare(b.name));
  result[info.name] = {count, documents_sha256:digest.digest("hex"), indexes_sha256:hash(indexes), options_sha256:hash(info.options || {})};
}
print(JSON.stringify(result));
'''


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def capture(filename, args):
    with (DEST / filename).open("wb") as stream:
        run(args, stdout=stream, stderr=subprocess.STDOUT)


def snapshot(container):
    result = run(["docker", "exec", container, "mongosh", "--quiet", "--eval", SNAPSHOT_JS],
                 capture_output=True, text=True)
    return json.loads(result.stdout)


def save(name, value):
    (DEST / name).write_text(json.dumps(value, indent=2) + "\n")


def archive(path, entries):
    with tarfile.open(path, "w:gz") as output:
        for entry, name in entries:
            output.add(entry, arcname=name)


def main():
    assert (ROOT / "AGENT_HANDOVER.md").is_file()
    config = dotenv_values(ROOT / "backend/.env")
    assert config.get("DB_NAME") == "sellerbottel", "Unexpected database: audit backup target first"
    assert config.get("INVENTORY_ENCRYPTION_KEY"), "Missing inventory decryption key"
    capture("git-status.txt", ["git", "-C", str(ROOT), "status", "--short"])
    capture("git-branches.txt", ["git", "-C", str(ROOT), "branch", "-avv"])
    capture("git-log.txt", ["git", "-C", str(ROOT), "log", "--oneline", "-10"])
    capture("working-tree.patch", ["git", "-C", str(ROOT), "diff", "--binary", "HEAD"])
    capture("docker-inspect.json", ["docker", "inspect", SOURCE])
    capture("systemd-unit.txt", ["systemctl", "cat", "sellerbottel"])
    capture("python-packages.txt", [str(ROOT / "backend/venv/bin/pip"), "freeze"])
    capture("node-version.txt", ["node", "--version"])
    capture("npm-version.txt", ["npm", "--version"])
    capture("mongo-version.txt", ["docker", "exec", SOURCE, "mongod", "--version"])

    # Accept only a dump bracketed by identical full-value snapshots. No downtime.
    for attempt in range(1, 4):
        before = snapshot(SOURCE)
        with (DEST / "mongodb.archive.gz").open("wb") as data, (DEST / "mongodump.log").open("wb") as log:
            run(["docker", "exec", SOURCE, "mongodump", "--db", "sellerbottel", "--gzip", "--archive"], stdout=data, stderr=log)
        after = snapshot(SOURCE)
        if before == after:
            break
    else:
        raise RuntimeError("Database changed during each attempt; backup not marked verified. Retry at a quieter time.")
    save("database-before.json", before)
    save("database-after.json", after)
    with gzip.open(DEST / "mongodb.archive.gz", "rb") as stream:
        while stream.read(1024 * 1024):
            pass
    print("Full Mongo dump captured; production snapshots match.", flush=True)

    started = False
    try:
        run(["docker", "run", "--detach", "--name", VERIFY, "--network", "none",
             "--tmpfs", "/data/db:rw", "--tmpfs", "/data/configdb:rw", "mongo:7.0",
             "mongod", "--bind_ip", "127.0.0.1", "--setParameter", "ttlMonitorEnabled=false"], stdout=subprocess.DEVNULL)
        started = True
        for _ in range(30):
            ping = subprocess.run(["docker", "exec", VERIFY, "mongosh", "--quiet", "--eval", "quit(db.adminCommand({ping:1}).ok ? 0 : 1)"], capture_output=True)
            if ping.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Isolated verification Mongo failed to start")
        with (DEST / "mongodb.archive.gz").open("rb") as data, (DEST / "mongorestore-verification.log").open("wb") as log:
            run(["docker", "exec", "-i", VERIFY, "mongorestore", "--gzip", "--archive", "--stopOnError"], stdin=data, stdout=log, stderr=subprocess.STDOUT)
        restored = snapshot(VERIFY)
        save("database-restored.json", restored)
        assert before == restored, "Isolated restore differs in document values, indexes, or collection options"
        save("verification.json", {"verified": True, "production_unchanged_during_dump": True,
            "isolated_restore_matches_all_document_values": True, "indexes_and_options_match": True,
            "collections": len(before), "documents": sum(x["count"] for x in before.values()),
            "dump_attempt": attempt, "database": "sellerbottel"})
    finally:
        if started:
            # Only our newly-created ephemeral verification container, never production.
            run(["docker", "rm", "--force", "--volumes", VERIFY], stdout=subprocess.DEVNULL)
    print("Isolated restore verified: all values, indexes and collection options match.", flush=True)

    excluded = {"backups", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", ".cache"}
    def repo_filter(info):
        if any(part in excluded for part in Path(info.name).parts[1:]):
            return None
        return info
    with tarfile.open(DEST / "repository.tar.gz", "w:gz") as output:
        output.add(ROOT, arcname="sellerbottel", filter=repo_filter)
    with tarfile.open(DEST / "repository.tar.gz") as check:
        names = check.getnames()
        for expected in ("sellerbottel/AGENT_HANDOVER.md", "sellerbottel/backend/.env", "sellerbottel/.git/HEAD", "sellerbottel/frontend/build/index.html"):
            assert expected in names, "Missing repository backup entry: " + expected
    (DEST / "repository-files.txt").write_text("\n".join(names) + "\n")

    candidates = ("/etc/nginx", "/etc/letsencrypt", "/etc/systemd/system/sellerbottel.service", "/etc/systemd/system/sellerbottel.service.d")
    runtime = [(Path(p), p.lstrip("/")) for p in candidates if Path(p).exists()]
    archive(DEST / "runtime-config.tar.gz", runtime)
    pid = run(["systemctl", "show", "sellerbottel", "--property=MainPID", "--value"], capture_output=True, text=True).stdout.strip()
    env = dict(x.split(b"=", 1) for x in Path("/proc/" + pid + "/environ").read_bytes().split(b"\0") if b"=" in x)
    storage = Path(env.get(b"LOCAL_STORAGE_DIR", str(config.get("LOCAL_STORAGE_DIR") or ROOT / "backend/storage_data").encode()).decode()).expanduser()
    if not storage.is_absolute():
        storage = ROOT / "backend" / storage
    storage = storage.resolve()
    external = storage.exists() and not storage.is_relative_to(ROOT)
    if external:
        archive(DEST / "external-storage.tar.gz", [(storage, "storage")])
    # Preserve ephemeral test evidence before /tmp is cleaned.
    evidence = [(Path(p), Path(p).name) for p in (
        "/tmp/idse-upgrade-ui", "/tmp/idse-upgrade-final-tests.log",
        "/tmp/idse-upgrade-before.json", "/tmp/idse-upgrade-after.json",
        "/tmp/idse-master-revision-ui", "/tmp/idse-master-revision-tests.log",
        "/tmp/idse-master-predeploy.json", "/tmp/idse-master-postdeploy.json",
        "/tmp/sellerbottel-catalog-recovery-report.json") if Path(p).exists()]
    if evidence:
        archive(DEST / "release-evidence.tar.gz", evidence)
    shutil.copy2(ROOT / "AGENT_HANDOVER.md", DEST / "AGENT_HANDOVER.md")
    (DEST / "RESTORE.md").write_text("""# Pemulihan backup IDSE Marketplace

Backup ini memuat rahasia; simpan privat. Baca AGENT_HANDOVER.md terlebih dahulu.

1. Dari direktori backup, jalankan `sha256sum -c SHA256SUMS`.
2. Ekstrak `repository.tar.gz` ke folder staging BARU. Jangan menimpa working tree aktif.
   `.git`, file dirty/untracked, `.env`, build dan aset disertakan; node_modules/venv/cache
   tidak disertakan. Install dependency dari requirements dan package lockfiles pada mesin baru.
3. Pertahankan INVENTORY_ENCRYPTION_KEY, TG_SESSION_KEY dan konfigurasi asli. Jangan
   menampilkan nilai rahasia atau menjalankan bot/payment worker dari staging.
4. Restore `mongodb.archive.gz` hanya ke Mongo terisolasi/kosong terlebih dahulu:
   `mongorestore --uri='<URI_MONGO_STAGING>' --gzip --archive=mongodb.archive.gz --stopOnError`
   Semua koleksi database sellerbottel beserta nilai BSON dan index ada di arsip.
   Jangan arahkan command ini ke production. Pengujian backup sudah memakai container
   tanpa jaringan, TTL monitor mati, dan membandingkan seluruh nilai, index, opsi koleksi.
5. Cocokkan jumlah koleksi/dokumen dan verification.json. Nyalakan TTL normal di produksi
   setelah rencana pemulihan disetujui. Jangan menilai data TTL yang sudah kedaluwarsa
   sebagai bukti dump rusak bila TTL dibiarkan aktif saat verifikasi.
6. runtime-config.tar.gz berisi konfigurasi Nginx/systemd/TLS. Sesuaikan domain/path/IP
   sebelum memasangnya di mesin lain. docker-inspect.json mencatat konfigurasi Mongo.
   Jika ada external-storage.tar.gz, kembalikan isinya ke lokasi storage pada MANIFEST.json.
7. Cutover/restore production memerlukan backup baru kondisi production saat itu dan
   rekonsiliasi transaksi yang masuk setelah snapshot ini. Jangan menjalankan --drop
   terhadap production sebagai bagian dari pengecekan backup.

Pembuatan backup ini tidak melakukan restore/write/reset pada database production.
SHA256SUMS melindungi integritas file, bukan enkripsi atau autentikasi pengirim.
""")
    files = {p.name: p.stat().st_size for p in DEST.iterdir() if p.is_file()}
    save("MANIFEST.json", {"created_at_utc": STAMP, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "path": str(DEST), "repository": str(ROOT), "database": "sellerbottel", "all_database_values": True,
        "collections": len(before), "documents": sum(x["count"] for x in before.values()),
        "counts": {name: data["count"] for name, data in before.items()}, "verified_isolated_restore": True,
        "repository_exclusions": sorted(excluded), "storage_path": str(storage),
        "storage_exists": storage.exists(), "external_storage_archived": external,
        "runtime_paths": [str(p) for p, _ in runtime], "files_bytes": files})
    sums = []
    for path in sorted(DEST.iterdir()):
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            sums.append(digest + "  " + path.name)
    (DEST / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    run(["sha256sum", "--check", "SHA256SUMS"], cwd=DEST, stdout=subprocess.DEVNULL)
    owner = ROOT.stat()
    for path in [DEST.parent, DEST, *DEST.iterdir()]:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
        if os.geteuid() == 0:
            os.chown(path, owner.st_uid, owner.st_gid)
    latest = DEST.parent / "LATEST"
    staged = DEST.parent / (".LATEST-" + STAMP)
    staged.symlink_to(DEST.name)
    staged.replace(latest)
    print(json.dumps({"backup": str(DEST), "collections": len(before),
        "documents": sum(x["count"] for x in before.values()), "verified": True,
        "total_bytes": sum(p.stat().st_size for p in DEST.iterdir() if p.is_file())}), flush=True)


if __name__ == "__main__":
    main()
