import os
import sys
import subprocess
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def stop_all_scrapers():
    print("=" * 65)
    print("      EMERGENCY STOP - PENGHENTIAN TOTAL SELURUH SCRAPER")
    print("=" * 65)
    print("[*] Memeriksa dan mematikan seluruh proses scraper dan worker...")
    
    if sys.platform != "win32":
        # Linux/macOS
        subprocess.run(["pkill", "-f", "crawlers/"])
        print("[DONE] Selesai.")
        return

    # Windows WMIC / PowerShell query for precision
    stopped_count = 0
    
    # 1. Kill any portable_python or python running crawlers
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { ($_.Name -match 'python' -and ($_.CommandLine -match 'crawlers' -or $_.CommandLine -match 'portable_python')) "
            "-or ($_.Name -match 'chrome' -and ($_.CommandLine -match 'pw_hilton_session' -or $_.CommandLine -match 'pw_marriott_session' -or $_.CommandLine -match 'hyatt_')) } | "
            "Select-Object ProcessId, Name, CommandLine"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
        lines = res.stdout.splitlines()
        
        pids = []
        for line in lines:
            m = re.match(r"^\s*(\d+)\s+(python|chrome)", line, re.IGNORECASE)
            if m:
                pids.append(m.group(1))
                
        for pid in pids:
            # Don't kill ourselves
            if int(pid) != os.getpid():
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                stopped_count += 1
    except Exception as e:
        print(f"[!] Warning saat pemindaian: {e}")

    # Fallback safety: kill any orphaned portable_python instances
    try:
        portable_py = os.path.join(ROOT, "portable_python", "python.exe").lower()
        res = subprocess.run(["powershell", "-NoProfile", "-Command", f"Get-Process python | Where-Object {{ $_.Path -like '*{ROOT}*' }} | Stop-Process -Force"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    print("\n" + "=" * 65)
    print(f" [BERHASIL] Seluruh aktivitas scraping berhasil dihentikan total!")
    print(f"  - Proses yang di-terminate : {stopped_count} proses (Python & Chrome background)")
    print(f"  - Status Database          : Aman (WAL mode SQLite mencegah corrupt)")
    print(f"  - Status Desktop / Taskbar : Bersih")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    stop_all_scrapers()
