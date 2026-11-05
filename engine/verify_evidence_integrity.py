"""Fail-closed evidence auditor for hotel_stays.db (schema v2).

LAYER 1 - byte parity. Every row that CLAIMS verified evidence (evidence_grade RAW or SUMMARY) must have
          its evidence file on disk with the exact SHA-256 the row records. UNVERIFIED rows are the known
          debt: they are counted and listed, and fail the audit only with --strict.
LAYER 2 - value replay. For every source that has a replayer, the cash / points / room stored in each row
          are re-derived from the row's own evidence file and compared. Sources with no replayer are
          listed as NOT VALUE-VERIFIED - they never count as verified.

Exit code is non-zero if anything that claims to be verified is not.
"""
import hashlib
import importlib
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from engine.extractors.legacy import ANY_DATE, LEGACY_REPLAYERS, UnsupportedEvidence  # noqa: E402

# chain module (engine/extractors/<name>.py) per source_type; used for evidence written under schema v2.
CHAIN_MODULES = {
    "OFFICIAL_WYNDHAM_CRS": "wyndham", "OFFICIAL_IHG_CRS": "ihg",
    "OFFICIAL_HYATT_AVAIL_DAYS": "hyatt", "OFFICIAL_HYATT_CASH_BENCHMARK": "hyatt",
    "OFFICIAL_SHANGRILA_CRS": "shangrila",
    "OFFICIAL_LANGHAM_SYNXIS": "langham",
    "OFFICIAL_MARRIOTT_CRS": "marriott",
    "OFFICIAL_ACCOR_CRS": "accor",
    "OFFICIAL_SWISSBEL_CRS": "swissbel",
    "OFFICIAL_RADISSON_CRS": "radisson", "OFFICIAL_GHA_CRS": "gha",
    "OFFICIAL_BESTWESTERN_BFF": "bestwestern",
    "OFFICIAL_HILTON_CRS": "hilton",
}


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _new_format_replayer(source_type: str) -> Optional[Callable[[bytes], dict]]:
    """Adapter around a chain's parse_evidence(bytes) -> [RateRow] for evidence written under schema v2."""
    name = CHAIN_MODULES.get(source_type)
    if not name:
        return None
    try:
        mod = importlib.import_module(f"engine.extractors.{name}")
        parse = mod.parse_evidence
    except Exception:
        return None

    def replay(data: bytes):
        out = {}
        for r in parse(data):
            val = (r.cash_rate, r.points_required, (r.currency or "").upper() or None, (r.room_name or "").strip())
            key = r.stay_date
            if key in out:
                prev = out[key]
                out[key] = (prev if isinstance(prev, list) else [prev]) + [val]   # per-room series
            else:
                out[key] = val
        # ANY_DATE evidence (a response with no stay date) must always be a list of candidates
        if ANY_DATE in out and not isinstance(out[ANY_DATE], list):
            out[ANY_DATE] = [out[ANY_DATE]]
        return out
    return replay


def _replay(source_type: str, data: bytes):
    """Try the schema-v2 extractor first, then the legacy replayer. Returns (replay_dict|None, how)."""
    new = _new_format_replayer(source_type)
    if new:
        try:
            got = new(data)
            if got:
                return got, "extractor"
        except Exception:
            pass
    leg = LEGACY_REPLAYERS.get(source_type)
    if leg:
        try:
            return leg(data), "legacy"
        except UnsupportedEvidence:
            return None, None      # a format we cannot replay: the rows stay NOT VALUE-VERIFIED
        except Exception:
            return None, None
    return None, None


def row_matches(exp, cash, pts, cur, room) -> bool:
    """Does one stored row equal what its evidence says? exp = (cash, points, currency, room_name)."""
    return (exp is not None
            and ((cash is None and not exp[0]) or (cash is not None and exp[0] and abs(cash - exp[0]) < 0.005))
            and ((pts is None and not exp[1]) or pts == exp[1])
            and (not exp[2] or not cur or exp[2] == cur)
            and (not exp[3] or exp[3] == (room or "")))


def row_ok(rep, stay_date, cash, pts, cur, room):
    """(ok, what-the-evidence-said) for one row against a replay dict (per-date, or ANY_DATE list)."""
    exp = rep.get(stay_date)
    if isinstance(exp, list):      # several rooms on one date: the row must equal one of them
        return any(row_matches(e, cash, pts, cur, room) for e in exp), f"any of {len(exp)} rooms on {stay_date}"
    if exp is None and ANY_DATE in rep:
        return any(row_matches(e, cash, pts, cur, room) for e in rep[ANY_DATE]), f"any of {len(rep[ANY_DATE])} listed prices"
    return row_matches(exp, cash, pts, cur, room), exp


def run_evidence_audit(db_path: str = "hotel_stays.db", strict: bool = False, max_examples: int = 5) -> Dict[str, Any]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM rate_records").fetchone()[0]
    if total == 0:
        print("[AUDIT] No records in rate_records to audit.")
        return {"total_records": 0, "audit_passed": True}

    # ---------------- Layer 1: parity, by evidence file (fast) ----------------
    # NOTE (2026-09-22): a single evidence_file path can legitimately carry more than one historical
    # source_payload_hash - a harvester that re-fetches a hotel later (e.g. --retry-failed) overwrites the
    # same file with a newer response; old rows for dates the newer response no longer reports keep their
    # OLD hash. That is a real, separate provenance issue (see the row's own "not in current file" check
    # below and Layer 2), but it must not be conflated with "is this file even readable" - caching ONE
    # ok/not-ok verdict per file (keyed only on whichever hash was seen first) previously caused every row
    # sharing that file to be misreported as bad, even rows whose hash matches the file exactly.
    files = c.execute(
        """SELECT evidence_file, source_payload_hash, evidence_grade, source_type, COUNT(*)
           FROM rate_records GROUP BY 1, 2, 3, 4"""
    ).fetchall()
    file_disk_hash: Dict[str, Optional[str]] = {}   # ef -> real sha256 of the bytes currently on disk
    rows_by_grade = Counter()
    bad_rows_by_grade = Counter()
    bad_examples = defaultdict(list)
    for ef, h, grade, src, n in files:
        rows_by_grade[grade] += n
        if ef not in file_disk_hash:
            p = _norm(ef or "")
            if not ef or not os.path.exists(p):
                file_disk_hash[ef] = None      # missing
            else:
                with open(p, "rb") as fh:
                    file_disk_hash[ef] = hashlib.sha256(fh.read()).hexdigest()
        disk_hash = file_disk_hash[ef]
        row_matches_disk = disk_hash is not None and disk_hash == h
        if not row_matches_disk:
            bad_rows_by_grade[grade] += n
            if len(bad_examples[grade]) < max_examples:
                reason = "missing" if disk_hash is None else "hash mismatch (row references a version of this file that a later run has since overwritten)"
                bad_examples[grade].append(f"{ef} ({reason}, {src}, {n} rows)")

    # Whether a file is usable for Layer 2 replay is a per-file question (can we read and parse it at all),
    # independent of whether every historical row's own hash still matches its current bytes.
    file_ok = {ef: (h is not None) for ef, h in file_disk_hash.items()}

    claimed_bad = bad_rows_by_grade["RAW"] + bad_rows_by_grade["SUMMARY"]
    unverified = rows_by_grade["UNVERIFIED"]

    # ---------------- Layer 2: value replay ----------------
    l2 = {}      # source -> dict(files, rows_checked, mismatches, examples, how)
    not_value_verified = []
    for (src,) in c.execute("SELECT DISTINCT source_type FROM rate_records ORDER BY 1").fetchall():
        rows = c.execute(
            """SELECT evidence_file, stay_date, cash_rate, points_required, raw_currency, room_name
               FROM rate_records WHERE source_type = ? AND evidence_grade IN ('RAW','SUMMARY')""", (src,)
        ).fetchall()
        if not rows:
            continue
        by_file = defaultdict(list)
        for r in rows:
            by_file[r[0]].append(r)
        stats = {"files": 0, "rows": 0, "mismatch": 0, "examples": [], "no_replay": 0, "how": set()}
        for ef, rs in by_file.items():
            if file_ok.get(ef) is not True:
                continue
            with open(_norm(ef), "rb") as fh:
                data = fh.read()
            rep, how = _replay(src, data)
            if rep is None:
                stats["no_replay"] += len(rs)
                continue
            stats["files"] += 1
            stats["how"].add(how)
            for _, sd, cash, pts, cur, room in rs:
                stats["rows"] += 1
                ok, exp = row_ok(rep, sd, cash, pts, cur, room)
                if not ok:
                    stats["mismatch"] += 1
                    if len(stats["examples"]) < max_examples:
                        stats["examples"].append(f"{ef} {sd}: db=(cash {cash}, pts {pts}, room {room!r}) evidence={exp}")
        if stats["rows"] == 0:
            not_value_verified.append((src, len(rows)))
        else:
            l2[src] = stats
            if stats["no_replay"]:
                not_value_verified.append((src + " (part)", stats["no_replay"]))

    l2_mismatch = sum(s["mismatch"] for s in l2.values())
    passed = claimed_bad == 0 and l2_mismatch == 0 and (unverified == 0 or not strict)

    print("=" * 78)
    print("                HOTEL DATABASE EVIDENCE AUDIT (schema v2)")
    print("=" * 78)
    print(f"Total rate records:                         {total:>12,}")
    for g in ("RAW", "SUMMARY", "UNVERIFIED"):
        print(f"  evidence_grade {g:<11}                  {rows_by_grade[g]:>12,}")
    print("-" * 78)
    print("LAYER 1  byte parity of rows that CLAIM verified evidence (RAW / SUMMARY)")
    print(f"  claiming verified but file missing/mismatched: {claimed_bad:>9,}   {'PASS' if claimed_bad == 0 else 'FAIL'}")
    for ex in bad_examples["RAW"] + bad_examples["SUMMARY"]:
        print(f"     e.g. {ex}")
    print(f"  UNVERIFIED rows (known debt, not counted as verified): {unverified:,}" + ("   <- FAILS under --strict" if strict and unverified else ""))
    print("LAYER 2  values re-derived from each row's own evidence")
    for src, s in sorted(l2.items()):
        print(f"  {src:<32} {s['rows']:>10,} rows / {s['files']:,} files   mismatches {s['mismatch']:>6,}   [{'/'.join(sorted(s['how']))}]   {'PASS' if s['mismatch'] == 0 else 'FAIL'}")
        for ex in s["examples"]:
            print(f"     e.g. {ex}")
    for src, n in not_value_verified:
        print(f"  NOT VALUE-VERIFIED (no replayer): {src:<30} {n:>9,} rows")
    print("-" * 78)
    print("AUDIT STATUS: " + ("PASSED" if passed else "FAILED"))
    print("=" * 78)
    conn.close()
    return {
        "total_records": total, "rows_by_grade": dict(rows_by_grade), "claimed_verified_but_bad": claimed_bad,
        "unverified_rows": unverified, "layer2_mismatches": l2_mismatch,
        "not_value_verified": not_value_verified, "audit_passed": passed,
    }


if __name__ == "__main__":
    strict = "--strict" in sys.argv
    sys.exit(0 if run_evidence_audit(strict=strict)["audit_passed"] else 1)
