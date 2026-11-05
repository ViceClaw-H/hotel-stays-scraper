"""Honesty audit for freshly scraped rows (any chain). Pure functions over a sqlite connection.

It asks the questions a careful human reviewer asks about a scraper's output:

  FAIL  EVIDENCE_NOT_VERBATIM  the evidence file contains keys a script ADDED to the server's response
                               (e.g. `all_in_rate`, `base_min_rate`, `excluded_taxes`): it is not a copy of the server.
  FAIL  NOT_TAX_INCLUSIVE      a row is not flagged tax inclusive (the project only stores final, taxed prices).
  FAIL  NO_CURRENCY            a row has no currency.
  FAIL  FORBIDDEN_NOTE         notes contain words the provenance gate forbids (synthetic, estimated, multiplier ...).
  FAIL  EVIDENCE_MISSING       the evidence file of a row is not on disk.
  WARN  ESTIMATED_KEY          the evidence has a key named 'estimated...' (may be the server's own wording; look at it).
  WARN  TOO_UNIFORM            >= 14 dates but at most 2 distinct prices for a hotel (real calendars rarely look like that).
  WARN  CONSTANT_TAX_RATIO     evidence carries tax/subtotal pairs whose ratio is identical across >= 10 records AND
                               across different hotels' files (a sign of a formula, not a server).
  INFO  UNKNOWN_ROOM           rows whose room is 'UNKNOWN (...)' (the source did not name a room).

The audit never changes anything. `audit_rows()` returns a list of Finding; `verdict()` summarises.
"""
import gzip
import json
import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

try:
    from engine.provenance_gate import FORBIDDEN_KEYWORDS
except Exception:  # pragma: no cover
    FORBIDDEN_KEYWORDS = ["synthetic", "estimated", "multiplier", "fake", "benchmark formula", "procedural", "placeholder"]

# keys that only a SCRIPT would add to a server response
SCRIPT_ADDED_KEYS = re.compile(r"^(all_in_rate|all_in|allin|base_min_rate|excluded_taxes|tax_rate_assumed|assumed_tax|multiplier|synthetic|computed_total|derived_total)$", re.I)
ESTIMATED_KEY = re.compile(r"estimated", re.I)


@dataclass
class Finding:
    level: str      # FAIL | WARN | INFO
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"


def _load_evidence(path: str) -> Any:
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _walk(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield (f"{path}/{k}", str(k), v)
            yield from _walk(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:200]):       # lists can be huge; the first 200 elements are enough to see the shape
            yield from _walk(v, f"{path}[{i}]")


def scan_evidence_keys(doc: Any) -> Dict[str, Set[str]]:
    """{'script_added': {...}, 'estimated': {...}} key names found anywhere in the document."""
    found = {"script_added": set(), "estimated": set()}
    for _p, key, _v in _walk(doc):
        if SCRIPT_ADDED_KEYS.match(key):
            found["script_added"].add(key)
        elif ESTIMATED_KEY.search(key):
            found["estimated"].add(key)
    return found


def _tax_ratios(doc: Any) -> List[float]:
    """taxes/subtotal ratios of records that carry both (generic: any dict with those two numeric keys)."""
    out: List[float] = []
    stack = [doc]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            sub, tax = o.get("subtotal"), o.get("estimated_taxes", o.get("taxes"))
            if isinstance(sub, (int, float)) and isinstance(tax, (int, float)) and not isinstance(sub, bool) and sub > 0:
                out.append(round(tax / sub, 3))
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o[:200])
    return out


def audit_rows(conn: sqlite3.Connection, workspace_dir: str, row_ids: Optional[Iterable[Any]] = None) -> List[Finding]:
    """Audit rate_records rows (all of them, or only `row_ids`). Evidence paths are relative to workspace_dir."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(rate_records)")]
    sel = "id, room_id, stay_date, cash_rate, raw_currency, tax_inclusive, room_name, notes, evidence_file"
    if "id" not in cols:
        return [Finding("FAIL", "SCHEMA", "rate_records has no id column")]
    if row_ids is None:
        rows = conn.execute(f"SELECT {sel} FROM rate_records").fetchall()
    else:
        ids = list(row_ids)
        rows = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows += conn.execute(f"SELECT {sel} FROM rate_records WHERE id IN ({','.join('?' * len(chunk))})", chunk).fetchall()
    findings: List[Finding] = []
    if not rows:
        return [Finding("FAIL", "NO_ROWS", "no rows to audit")]

    cash = [r for r in rows if r[3] is not None]          # points-only rows carry no cash price: tax/currency do not apply
    if len(cash) < len(rows):
        findings.append(Finding("INFO", "POINTS_ONLY_ROWS", f"{len(rows) - len(cash)} of {len(rows)} rows are points-only (no cash price)"))
    bad_tax = sum(1 for r in cash if r[5] != 1)
    if bad_tax:
        findings.append(Finding("FAIL", "NOT_TAX_INCLUSIVE", f"{bad_tax} of {len(cash)} cash rows are not flagged tax inclusive"))
    no_ccy = sum(1 for r in cash if not r[4])
    if no_ccy:
        findings.append(Finding("FAIL", "NO_CURRENCY", f"{no_ccy} of {len(cash)} cash rows have no currency"))
    low_kw = [kw for kw in FORBIDDEN_KEYWORDS if any(r[7] and kw in str(r[7]).lower() for r in rows)]
    if low_kw:
        findings.append(Finding("FAIL", "FORBIDDEN_NOTE", f"notes contain forbidden words: {', '.join(low_kw)}"))
    unknown = sum(1 for r in rows if str(r[6] or "").upper().startswith("UNKNOWN"))
    if unknown:
        findings.append(Finding("INFO", "UNKNOWN_ROOM", f"{unknown} of {len(rows)} rows have no room name from the source"))

    # uniformity per hotel (room_id prefix before '__' is the hotel id in this schema)
    by_hotel: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        if r[3] is not None:
            by_hotel[str(r[1]).split("__")[0]].append(float(r[3]))
    for h, vals in by_hotel.items():
        if len(vals) >= 14 and len(set(vals)) <= 2:
            findings.append(Finding("WARN", "TOO_UNIFORM", f"{h}: {len(vals)} dates but only {len(set(vals))} distinct price(s)"))

    # evidence files
    files = sorted({r[8] for r in rows if r[8]})
    ratio_sets: List[Set[float]] = []
    for rel in files:
        path = os.path.join(workspace_dir, rel)
        if not os.path.exists(path):
            findings.append(Finding("FAIL", "EVIDENCE_MISSING", f"{rel} is not on disk"))
            continue
        try:
            doc = _load_evidence(path)
        except Exception as e:
            findings.append(Finding("FAIL", "EVIDENCE_UNREADABLE", f"{rel}: {type(e).__name__}"))
            continue
        k = scan_evidence_keys(doc)
        if k["script_added"]:
            findings.append(Finding("FAIL", "EVIDENCE_NOT_VERBATIM", f"{os.path.basename(rel)} has keys no server sends: {', '.join(sorted(k['script_added']))}"))
        if k["estimated"]:
            findings.append(Finding("WARN", "ESTIMATED_KEY", f"{os.path.basename(rel)} has key(s) named {', '.join(sorted(k['estimated']))}"))
        ratios = _tax_ratios(doc)
        if len(ratios) >= 10:
            ratio_sets.append(set(ratios))
    if len(ratio_sets) >= 2 and all(len(s) <= 2 for s in ratio_sets) and len(set.intersection(*ratio_sets)) >= 1:
        findings.append(Finding("WARN", "CONSTANT_TAX_RATIO", f"the same tax/subtotal ratio {sorted(set.intersection(*ratio_sets))} appears in {len(ratio_sets)} different hotels' evidence"))
    return findings


def verdict(findings: List[Finding]) -> str:
    if any(f.level == "FAIL" for f in findings):
        return "FAIL"
    if any(f.level == "WARN" for f in findings):
        return "WARN"
    return "PASS"


def main(argv=None) -> int:
    """v9f entry point: `python -m engine.honesty_audit [--db hotel_stays.db]` (read-only).

    v9e had no entry point, so `python -m engine.honesty_audit` exited 0 without auditing anything.
    Exit codes: 0 = PASS, 1 = WARN, 2 = FAIL, 3 = could not run.
    """
    import argparse
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Honesty audit of rate_records (read-only)")
    ap.add_argument("--db", default=os.path.join(root, "hotel_stays.db"))
    ap.add_argument("--workspace", default=root, help="folder that holds the evidence files (default: package folder)")
    ap.add_argument("--max-print", type=int, default=300)
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        print(f"[AUDIT] database not found: {a.db}")
        return 3
    conn = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(a.db).replace("\\", "/"), uri=True)
    try:
        findings = audit_rows(conn, a.workspace)
    finally:
        conn.close()
    v = verdict(findings)
    print(f"VERDICT: {v}")
    print(f"FINDINGS: {len(findings)}")
    for f in findings[: a.max_print]:
        print(str(f))
    return {"PASS": 0, "WARN": 1, "FAIL": 2}[v]


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
