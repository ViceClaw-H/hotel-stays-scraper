#!/usr/bin/env python3
"""Check ONE hotel per chain script, end to end, in a throw-away copy of the project.

    python tools/check_one_hotel.py swissbel            # one chain
    python tools/check_one_hotel.py all                 # every chain, one hotel each (opens Chrome for some chains)
    python tools/check_one_hotel.py swissbel --hotel Sydney
    python tools/check_one_hotel.py --list

For each chain it: copies the project (without evidence, Python runtime and html) to a temp folder, runs the chain's own
script there with a one-hotel limit, and then looks at what the script wrote:

  * did it write any row at all, and if not, WHY (the script's own last lines are shown);
  * the cryptographic evidence audit (byte parity + value replay) of the new rows;
  * the honesty audit (engine/honesty_audit.py): script-added keys in the evidence, rows not tax inclusive, missing
    currency, forbidden words, too-uniform prices, a constant tax ratio across hotels.

Your real database and evidence folder are never touched. Verdict per chain: PASS, WARN, FAIL or NO ROWS.
Exit code 0 only when every chain checked is PASS or WARN.
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# chain -> (script, args for ONE hotel, needs a visible Chrome?)
CHAINS: Dict[str, Tuple[str, List[str], bool]] = {
    "swissbel": ("crawlers/swissbel_harvester.py", ["--limit", "1"], False),
    "bestwestern": ("crawlers/bestwestern_harvester.py", ["--limit", "1", "--months", "1"], False),
    "radisson": ("crawlers/radisson_harvester.py", ["--limit", "1", "--dates", "4"], True),
    "gha": ("crawlers/gha_harvester.py", ["--limit", "1", "--dates", "4"], True),
    "accor": ("crawlers/accor_fast_harvester.py", ["--limit", "1"], False),
    "wyndham": ("crawlers/wyndham_stream_harvester.py", ["--limit", "1"], False),
    "ihg": ("crawlers/ihg_calendar_harvester.py", ["--limit", "1"], False),
    "shangrila": ("crawlers/shangrila_master_365_and_percentiles_crawler.py", ["--limit", "1"], False),
    "langham": ("crawlers/langham_harvester.py", ["--limit", "1"], False),
    "hilton": ("crawlers/hilton_fast_harvester.py", ["--limit", "1", "--months", "1"], True),
    "marriott": ("crawlers/marriott_fast_harvester.py", ["--limit", "1", "--months", "1"], True),
    "hyatt": ("crawlers/hyatt_avail_days_harvester.py", ["--limit", "1", "--months", "1"], True),
}
HOTEL_FLAG = {"swissbel": "--hotel", "langham": "--hotel", "wyndham": "--hotel", "ihg": "--hotel", "shangrila": "--hotel", "radisson": "--hotel", "gha": "--hotel",
              "hilton": "--ctyhocn", "marriott": "--marsha", "hyatt": "--spirit"}
SKIP_DIRS = {
    "portable_python", "evidence", "__pycache__", ".git", "assets",
    "Claude's Advice", ".claude", "scratch", "logs", "temp_chrome_test",
    "SS Hotel New PC", "audit_output", ".pytest_cache"
}
SKIP_SUFFIX = (".html", ".pyc", ".zip")


def make_workspace(project_root: str, tmp_root: str) -> str:
    ws = os.path.join(tmp_root, "ws")

    def ignore(d, names):
        return {n for n in names if n in SKIP_DIRS or n == "browser_profile" or n.endswith(SKIP_SUFFIX)}

    shutil.copytree(project_root, ws, ignore=ignore)
    os.makedirs(os.path.join(ws, "evidence"), exist_ok=True)
    return ws


def row_ids(db_path: str) -> set:
    if not os.path.exists(db_path):
        return set()
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {r[0] for r in c.execute("SELECT id FROM rate_records")}
    except sqlite3.Error:
        return set()
    finally:
        c.close()


def run_chain(name: str, project_root: str = ROOT, hotel: Optional[str] = None, timeout: int = 300,
              script: Optional[str] = None, args: Optional[List[str]] = None, python: Optional[str] = None,
              keep: bool = False, say=print) -> Tuple[str, List[str]]:
    """Returns (verdict, detail lines). verdict in PASS / WARN / FAIL / NO ROWS / ERROR."""
    from engine.honesty_audit import audit_rows, verdict as audit_verdict

    if script is None:
        if name not in CHAINS:
            return "ERROR", [f"rantai '{name}' tidak dikenal. Pilihan: {', '.join(CHAINS)}"]
        script, base_args, _ = CHAINS[name]
        args = list(base_args)
        if hotel:
            flag = HOTEL_FLAG.get(name)
            if not flag:
                return "ERROR", [f"rantai '{name}' tidak mendukung --hotel; edit CHAINS di tools/check_one_hotel.py"]
            if "--limit" in args:
                i = args.index("--limit")
                del args[i:i + 2]
            args += [flag, hotel]
    args = args or []
    lines: List[str] = []
    tmp = tempfile.mkdtemp(prefix=f"check_{name}_")
    try:
        ws = make_workspace(project_root, tmp)
        db = os.path.join(ws, "hotel_stays.db")
        before = row_ids(db)
        cmd = [python or sys.executable, os.path.join(ws, script)] + args
        say(f"   menjalankan: {os.path.basename(script)} {' '.join(args)}   (maks {timeout}s)")
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            out, code = (p.stdout or "") + (p.stderr or ""), p.returncode
        except subprocess.TimeoutExpired as e:
            out, code = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")), -9
            lines.append(f"skrip melewati batas waktu {timeout}s dan dihentikan")
        tail = [l for l in out.strip().splitlines() if l.strip()][-6:]
        lines.append(f"kode keluar {code}, {time.time() - t0:.0f} detik. Baris terakhir skrip:")
        lines += [f"     | {l[:160]}" for l in tail]

        new = row_ids(db) - before
        if not new:
            lines.append("TIDAK ADA BARIS baru ditulis. (Lihat alasan skrip di atas.)")
            return "NO ROWS", lines
        lines.append(f"{len(new)} baris baru ditulis.")
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            findings = audit_rows(conn, ws, new)
        finally:
            conn.close()
        try:
            from engine.verify_evidence_integrity import run_evidence_audit
            import contextlib
            import io
            buf = io.StringIO()
            here = os.getcwd()
            os.chdir(ws)                     # the verifier resolves evidence paths relative to the current folder
            try:
                with contextlib.redirect_stdout(buf):
                    rep = run_evidence_audit(db)
            finally:
                os.chdir(here)
            if not rep.get("audit_passed"):
                findings.append(__import__("engine.honesty_audit", fromlist=["Finding"]).Finding("FAIL", "EVIDENCE_AUDIT", "audit bukti kriptografis GAGAL (lihat tools/check_readiness.py)"))
        except Exception as e:
            findings.append(__import__("engine.honesty_audit", fromlist=["Finding"]).Finding("WARN", "EVIDENCE_AUDIT", f"audit bukti tidak bisa dijalankan: {type(e).__name__}"))
        lines += [f"   {f}" for f in findings]
        return audit_verdict(findings), lines
    finally:
        if keep:
            lines.append(f"(folder sementara disimpan: {tmp})")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cek 1 hotel per rantai di salinan sementara")
    ap.add_argument("chain", nargs="?", help="nama rantai atau 'all'")
    ap.add_argument("--hotel", help="hotel tertentu (jika didukung rantai itu)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--keep", action="store_true", help="simpan folder sementara untuk diperiksa")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list or not a.chain:
        print("Rantai yang bisa dicek:")
        for k, (s, args, vis) in CHAINS.items():
            print(f"  {k:12s} {os.path.basename(s)} {' '.join(args)}{'   [membuka Chrome]' if vis else ''}")
        return 0 if a.list else 2
    names = list(CHAINS) if a.chain == "all" else [a.chain]
    results = []
    for n in names:
        print(f"\n=== {n} " + "=" * (60 - len(n)))
        v, lines = run_chain(n, hotel=a.hotel, timeout=a.timeout, keep=a.keep)
        for l in lines:
            print(l)
        print(f"--> {n}: {v}")
        results.append((n, v))
    print("\n" + "=" * 66 + "\nRINGKASAN")
    for n, v in results:
        print(f"  {n:12s} {v}")
    return 0 if all(v in ("PASS", "WARN") for _, v in results) else 1


if __name__ == "__main__":
    sys.exit(main())
