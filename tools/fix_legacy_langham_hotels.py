#!/usr/bin/env python3
"""Membereskan hotel Langham yang didaftarkan skrip LAMA (kota/negara 'Global', mata uang 'USD' sebagai pengisi).

    python tools/fix_legacy_langham_hotels.py            # hanya melaporkan (tidak mengubah apa pun)
    python tools/fix_legacy_langham_hotels.py --apply    # membuat salinan cadangan database, lalu memperbaiki

Yang diubah (hanya hotel brand LANGHAM):
  * city/country 'Global'  -> 'Unknown'   (tidak ada yang ditebak)
  * hotels.currency        -> mata uang yang benar-benar tercatat di rate_records hotel itu bila HANYA ada satu;
                              kalau tidak ada/lebih dari satu: mata uang lama DIPERTAHANKAN bila kode ISO yang sah
                              (v9f; v9e menggantinya dengan 'Unknown'), hanya pengisi seperti 'Global' -> 'Unknown'
Baris harga (rate_records) TIDAK dihapus atau diubah: nilainya berasal dari respons server beserta mata uangnya.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_iso(code) -> bool:
    return isinstance(code, str) and len(code) == 3 and code.isalpha() and code.isupper()


def plan(conn):
    out = []
    for hid, city, country, cur in conn.execute("SELECT id, city, country, currency FROM hotels WHERE brand='LANGHAM'").fetchall():
        seen = [r[0] for r in conn.execute(
            "SELECT DISTINCT r.raw_currency FROM rate_records r JOIN room_categories rc ON rc.id = r.room_id WHERE rc.hotel_id = ? AND r.raw_currency IS NOT NULL", (hid,))]
        if len(seen) == 1:
            new_cur = seen[0]                      # the server's own currency for this hotel's prices
        elif _is_iso(cur):
            new_cur = cur                          # v9f: never overwrite a valid currency with 'Unknown'
        else:
            new_cur = "Unknown"                    # only a placeholder (e.g. 'Global') becomes 'Unknown'
        new_city = "Unknown" if city == "Global" else city
        new_country = "Unknown" if country == "Global" else country
        if (new_city, new_country, new_cur) != (city, country, cur):
            out.append((hid, (city, country, cur), (new_city, new_country, new_cur)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=os.path.join(ROOT, "hotel_stays.db"))
    a = ap.parse_args(argv)
    conn = sqlite3.connect(a.db)
    try:
        changes = plan(conn)
    finally:
        conn.close()                               # v9f: closed before any copy (Windows locks open files)
    print(f"{len(changes)} hotel Langham perlu diperbaiki.")
    for hid, old, new in changes[:15]:
        print(f"  {hid}: {old} -> {new}")
    if not a.apply:
        print("(hanya laporan; jalankan dengan --apply untuk memperbaiki)")
        return 0
    if changes:
        backup = f"{a.db}.bak_{time.strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(a.db, backup)
        print(f"Cadangan database: {backup}")
        conn = sqlite3.connect(a.db)
        try:
            for hid, _old, (city, country, cur) in changes:
                conn.execute("UPDATE hotels SET city=?, country=?, currency=? WHERE id=?", (city, country, cur, hid))
            conn.commit()
        finally:
            conn.close()
    print("Selesai.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
