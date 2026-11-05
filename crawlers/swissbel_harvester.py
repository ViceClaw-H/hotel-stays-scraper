#!/usr/bin/env python3
"""
Swiss-Belhotel International - harvester (Hotelchamp IBE REST API, schema v2).

What it does, per hotel:
  1. reads the hotel's own detail (currency, rooms, rates)           GET /properties/{id}/
  2. reads the lowest price per day                                  GET /properties/{id}/calendar?start=..&end=..
  3. asks the hotel's own tax endpoint whether anything is charged on top of the price, on 2 rates
                                                                     GET /properties/{id}/rooms/{room}/rates/{rate}/taxes?...
  4. stores the verbatim responses as evidence and writes a row ONLY if the server says the price is final.

No tax is ever estimated or added. If the tax endpoint says taxes are charged on top (most Indonesian hotels), fails,
or disagrees between the two rates, the hotel gets NO rows and the reason is printed. The calendar names no room, so the
room is 'UNKNOWN (...)'. The currency is the hotel's own `default_currency`.

Usage:
    python crawlers/swissbel_harvester.py --limit 1          # one-hotel check
    python crawlers/swissbel_harvester.py --hotel "Sydney"   # hotels whose name contains the text
    python crawlers/swissbel_harvester.py                    # every hotel
Exit code 1 when no row was written.
"""
import argparse
import datetime
import gzip
import json
import os
import re
import sqlite3
import ssl
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

from engine.extractors import swissbel as sb_parse  # noqa: E402
from engine.rate_writer import write_rate_batch  # noqa: E402

DB_PATH = os.path.join(BASE_DIR, "hotel_stays.db")
API = "https://ibe-api.hotelchamp.io/api/v1"
GROUP_ID = "9e985649-786b-4a4a-8825-db09e47568fc"
SOURCE_TYPE = "OFFICIAL_SWISSBEL_CRS"
PLACEHOLDER_CCY = {None, "", "XXX", "Unknown", "UNKNOWN"}
DELAY_SECONDS = 0.5
CTX = ssl.create_default_context()
HEADERS = {
    "Origin": "https://www.swiss-belhotel.com",
    "Referer": "https://www.swiss-belhotel.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


class Blocked(RuntimeError):
    """The server refused us (HTTP 403/429): stop and tell the user."""


def http_get(url: str, timeout: int = 20) -> Tuple[Optional[int], Optional[bytes]]:
    """(status, body). status None = network error. Never raises for HTTP errors."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = None
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} from {url.split('?')[0]}")
        return e.code, body
    except Exception:
        return None, None


def get_json(url: str) -> Tuple[Optional[int], Any]:
    status, body = http_get(url)
    if status != 200 or body is None:
        return status, None
    try:
        return status, json.loads(body.decode("utf-8"))
    except ValueError:
        return status, None


def discover_properties(limit: Optional[int] = None, name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    print("[1/3] Menemukan hotel dari Hotelchamp ...")
    props: List[Dict[str, Any]] = []
    page = 1
    while True:
        status, data = get_json(f"{API}/property_groups/{GROUP_ID}?page={page}&paginate=true")
        if not isinstance(data, dict) or not data.get("properties"):
            if status != 200:
                print(f"      [!] halaman {page}: HTTP {status}")
            break
        props.extend(data["properties"])
        if name_filter:
            hit = [p for p in props if name_filter.lower() in (p.get("name") or "").lower()]
            if hit and limit and len(hit) >= limit:
                break
        elif limit and len(props) >= limit:
            break
        if not data.get("has_more_data"):
            break
        page += 1
        time.sleep(DELAY_SECONDS)
    if name_filter:
        props = [p for p in props if name_filter.lower() in (p.get("name") or "").lower()]
    if limit:
        props = props[:limit]
    print(f"      {len(props)} hotel akan diperiksa.")
    return props


def clean_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def match_or_register_hotel(conn: sqlite3.Connection, prop: Dict[str, Any]) -> str:
    """Find the hotel in the catalog, or register it with 'Unknown' city/country/currency. Nothing is guessed."""
    cur = conn.cursor()
    name = (prop.get("name") or "").strip()
    norm = clean_slug(name)
    row = cur.execute("SELECT id FROM hotels WHERE brand='SWISS_BELHOTEL' AND lower(name)=lower(?)", (name,)).fetchone()
    if row:
        return row[0]
    for hid, hname in cur.execute("SELECT id, name FROM hotels WHERE brand='SWISS_BELHOTEL'").fetchall():
        c1 = clean_slug(hname)
        if c1 and norm and (c1 == norm):
            return hid
    canonical = f"swiss_{norm}"[:50].strip("_")
    if cur.execute("SELECT 1 FROM hotels WHERE id=?", (canonical,)).fetchone():
        return canonical
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cols = [r[1] for r in cur.execute("PRAGMA table_info(hotels)")]
    base = {"id": canonical, "brand": "SWISS_BELHOTEL", "name": name, "city": "Unknown", "country": "Unknown",
            "currency": "Unknown", "loyalty_model": "SBEC_BENEFITS", "award_category": "STANDARD", "track_points": 1,
            "official_url": f"https://www.swiss-belhotel.com/hotels/{canonical}", "created_at": now_iso,
            "lifecycle_status": "ACTIVE", "status_updated_at": now_iso}
    use = {k: v for k, v in base.items() if k in cols}
    cur.execute(f"INSERT INTO hotels ({','.join(use)}) VALUES ({','.join('?' * len(use))})", tuple(use.values()))
    conn.commit()
    return canonical


def build_evidence(hotel_id: str, prop_id: str, currency_obj: Any, cal_url: str, cal_response: Any,
                   probes: List[Dict[str, Any]], matched_room: Optional[Dict[str, Any]] = None,
                   matched_rate: Optional[Dict[str, Any]] = None,
                   harvested_at: Optional[str] = None) -> bytes:
    doc = {
        "format": sb_parse.EVIDENCE_FORMAT, "version": sb_parse.EVIDENCE_VERSION,
        "hotel_id": hotel_id, "property_id": prop_id,
        "harvested_at": harvested_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": currency_obj, "calendar_url": cal_url, "calendar_response": cal_response, "tax_probes": probes,
        "matched_room": matched_room, "matched_rate": matched_rate,
    }
    return gzip.compress(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0)


def find_entry_level_room(detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Selects the lowest sequence (entry-level) room, strictly excluding luxury suites/villas/penthouses."""
    rooms = [r for r in (detail.get("rooms") or []) if isinstance(r, dict) and r.get("id")]
    if not rooms:
        return None
    EXCLUDE_KEYWORDS = ("suite", "penthouse", "presidential", "villa", "residence", "apartment")
    candidates = []
    for r in rooms:
        name = str((r.get("name") or {}).get("en-US") or (r.get("name") or {}).get("id-ID") or r.get("name") or "").lower()
        if not any(k in name for k in EXCLUDE_KEYWORDS):
            candidates.append(r)
    pool = candidates if candidates else rooms
    return min(pool, key=lambda r: r.get("sequence") if isinstance(r.get("sequence"), int) else 9999)


def find_standard_rate(detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Selects the standard flexible room-only rate plan."""
    rates = [r for r in (detail.get("rates") or []) if isinstance(r, dict) and r.get("id")]
    if not rates:
        return None
    def rate_rank(rt):
        name = str((rt.get("name") or {}).get("en-US") or (rt.get("name") or {}).get("id-ID") or rt.get("name") or "").lower()
        score = 100
        if "flexible" in name: score -= 40
        if "standard" in name: score -= 30
        if "room only" in name or "kamar saja" in name: score -= 20
        if "breakfast" in name or "sarapan" in name: score += 50
        if "member" in name: score += 40
        if "deal" in name or "promo" in name or "save" in name: score += 30
        return score
    return min(rates, key=rate_rank)


def harvest_property(conn: sqlite3.Connection, prop: Dict[str, Any], days: int, workspace_dir: str = BASE_DIR,
                     sleep=time.sleep) -> Dict[str, Any]:
    prop_id = prop.get("id")
    name = prop.get("name") or "?"
    hotel_id = match_or_register_hotel(conn, prop)
    out = {"hotel_id": hotel_id, "name": name, "written": 0, "reason": None}

    st, detail = get_json(f"{API}/properties/{prop_id}/")
    cur_obj = detail.get("default_currency") if isinstance(detail, dict) else None
    if not isinstance(detail, dict) or not isinstance(cur_obj, dict) or not cur_obj.get("code"):
        out["reason"] = f"detail/mata uang hotel tidak tersedia (HTTP {st})"
        return out
    sleep(DELAY_SECONDS)

    entry_room = find_entry_level_room(detail)
    std_rate = find_standard_rate(detail)
    if not entry_room or not std_rate:
        out["reason"] = "hotel tidak punya kamar/tarif standar valid"
        return out

    start = (date.today() + timedelta(days=1)).isoformat()
    end = (date.today() + timedelta(days=days)).isoformat()
    cal_url = f"{API}/properties/{prop_id}/calendar?start={start}&end={end}"
    st, cal = get_json(cal_url)
    if not isinstance(cal, dict) or not cal:
        out["reason"] = f"kalender kosong/tidak tersedia (HTTP {st})"
        return out
    priced = sorted(d for d, v in cal.items() if isinstance(v, dict) and isinstance(v.get("min_rate"), (int, float)) and v["min_rate"] > 0)
    if not priced:
        out["reason"] = "kalender tidak punya tanggal berharga"
        return out

    room_id = entry_room["id"]
    rate_id = std_rate["id"]
    probes: List[Dict[str, Any]] = []

    check_in = priced[0]
    check_out = (date.fromisoformat(check_in) + timedelta(days=1)).isoformat()
    url = f"{API}/properties/{prop_id}/rooms/{room_id}/rates/{rate_id}/taxes?check_in={check_in}&check_out={check_out}&adults=2"
    st, tj = get_json(url)
    if st != 200 or not isinstance(tj, dict):
        out["reason"] = f"gagal memeriksa pajak kamar standar (HTTP {st})"
        return out

    probes.append({"room_id": room_id, "rate_id": rate_id, "check_in": check_in, "check_out": check_out, "status": st, "response": tj})

    excluded = tj.get("excluded", [])
    if not excluded:
        # Tax-inclusive (e.g. Australia GST): confirm with a second probe
        if len(priced) > 1:
            check_in2 = priced[1]
            check_out2 = (date.fromisoformat(check_in2) + timedelta(days=1)).isoformat()
            url2 = f"{API}/properties/{prop_id}/rooms/{room_id}/rates/{rate_id}/taxes?check_in={check_in2}&check_out={check_out2}&adults=2"
            st2, tj2 = get_json(url2)
            if st2 == 200 and isinstance(tj2, dict):
                probes.append({"room_id": room_id, "rate_id": rate_id, "check_in": check_in2, "check_out": check_out2, "status": st2, "response": tj2})
    else:
        # Tax-excluded (e.g. Indonesia VAT & Service Charge):
        # Probe stay dates to pair each date with exact official server tax cost
        probe_limit = min(len(priced), days, 30)
        for d in priced[1:probe_limit]:
            d_out = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
            url_d = f"{API}/properties/{prop_id}/rooms/{room_id}/rates/{rate_id}/taxes?check_in={d}&check_out={d_out}&adults=2"
            sleep(DELAY_SECONDS)
            st_d, tj_d = get_json(url_d)
            if st_d == 200 and isinstance(tj_d, dict):
                probes.append({"room_id": room_id, "rate_id": rate_id, "check_in": d, "check_out": d_out, "status": st_d, "response": tj_d})

    evidence = build_evidence(hotel_id, prop_id, cur_obj, cal_url, cal, probes, matched_room=entry_room, matched_rate=std_rate)
    rows = sb_parse.parse_evidence(evidence)
    if not rows:
        why = sb_parse.probes_say_price_is_final(probes) or "tidak ada tanggal berharga"
        out["reason"] = f"tidak ada baris disimpan: {why}"
        return out

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    res = write_rate_batch(
        conn, hotel_id=hotel_id, source_type=SOURCE_TYPE, source_url=cal_url, rows=rows,
        evidence_relpath=f"evidence/swissbel/raw/{hotel_id}__{ts}.json.gz", evidence_bytes=evidence,
        evidence_grade="RAW", workspace_dir=workspace_dir,
        notes="Official Swiss-Belhotel Hotelchamp calendar; price final per the hotel's own tax endpoint",
    )
    code = cur_obj["code"].upper()
    row = conn.execute("SELECT currency FROM hotels WHERE id=?", (hotel_id,)).fetchone()
    if row and row[0] in PLACEHOLDER_CCY:
        conn.execute("UPDATE hotels SET currency=? WHERE id=?", (code, hotel_id))
        conn.commit()
    out["written"] = res.written
    if res.rejected:
        out["reason"] = f"{len(res.rejected)} baris ditolak penulis"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Swiss-Belhotel harvester (tanpa tebakan pajak)")
    ap.add_argument("--limit", type=int, default=None, help="jumlah hotel yang diperiksa")
    ap.add_argument("--hotel", default=None, help="hanya hotel yang namanya memuat teks ini")
    ap.add_argument("--days", type=int, default=365, help="berapa hari ke depan (default 365)")
    args = ap.parse_args(argv)

    print("=" * 66)
    print("  SWISS-BELHOTEL - HARVESTER (pajak hanya dari server, tanpa tebakan)")
    print("=" * 66)
    try:
        props = discover_properties(args.limit, args.hotel)
    except Blocked as e:
        print(f"[!] Situs menolak permintaan ({e}). Berhenti; coba lagi nanti.")
        return 1
    if not props:
        print("[!] Tidak ada hotel ditemukan.")
        return 1

    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    total = 0
    print(f"\n[2/3] Mengambil harga ({args.days} hari) ...")
    try:
        for i, p in enumerate(props, 1):
            r = harvest_property(conn, p, args.days)
            total += r["written"]
            if r["written"]:
                print(f"[{i}/{len(props)}] {r['name']} -> {r['written']} baris" + (f" ({r['reason']})" if r["reason"] else ""), flush=True)
            else:
                print(f"[{i}/{len(props)}] {r['name']} -> 0 baris: {r['reason']}", flush=True)
            time.sleep(DELAY_SECONDS)
    except Blocked as e:
        print(f"[!] Situs menolak permintaan ({e}). Berhenti.")
    finally:
        conn.close()
    print(f"\n[3/3] SELESAI: {total} baris ditulis.")
    if total == 0:
        print("[!] 0 baris: tidak ada hotel yang membuktikan harganya sudah final. Tidak ada yang dikarang.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
