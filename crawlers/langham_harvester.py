#!/usr/bin/env python3
"""Langham / Cordis / Eaton / Ying'nFlo - kalender harga resmi (SynXis), tanpa tebakan.

Sumber : POST https://reservations.brilliantbylangham.com/api/booking/calendar_availability
Isi    : per tanggal {date, amount (sebelum pajak), amountWithTax (setelah pajak), currency}. Yang disimpan = amountWithTax APA ADANYA,
         dengan mata uang dari respons yang sama. Tidak ada kurs, tidak ada mata uang bawaan, tidak ada pajak yang dihitung sendiri.
Bukti  : respons server disimpan apa adanya; baris dibentuk oleh extractor murni yang sama dengan verifikasi (engine/extractors/langham.py).

    python crawlers/langham_harvester.py --limit 1            # satu hotel
    python crawlers/langham_harvester.py --hotel london       # nama memuat teks
    python crawlers/langham_harvester.py --months 3           # 3 jendela x 31 hari
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine.currency_source import is_iso                       # noqa: E402
from engine.extractors import langham as lang_parse            # noqa: E402
from engine.rate_writer import write_rate_batch                # noqa: E402

DB_PATH = os.path.join(BASE_DIR, "hotel_stays.db")
URL = "https://reservations.brilliantbylangham.com/api/booking/calendar_availability"
SOURCE_TYPE = "OFFICIAL_LANGHAM_SYNXIS"
WINDOW_DAYS = 30
DELAY_SECONDS = 0.4
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://reservations.brilliantbylangham.com",
    "Referer": "https://reservations.brilliantbylangham.com/",
}


class Blocked(RuntimeError):
    """The server refused us (HTTP 403/429): stop and tell the user."""


def post_json(payload: Dict[str, Any], timeout: int = 25) -> Tuple[Optional[int], Optional[Any], str]:
    """(status, parsed json or None, reason). Uses the browser-impersonating client when it is bundled, else urllib."""
    body = json.dumps(payload).encode()
    try:
        try:
            from curl_cffi import requests as cr
            r = cr.post(URL, data=body, headers=HEADERS, impersonate="chrome124", timeout=timeout)
            status, text = r.status_code, r.text
        except ImportError:
            req = urllib.request.Request(URL, data=body, headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, text = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, ""
    except Exception as e:                       # network failure: reported, not swallowed
        return None, None, f"{type(e).__name__}: {e}"
    if status in (403, 429):
        raise Blocked(f"HTTP {status}")
    if status != 200:
        return status, None, f"HTTP {status}"
    try:
        return status, json.loads(text), ""
    except ValueError:
        return status, None, "respons bukan JSON"


def load_roster(limit: Optional[int] = None, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    seen, out = set(), []
    base = os.path.join(BASE_DIR, "catalogs", "langham")
    for fname, key_id, key_name in (("langham_3tier_resolved.json", "synxis_hotel_id", "name"), ("langham_master_crs_roster.json", "synxis_id", "name")):
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            continue
        for r in json.load(open(path, encoding="utf-8")):
            sid = r.get(key_id)
            if not sid or sid in seen:
                continue
            if fname.endswith("crs_roster.json") and not r.get("is_live"):
                continue
            seen.add(sid)
            out.append({"synxis_id": str(sid), "name": r.get(key_name) or f"Langham {sid}"})
    if name_filter:
        out = [p for p in out if name_filter.lower() in p["name"].lower()]
    return out[:limit] if limit else out


def clean_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def match_or_register_hotel(conn: sqlite3.Connection, prop: Dict[str, Any]) -> str:
    """Find the hotel in the catalog, or register it with 'Unknown' city/country/currency. Nothing is guessed."""
    cur = conn.cursor()
    name = prop["name"].strip()
    norm = clean_slug(name)
    for hid, hname in cur.execute("SELECT id, name FROM hotels WHERE brand='LANGHAM'").fetchall():
        if clean_slug(hname) == norm:
            return hid
    canonical = f"lang_{norm}"[:50].strip("_")
    if cur.execute("SELECT 1 FROM hotels WHERE id=?", (canonical,)).fetchone():
        return canonical
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(hotels)")]
    base = {"id": canonical, "brand": "LANGHAM", "name": name, "city": "Unknown", "country": "Unknown", "currency": "Unknown",
            "loyalty_model": "FIXED_REBATE", "award_category": "Brilliant by Langham", "track_points": 1,
            "official_url": f"https://reservations.brilliantbylangham.com/?hotel={prop['synxis_id']}&chain=10316",
            "created_at": now_iso, "lifecycle_status": "ACTIVE", "status_updated_at": now_iso}
    use = {k: v for k, v in base.items() if k in cols}
    cur.execute(f"INSERT INTO hotels ({','.join(use)}) VALUES ({','.join('?' * len(use))})", tuple(use.values()))
    conn.commit()
    return canonical


def fetch_calendar(synxis_id: str, months: int, sleep=time.sleep) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(verbatim calendar day objects, problems). A window that fails is REPORTED, not skipped silently."""
    days: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    start = date.today() + timedelta(days=1)
    for i in range(months):
        end = start + timedelta(days=WINDOW_DAYS)
        status, js, why = post_json({"hotelCode": str(synxis_id), "startDate": start.isoformat(), "endDate": end.isoformat(),
                                     "adults": 1, "children": 0, "childAges": []})
        cal = ((js or {}).get("data") or {}).get("calendar") if isinstance(js, dict) else None
        if not isinstance(cal, list):
            problems.append(f"{start}..{end}: {why or 'tidak ada kalender'}")
        else:
            for d in cal:
                if isinstance(d, dict) and d.get("date"):
                    days[d["date"]] = d
        start = end + timedelta(days=1)
        sleep(DELAY_SECONDS)
    return [days[k] for k in sorted(days)], problems


def build_evidence(hotel_id: str, synxis_id: str, calendar: List[Dict[str, Any]]) -> bytes:
    return json.dumps({
        "format": lang_parse.EVIDENCE_FORMAT, "version": lang_parse.EVIDENCE_VERSION, "hotel_id": hotel_id, "synxis_id": str(synxis_id),
        "source_url": URL, "harvested_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "tax_inclusive": 1, "calendar": calendar,
    }, ensure_ascii=False).encode("utf-8")


def harvest_property(conn: sqlite3.Connection, prop: Dict[str, Any], months: int, workspace_dir: str = BASE_DIR,
                     sleep=time.sleep) -> Dict[str, Any]:
    hotel_id = match_or_register_hotel(conn, prop)
    out = {"hotel_id": hotel_id, "name": prop["name"], "written": 0, "reason": None}
    calendar, problems = fetch_calendar(prop["synxis_id"], months, sleep)
    if problems:
        out["reason"] = f"{len(problems)} jendela gagal ({problems[0]})"
    if not calendar:
        out["reason"] = out["reason"] or "kalender kosong"
        return out
    evidence = build_evidence(hotel_id, prop["synxis_id"], calendar)
    rows = lang_parse.parse_evidence(evidence)
    if not rows:
        out["reason"] = (out["reason"] + "; " if out["reason"] else "") + "tidak ada tanggal berharga (atau mata uang tidak disebut)"
        return out
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    res = write_rate_batch(
        conn, hotel_id=hotel_id, source_type=SOURCE_TYPE, source_url=URL, rows=rows,
        evidence_relpath=f"evidence/langham/calendar/{hotel_id}__{ts}.json", evidence_bytes=evidence,
        evidence_grade="RAW", workspace_dir=workspace_dir,
        notes="Official Langham SynXis calendar; amountWithTax as given by the server",
    )
    ccy = sorted({r.currency for r in rows if r.currency})
    row = conn.execute("SELECT currency FROM hotels WHERE id=?", (hotel_id,)).fetchone()
    if row and not is_iso(row[0]) and len(ccy) == 1:
        conn.execute("UPDATE hotels SET currency=? WHERE id=?", (ccy[0], hotel_id))
        conn.commit()
    out["written"] = res.written
    if res.rejected:
        out["reason"] = f"{len(res.rejected)} baris ditolak penulis"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Langham harvester (tanpa kurs/mata uang bawaan)")
    ap.add_argument("--limit", type=int, default=None, help="jumlah hotel")
    ap.add_argument("--hotel", default=None, help="hanya hotel yang namanya memuat teks ini")
    ap.add_argument("--months", type=int, default=12, help="jumlah jendela 31 hari (default 12 = ~1 tahun)")
    args = ap.parse_args(argv)
    print("=" * 66)
    print("  LANGHAM - KALENDER HARGA RESMI (amountWithTax apa adanya, tanpa kurs)")
    print("=" * 66)
    props = load_roster(args.limit, args.hotel)
    if not props:
        print("[!] Tidak ada hotel di roster.")
        return 1
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    total = 0
    try:
        for i, p in enumerate(props, 1):
            r = harvest_property(conn, p, args.months)
            total += r["written"]
            print(f"[{i}/{len(props)}] {r['name']} -> {r['written']} baris" + (f" ({r['reason']})" if r["reason"] else ""), flush=True)
    except Blocked as e:
        print(f"[!] Situs menolak permintaan ({e}). Berhenti; coba lagi nanti.")
    finally:
        conn.close()
    print(f"\nSELESAI: {total} baris ditulis.")
    if total == 0:
        print("[!] 0 baris. Tidak ada yang dikarang.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
