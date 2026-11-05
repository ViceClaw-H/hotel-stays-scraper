#!/usr/bin/env python3
"""
Master Concurrent Harvester Orchestrator (12 Chains)
Runs all 12 chains concurrently in isolated background subprocesses.
Monitors progress in a single unified dashboard without cluttering the screen.
"""

import os
import sys
import time
import subprocess
import signal

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# Select Python binary (portable if present, else sys.executable)
PORTABLE_PY = os.path.join(ROOT_DIR, "portable_python", "python.exe")
PY_BIN = PORTABLE_PY if os.path.exists(PORTABLE_PY) else sys.executable

CHAINS = [
    {
        "id": "accor",
        "name": "Accor (ALL)",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "accor_fast_harvester.py"), "--num-workers", "1", "--days", "120"]
    },
    {
        "id": "ihg",
        "name": "IHG (IHG One Rewards)",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "ihg_calendar_harvester.py"), "--workers", "3", "--rate", "1.5"]
    },
    {
        "id": "hilton",
        "name": "Hilton Honors",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "hilton_fast_harvester.py"), "--workers", "1", "--months", "3", "--offscreen"]
    },
    {
        "id": "marriott",
        "name": "Marriott Bonvoy",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "marriott_fast_harvester.py"), "--workers", "1", "--months", "12"]
    },
    {
        "id": "hyatt",
        "name": "World of Hyatt",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "hyatt_avail_days_harvester.py"), "--workers", "2", "--months", "12"]
    },
    {
        "id": "wyndham",
        "name": "Wyndham Rewards",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "wyndham_stream_harvester.py"), "--workers", "4"]
    },
    {
        "id": "swissbel",
        "name": "Swiss-Belhotel",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "swissbel_harvester.py")]
    },
    {
        "id": "radisson",
        "name": "Radisson Hotel Group",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "radisson_harvester.py")]
    },
    {
        "id": "bestwestern",
        "name": "Best Western",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "bestwestern_harvester.py")]
    },
    {
        "id": "shangrila",
        "name": "Shangri-La Circle",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "shangrila_master_365_and_percentiles_crawler.py")]
    },
    {
        "id": "langham",
        "name": "Langham (1865)",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "langham_harvester.py")]
    },
    {
        "id": "gha",
        "name": "GHA DISCOVERY",
        "cmd": [PY_BIN, os.path.join(ROOT_DIR, "crawlers", "gha_harvester.py")]
    }
]

START_STAGGER_SECONDS = 12     # pause between launches


def format_seconds(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def get_last_log_line(log_path):
    if not os.path.exists(log_path):
        return ""
    try:
        with open(log_path, "rb") as f:
            f.seek(max(0, os.path.getsize(log_path) - 1024))
            lines = f.read().decode("utf-8", errors="ignore").splitlines()
            for line in reversed(lines):
                s = line.strip()
                if s and not s.startswith("="):
                    return s[:45]
    except Exception:
        pass
    return ""

def main():
    print("=" * 80)
    print("      ANTIGRAVITY UNIFIED HOTEL HARVESTER - MASTER CONCURRENT RUNNER")
    print("                  PORTFOLIO: 12 GLOBAL HOTEL CHAINS")
    print("=" * 80)
    print(f"Python Runtime : {PY_BIN}")
    print(f"Logs Directory : {LOGS_DIR}")
    print(f"Working Dir    : {ROOT_DIR}")
    print("=" * 80)
    print("\nMeluncurkan 12 chain secara paralel...\n")

    processes = []
    log_files = []
    start_times = {}

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW

    for n_started, item in enumerate(CHAINS):
        if n_started:
            time.sleep(START_STAGGER_SECONDS)     # not 12 chains at the same second from one IP (IHG/Hilton were blocked that way)
        cid = item["id"]
        cname = item["name"]
        log_file_path = os.path.join(LOGS_DIR, f"{cid}.log")
        fout = open(log_file_path, "w", encoding="utf-8", buffering=1)
        log_files.append(fout)

        proc = subprocess.Popen(
            item["cmd"],
            cwd=ROOT_DIR,
            stdout=fout,
            stderr=subprocess.STDOUT,
            creationflags=creationflags
        )
        processes.append((item, proc, log_file_path))
        start_times[cid] = time.time()
        print(f"  [+] Started: {cname.ljust(24)} (PID: {proc.pid}) -> {os.path.basename(log_file_path)}")

    print("\n" + "=" * 80)
    print("Seluruh proses telah berjalan di background!")
    print("Dashboard status diperbarui setiap 2 detik. Tekan Ctrl+C untuk stop.")
    print("=" * 80 + "\n")

    try:
        while True:
            all_done = True
            time.sleep(2.0)

            # Move cursor up or print status
            lines_output = []
            lines_output.append(f"STATUS UPDATE [{time.strftime('%Y-%m-%d %H:%M:%S')}]:")
            lines_output.append("-" * 80)

            for idx, (item, proc, log_path) in enumerate(processes, 1):
                cid = item["id"]
                cname = item["name"]
                elapsed = format_seconds(time.time() - start_times[cid])
                ret = proc.poll()
                last_line = get_last_log_line(log_path)

                if ret is None:
                    all_done = False
                    status_str = f"[RUNNING] {elapsed}"
                elif ret == 0:
                    status_str = f"[DONE OK] {elapsed}"
                elif ret == 2:
                    status_str = f"[PARTIAL] {elapsed}"      # the script says it stopped early / covered too little: see its log
                else:
                    status_str = f"[ERROR {ret}] {elapsed}"

                line_display = f" {idx:2d}. {cname.ljust(22)}: {status_str.ljust(18)} | {last_line}"
                lines_output.append(line_display)

            lines_output.append("-" * 80)
            
            # Print update (clear screen on console)
            os.system("cls" if sys.platform == "win32" else "clear")
            print("=" * 80)
            print("      ANTIGRAVITY UNIFIED HOTEL HARVESTER - CONCURRENT LIVE MONITOR")
            print("=" * 80)
            for l in lines_output:
                print(l)
            print("Tekan Ctrl+C untuk menghentikan seluruh scraper.")

            if all_done:
                codes = {it["id"]: p.poll() for it, p, _ in processes}
                n_ok = sum(1 for c in codes.values() if c == 0)
                n_part = sum(1 for c in codes.values() if c == 2)
                n_err = len(codes) - n_ok - n_part
                summary = [f"Ringkasan akhir {time.strftime('%Y-%m-%d %H:%M:%S')}: {n_ok} selesai, {n_part} PARSIAL (berhenti dini), {n_err} error."]
                summary += [f"  {it['name']:24s} kode keluar {codes[it['id']]} -> {'OK' if codes[it['id']] == 0 else ('PARSIAL' if codes[it['id']] == 2 else 'ERROR')}"
                            for it, _, _ in processes]
                summary.append("Kode keluar 0 berarti skrip selesai tanpa kegagalan yang ia ketahui; PARSIAL/ERROR berarti sebagian katalog belum terambil. Lihat logs/<rantai>.log.")
                try:
                    with open(os.path.join(LOGS_DIR, "_RINGKASAN_AKHIR.txt"), "w", encoding="utf-8") as sf:
                        sf.write("\n".join(summary) + "\n")
                except OSError:
                    pass
                print("\n" + "=" * 80)
                print("\n".join(summary))
                print(f"Hasil log lengkap tersimpan di folder: {LOGS_DIR}")
                print("=" * 80)
                break

    except KeyboardInterrupt:
        print("\n\n[INTERRUPT] Menghentikan seluruh proses background dan worker...")
        for item, proc, _ in processes:
            if proc.poll() is None:
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        proc.terminate()
                except Exception:
                    pass
        print("[DONE] Seluruh proses dan background worker telah dihentikan secara aman.")
    finally:
        for f in log_files:
            try:
                f.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
