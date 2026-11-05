# -*- coding: utf-8 -*-
"""
Hyatt CASH benchmark harvester (schema v2) - NOT a cash calendar, and not part of the default run.

Hyatt has no cash calendar. Its only multi-date endpoint (`avail/days`, the "Points Calendar" page) never
returns cash: `rate` is null in every cell, and the page hard-codes pointsCashAvailable=false. A cash price
exists only per stay in the booking flow:

    GET https://www.hyatt.com/en-US/shop/service/rooms/roomrates/{spirit}?spiritCode={spirit}&rooms=1&adults=1&kids=0
        &checkinDate={D}&checkoutDate={D+1}
    -> {"roomRates": {"KING": {"roomCategory": "STANDARD", "roomType": {"title": "1 King Bed"},
                               "ratePlans": [{"id": "RACK", "ratePlanCategory": "CASH", "rate": 2650 (pre-tax),
                                              "totalAfterTax": 3272.75, "currencyCode": "AED", "taxes": [...]}]}}}

One request = one night at one hotel (~110 KB, ~1.8 s). A multi-night request returns an AVERAGE per night, not
per-night prices, so there is no way to batch dates. Hence "benchmark dates": for each hotel we price up to
24 dates (the 2nd Wednesday and 2nd Saturday of each of the next 12 months, moved to the nearest date in that
month that has a confirmed award night, so cash and points are paired for the SAME date). This is a
sample for points-value analysis, not a calendar.

Contract (schema v2): cash = the plan's totalAfterTax (fully taxed checkout total, never the pre-tax `rate`),
currency from the response (`currency=USD` in the URL does NOT convert, measured), points NULL on cash rows
(award points come from the award harvester), room_name = the room title verbatim. The room/plan rule lives
in engine.extractors.hyatt (parse_cash_evidence). Writes: engine.rate_writer.write_rate_batch, one transaction
per hotel; state: harvest_status source HYATT_CASH.

Run:
  python crawlers/hyatt_cash_benchmark_harvester.py --estimate               # cost estimate from the DB, no requests
  python crawlers/hyatt_cash_benchmark_harvester.py --spirit balgh --dry-run
  python crawlers/hyatt_cash_benchmark_harvester.py --spirit balgh --limit 1
"""
import argparse
import json
import os
import random
import sqlite3
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from typing import List, Optional, Set

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import hyatt_avail_days_harvester as aw  # noqa: E402  (session, console, logging, catalog, fetch/retry)
from dateutil.relativedelta import relativedelta  # noqa: E402

from engine import harvest_state  # noqa: E402
from engine.extractors import hyatt as hx  # noqa: E402
from engine.rate_writer import write_rate_batch  # noqa: E402

SOURCE = "HYATT_CASH"
SOURCE_TYPE = "OFFICIAL_HYATT_CASH_BENCHMARK"
AWARD_SOURCE_TYPE = aw.SOURCE_TYPE

# Measured 2026-09-21 on one Chrome session (roomrates): 1.6-2.4 s server time, 5-372 KB, median 107 KB.
EST_SECONDS_PER_CALL = 1.9
EST_PACING_SECONDS = 0.45
EST_RECYCLE_SECONDS = 12.0


def cash_url(spirit: str, checkin: date) -> str:
    return (f"{aw.BASE}/en-US/shop/service/rooms/roomrates/{spirit}?spiritCode={spirit}&rooms=1&adults=1&kids=0"
            f"&checkinDate={checkin}&checkoutDate={checkin + timedelta(days=1)}")


# ── which dates ─────────────────────────────────────────────────────────────────────────────
def confirmed_award_dates(conn, hotel_id: str, today: date) -> Set[str]:
    """Future stay dates with a stored award price for this hotel (from our own award harvest)."""
    cur = conn.execute(
        """SELECT DISTINCT rr.stay_date FROM rate_records rr JOIN room_categories rc ON rc.id = rr.room_id
           WHERE rc.hotel_id = ? AND rr.source_type = ? AND rr.points_required > 0 AND rr.stay_date >= ?""",
        (hotel_id, AWARD_SOURCE_TYPE, today.isoformat()))
    return {r[0] for r in cur}


def _nth_weekday(days: List[date], weekday: int) -> Optional[date]:
    m = [d for d in days if d.weekday() == weekday]
    return m[1] if len(m) > 1 else (m[0] if m else None)


def build_benchmark_dates(award_dates: Set[str], today: date, months: int = 12, include_unpaired: bool = False) -> List[str]:
    """2nd Wednesday + 2nd Saturday per month from today; a target without an award night moves to the
    nearest award date of that month; a month with no award night is skipped (unless include_unpaired)."""
    out: List[str] = []
    for m in range(months):
        first = today.replace(day=1) + relativedelta(months=m)
        nxt = first + relativedelta(months=1)
        days = [first + timedelta(days=i) for i in range((nxt - first).days)]
        month_awards = sorted(a for a in award_dates if a.startswith(first.strftime("%Y-%m")))
        for target in (_nth_weekday(days, 2), _nth_weekday(days, 5)):
            if target is None:
                continue
            t = target.isoformat()
            if target > today and (t in award_dates or (include_unpaired and not award_dates)):
                out.append(t)
            elif month_awards:
                out.append(min(month_awards, key=lambda a: abs((date.fromisoformat(a) - target).days)))
            elif include_unpaired and target > today:
                out.append(t)
    seen, uniq = set(), []
    for d in out:
        if d not in seen and d > today.isoformat():
            seen.add(d)
            uniq.append(d)
    return uniq


# ── one hotel ───────────────────────────────────────────────────────────────────────────────
def harvest_cash_hotel(session, conn, hotel: dict, cfg: aw.Cfg, include_unpaired=False, max_dates=None) -> aw.HotelResult:
    sc, hid = hotel["spirit_code"], hotel["hotel_id"]
    res = aw.HotelResult()
    award_dates = confirmed_award_dates(conn, hid, cfg.today) if conn is not None else set()
    dates = build_benchmark_dates(award_dates, cfg.today, cfg.months, include_unpaired)
    if max_dates:
        dates = dates[:max_dates]
    res.dates_total = len(dates)
    if not dates:
        res.status, res.reason = "NO_AVAILABILITY", "NO_AWARD_DATES"
        res.detail = "no confirmed future award night in the database; nothing to pair a cash price with"
        aw._record(conn, hid, res, cfg, SOURCE)
        return res

    failed, priced, unpriced = [], 0, 0
    try:
        for d in dates:
            url = cash_url(sc, date.fromisoformat(d))
            o = aw.fetch_definitive(session, url, hx.classify_cash_response, cfg, res)
            o.window = (d, d)
            res.url = res.url or url
            if o.verdict.kind == "SOLD_OUT":
                unpriced += 1
            elif o.verdict.kind == "OK":
                raw = o.text.encode("utf-8")
                rows = hx.parse_cash_evidence(raw, d)
                if not rows:
                    unpriced += 1                     # answered, but no eligible standard-room cash plan that night
                elif not cfg.dry_run:
                    wr = write_rate_batch(conn, hotel_id=hid, source_type=SOURCE_TYPE, source_url=url, rows=rows,
                                          evidence_relpath=f"evidence/hyatt/cash_benchmarks/hyatt_{sc}_{d}_cash.json",
                                          evidence_bytes=raw, evidence_grade="RAW", workspace_dir=cfg.workspace,
                                          today=cfg.today, commit=False)
                    priced += wr.written
                    for _, why in wr.rejected:
                        res.rejected[why] += 1
                    if wr.written:
                        res.horizon_last_ok = max(res.horizon_last_ok or "", d)
                else:
                    priced += len(rows)
                    print(f"    DRY {d} {rows[0].currency} {rows[0].cash_rate:,.2f}  {rows[0].room_name}  {rows[0].notes}")
            else:
                failed.append(o)
            cfg.sleep(random.uniform(*cfg.pace))
    except Exception as ex:
        if conn is not None:
            conn.rollback()
        res.status, res.reason, res.detail = "FAILED", "DB_OR_PARSE_ERROR", f"{type(ex).__name__}: {ex}"
        aw._record(conn, hid, res, cfg, SOURCE)
        return res

    res.rows = res.dates_ok = priced
    rej = ("; rejected: " + ", ".join(f"{k}={v}" for k, v in sorted(res.rejected.items()))) if res.rejected else ""
    if not failed:
        if priced:
            res.status, res.detail = "OK", f"{priced}/{len(dates)} benchmark nights priced, {unpriced} answered without an eligible cash plan{rej}"
        else:
            res.status, res.reason = "NO_AVAILABILITY", "NO_ELIGIBLE_CASH_PLAN"
            res.detail = f"all {len(dates)} benchmark nights answered but none had an eligible standard-room cash plan{rej}"
    else:
        res.reason = failed[0].verdict.reason
        res.url = failed[0].url
        res.detail = f"{len(failed)}/{len(dates)} nights failed: " + " | ".join(
            f"{o.window[0]} HTTP {o.status} {o.verdict.reason} after {o.attempts} tries: {(o.verdict.detail or o.text or '')[:80]!r}"
            for o in failed[:4]) + rej
        res.status = "PARTIAL" if (priced or unpriced) else "FAILED"
    aw._record(conn, hid, res, cfg, SOURCE)
    return res


# ── estimate ────────────────────────────────────────────────────────────────────────────────
def estimate(conn, hotels, today: date, months: int, include_unpaired: bool, workers: int = 1) -> str:
    """Calls / hours / GB for the given hotels, from the award dates already in the database (no requests)."""
    by_hotel = {}
    for hid, sd in conn.execute(
            """SELECT rc.hotel_id, rr.stay_date FROM rate_records rr JOIN room_categories rc ON rc.id = rr.room_id
               WHERE rr.source_type = ? AND rr.points_required > 0 AND rr.stay_date >= ?""", (AWARD_SOURCE_TYPE, today.isoformat())):
        by_hotel.setdefault(hid, set()).add(sd)
    per_hotel = [len(build_benchmark_dates(by_hotel.get(h["hotel_id"], set()), today, months, include_unpaired)) for h in hotels]
    priced = [n for n in per_hotel if n]
    calls = sum(per_hotel)
    avg_bytes = 110_000
    secs = calls * (EST_SECONDS_PER_CALL + EST_PACING_SECONDS) + (calls / 60) * EST_RECYCLE_SECONDS   # recycle every ~60 calls
    return (f"hotels considered {len(hotels)}; with >=1 pairable date {len(priced)}; "
            f"calls/hotel avg {calls/max(len(priced),1):.1f} (max {max(per_hotel or [0])}); total calls {calls:,}; "
            f"~{secs/max(len(priced),1):.0f} s/hotel; ~{secs/3600:.1f} h on 1 Chrome, ~{secs/3600/max(workers,1):.1f} h on {workers}; "
            f"evidence ~{calls*avg_bytes/1e9:.1f} GB ({avg_bytes//1000} KB/response, stored verbatim)")


# ── run ─────────────────────────────────────────────────────────────────────────────────────
def run(args) -> int:
    workspace = os.path.abspath(args.workspace_dir)
    db_path = args.db or os.path.join(workspace, "hotel_stays.db")
    logfile = aw.setup_logging(workspace)
    spirit = [s.strip().lower() for s in args.spirit.split(",")] if args.spirit else None
    hotels = aw.load_redeemable_hotels(spirit)
    if args.total_workers > 1:
        hotels = hotels[args.worker_id - 1::args.total_workers]
    today = date.today()
    if args.estimate:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        print(estimate(conn, hotels, today, args.months, args.include_unpaired, args.workers))
        return 0
    conn = aw.open_db(db_path, read_only_if_dry=args.dry_run)
    if conn is None:
        print(f"[!] database not found: {db_path}")
        return 1
    states = harvest_state.load_all(conn, SOURCE) if aw._has_status(conn) else {}
    todo = aw.select_hotels(hotels, states, spirit=spirit, force=args.force, retry_failed=args.retry_failed,
                            refresh_days=args.refresh_days, limit=args.limit)
    if not args.dry_run:
        missing = aw.hotels_missing_from_db(conn, todo)
        for h in missing:
            harvest_state.record(conn, SOURCE, h["hotel_id"], "FAILED", reason="HOTEL_NOT_IN_DB",
                                 detail="hotel row is missing from `hotels`", retry_days=7)
            aw.say(f"  [FAILED] {h['spirit_code']}  HOTEL_NOT_IN_DB")
        skip = {h["hotel_id"] for h in missing}
        todo = [h for h in todo if h["hotel_id"] not in skip]
    cfg = aw.Cfg(workspace=workspace, months=args.months, today=today, dry_run=args.dry_run)
    aw.say(f"[HYATT_CASH w{args.worker_id}/{args.total_workers}] {len(todo)} hotels, up to {args.max_dates or 2 * args.months} nights each, "
           f"db={db_path}, log={logfile}{'  DRY-RUN' if args.dry_run else ''}")
    if not todo:
        return 0
    session = aw.HyattCDPSession(port=args.port, tag="cash", max_reqs=(args.max_reqs, args.max_reqs + 20))
    console = aw.Console(len(todo), f"HYATT_CASH w{args.worker_id}", every=args.every)
    streak, rc, t0 = 0, 0, time.time()
    try:
        session.start()
        for hotel in todo:
            res = harvest_cash_hotel(session, conn, hotel, cfg, args.include_unpaired, args.max_dates)
            console.hotel(hotel["spirit_code"], res, session)
            streak = streak + 1 if res.status == "FAILED" else 0
            if streak >= args.abort_after:
                aw.say(f"[!] {streak} hotels in a row FAILED - Hyatt is blocking us; stopping. Re-run with --retry-failed later.")
                rc = 2
                break
    except KeyboardInterrupt:
        aw.say("[!] interrupted; finishing")
        rc = 130
    finally:
        session.close()
        conn.close()
    el = time.time() - t0
    c = console.counts
    aw.say(f"[HYATT_CASH w{args.worker_id}] DONE {console.done} hotels in {el/60:.1f} min ({el/max(console.done,1):.0f} s/hotel): "
           f"ok {c['OK']}  no-data {c['NO_AVAILABILITY']}  partial {c['PARTIAL']}  failed {c['FAILED']}  rows {console.rows:,}  "
           f"requests {session.requests} ({session.requests/max(console.done,1):.1f}/hotel)  chrome recycles {session.recycles}")
    return rc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Hyatt cash benchmark harvester (per-night roomrates; NOT a calendar)")
    p.add_argument("--spirit")
    p.add_argument("--limit", type=int)
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--max-dates", type=int, help="cap benchmark nights per hotel")
    p.add_argument("--include-unpaired", action="store_true", help="also price target dates that have no award night")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--estimate", action="store_true", help="print calls/hours/GB from the database and exit (no requests)")
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument("--refresh-days", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--resume", action="store_true", help="(kept for old command lines; resuming from harvest_status is the default)")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--worker-id", type=int, default=1)
    p.add_argument("--total-workers", type=int, default=1)
    p.add_argument("--port", type=int, default=9232)
    p.add_argument("--max-reqs", type=int, default=60)
    p.add_argument("--abort-after", type=int, default=4)
    p.add_argument("--every", type=int, default=10, help="hotels between console summary lines")
    p.add_argument("--db")
    p.add_argument("--workspace-dir", default=aw.ROOT)
    args = p.parse_args(argv)
    if args.workers > 1 and not args.estimate:
        return aw.spawn_workers(args, os.path.abspath(__file__))
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
