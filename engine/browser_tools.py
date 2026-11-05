"""Find the browser the harvesters drive. One place, used by every browser-assisted script.

Order: $CHROME_BIN, then Google Chrome, then Microsoft Edge (Windows paths, then macOS/Linux paths,
then PATH). Returns (path, kind) or (None, None); callers must print `MISSING_BROWSER_HELP` and
exit non-zero instead of carrying on.
"""
import os
import shutil
import sys
from typing import List, Optional, Tuple

MISSING_BROWSER_HELP = (
    "Google Chrome atau Microsoft Edge tidak ditemukan.\n"
    "  - Windows 10/11 biasanya sudah punya Microsoft Edge. Pasang Google Chrome dari https://www.google.com/chrome\n"
    "  - Atau isi variabel lingkungan CHROME_BIN dengan path lengkap chrome.exe / msedge.exe."
)


def _candidates() -> List[Tuple[str, str]]:
    env = os.environ
    c: List[Tuple[str, str]] = []
    if env.get("CHROME_BIN"):
        p = env["CHROME_BIN"]
        c.append((p, "msedge" if "msedge" in p.lower() else "chrome"))
    pf = env.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = env.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    local = env.get("LOCALAPPDATA", "")
    for base in (pf, pf86, local):
        if base:
            c.append((os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"), "chrome"))
    for base in (pf86, pf, local):
        if base:
            c.append((os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"), "msedge"))
    c += [
        ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
        ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "msedge"),
    ]
    for name, kind in (("google-chrome", "chrome"), ("google-chrome-stable", "chrome"), ("chromium", "chrome"),
                       ("chrome", "chrome"), ("msedge", "msedge"), ("microsoft-edge", "msedge")):
        w = shutil.which(name)
        if w:
            c.append((w, kind))
    return c


def find_browser() -> Tuple[Optional[str], Optional[str]]:
    for path, kind in _candidates():
        if path and os.path.exists(path):
            return path, kind
    return None, None


def launch_persistent(playwright, profile_dir: str, headless: bool = False):
    """Open the system browser with its own throw-away profile folder (never the user's profile)."""
    path, _ = find_browser()
    if not path:
        raise RuntimeError(MISSING_BROWSER_HELP)
    os.makedirs(profile_dir, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        executable_path=path,
        headless=headless,
        locale="en-US",
        viewport=None if not headless else {"width": 1280, "height": 800},
        args=["--disable-blink-features=AutomationControlled"],     # --no-sandbox removed: it lowers browser security on your PC
        ignore_default_args=["--enable-automation"],
    )


if __name__ == "__main__":
    p, k = find_browser()
    print(f"{k}: {p}" if p else MISSING_BROWSER_HELP)
    sys.exit(0 if p else 1)
