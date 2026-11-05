"""Location-only Marriott discovery through its public booking autocomplete.

This crawler deliberately does not scrape room prices.  It types each catalog
country into Marriott's booking box, records every displayed suggestion, opens
each suggestion sequentially, and saves the live property-card Marsha codes
for a later sitemap comparison.  It does not create hotels or rate records.
"""
from __future__ import annotations

import argparse, gzip, hashlib, json, re, sqlite3, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
HOME = "https://www.marriott.com/id/default.mi"


def clean(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "country"


def countries(conn: sqlite3.Connection, requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    return [row[0] for row in conn.execute(
        "SELECT DISTINCT country FROM hotels WHERE brand='MARRIOTT' AND trim(country)<>'' ORDER BY country"
    )]


def suggestions(page, country: str) -> list[str]:
    page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
    field = page.locator("#downshift-1-input")
    field.fill(country)
    page.locator('[role="option"]').first.wait_for(state="visible", timeout=25_000)
    page.wait_for_timeout(800)
    return [text.strip() for text in page.locator('[role="option"]').all_inner_texts() if text.strip()]


def save_evidence(evidence_dir: Path, country: str, suggestion_number: int,
                  page_number: int, markup: str) -> dict[str, str]:
    """Keep the official result markup behind each observation, not just a hash."""
    folder = evidence_dir / clean(country)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"suggestion-{suggestion_number:03d}-page-{page_number:03d}.html.gz"
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        handle.write(markup)
    return {
        "path": str(target.relative_to(ROOT)).replace("\\\\", "/"),
        "sha256": hashlib.sha256(markup.encode("utf-8")).hexdigest(),
    }


def page_codes(page) -> list[str]:
    locator = page.locator('.property-card[data-marsha]')
    return [
        (locator.nth(index).get_attribute('data-marsha') or '').upper()
        for index in range(locator.count())
        if locator.nth(index).get_attribute('data-marsha')
    ]


def cards_from_result(page, country: str, suggestion_number: int,
                      evidence_dir: Path) -> tuple[list[dict], list[dict], list[str]]:
    """Return all visible result pages; failure stays an observation, never no-hotels."""
    cards: dict[str, dict] = {}
    evidence: list[dict] = []
    issues: list[str] = []
    for _ in range(20):
        try:
            page.locator('.property-card[data-marsha]').first.wait_for(state='attached', timeout=30_000)
        except Error:
            return [], evidence, ['PROPERTY_CARDS_NOT_LOADED']
        page.wait_for_timeout(1200)
        markup = page.content()
        evidence.append(save_evidence(evidence_dir, country, suggestion_number, len(evidence) + 1, markup))
        locator = page.locator('.property-card[data-marsha]')
        for n in range(locator.count()):
            card = locator.nth(n)
            code = (card.get_attribute('data-marsha') or '').upper()
            raw = card.get_attribute('data-property') or '{}'
            try: data = json.loads(raw)
            except ValueError: data = {}
            if code:
                cards[code] = {'marsha': code, 'brand_code': card.get_attribute('data-brand') or '',
                               'name': data.get('hotelName') or '', 'currency': data.get('currency') or '',
                               'latitude': data.get('lat'), 'longitude': data.get('long')}
        next_page = page.get_by_role('button', name='NextPage')
        if next_page.count() == 0 or not next_page.is_enabled():
            break
        before = page_codes(page)
        next_page.click(timeout=10_000)
        changed = False
        for _ in range(20):
            page.wait_for_timeout(500)
            if page_codes(page) != before:
                changed = True
                break
        # A stagnant paginator is an unknown/incomplete observation, never an empty result.
        if not changed:
            issues.append('PAGINATION_STUCK')
            break
    else:
        issues.append('PAGINATION_LIMIT_REACHED')
    return sorted(cards.values(), key=lambda row: row['marsha']), evidence, issues


def existing_codes(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT id, coalesce(official_url,'') FROM hotels WHERE brand='MARRIOTT'")
    codes: set[str] = set()
    for hotel_id, url in rows:
        match = re.fullmatch(r'marr_([a-z0-9]{5})', hotel_id.lower())
        if match: codes.add(match.group(1).upper())
        codes.update(part.upper() for part in re.findall(r'/([a-z0-9]{5})-', url.lower()))
    return codes


def future_result_url(current_url: str, checkin: date) -> str:
    """Keep the official selected destination, but use a reproducible future stay."""
    checkout = checkin + timedelta(days=1)
    start = checkin.strftime('%d/%m/%Y')
    end = checkout.strftime('%d/%m/%Y')
    parsed = urlsplit(current_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({
        'fromToDate_submit': end,
        'fromDate': start,
        'toDate': end,
        'fromDateDefaultFormat': start,
        'toDateDefaultFormat': end,
        't-start': start,
        't-end': end,
        'lengthOfStay': '1',
        'useRewardsPoints': 'false',
        'recordsPerPage': '20',
    })
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))


def scan_one(page, country: str, known: set[str], max_suggestions: int | None,
             pause: float, evidence_dir: Path, checkin: date) -> dict:
    shown = suggestions(page, country)
    if max_suggestions is not None: shown = shown[:max_suggestions]
    observed = []
    for index, label in enumerate(shown):
        time.sleep(pause)
        try:
            page.goto(HOME, wait_until='domcontentloaded', timeout=60_000)
            page.locator('#downshift-1-input').fill(country)
            opts = page.locator('[role="option"]')
            opts.first.wait_for(state='visible', timeout=25_000)
            if index >= opts.count():
                observed.append({'suggestion': label, 'status': 'SUGGESTION_CHANGED_BEFORE_SELECTION', 'hotels': []})
                continue
            # Index deliberately follows the official displayed order; we log every entry,
            # including landmarks and cross-border suggestions, instead of guessing their type.
            opts.nth(index).click(timeout=10_000)
            page.get_by_role('button', name=re.compile('Cari Hotel|Find Hotels', re.I)).click(timeout=15_000)
            page.wait_for_timeout(2500)
            page.goto(future_result_url(page.url, checkin), wait_until='domcontentloaded', timeout=60_000)
            page.wait_for_timeout(2500)
            cards, evidence, issues = cards_from_result(page, country, index + 1, evidence_dir)
            for card in cards:
                card['catalog_status'] = 'ALREADY_IN_SITEMAP' if card['marsha'] in known else 'NEW_LIVE_PROPERTY'
            observed.append({'suggestion': label, 'result_url': page.url,
                             'status': 'LIVE_CARDS' if cards else 'NO_CARDS_OR_LOAD_FAILURE',
                             'issues': issues, 'hotels': cards, 'evidence': evidence})
        except Exception as exc:
            observed.append({'suggestion': label, 'status': f'{type(exc).__name__}: {exc}', 'hotels': []})
    return {'country_query': country, 'suggestions': observed}


def main() -> int:
    ap = argparse.ArgumentParser(description='Marriott public-autocomplete location discovery; no prices.')
    ap.add_argument('--db', default=str(ROOT/'hotel_stays.db'))
    ap.add_argument('--country', action='append', help='Repeat for an explicit country; omit to use the catalog country list.')
    ap.add_argument('--limit-countries', type=int)
    ap.add_argument('--max-suggestions', type=int, help='Pilot cap only; omit to explore all shown suggestions.')
    ap.add_argument('--min-delay', type=float, default=8.0, help='Sequential pause before each suggestion.')
    ap.add_argument('--checkin', default='2026-10-07', help='Future YYYY-MM-DD stay date for live result cards.')
    ap.add_argument('--force', action='store_true', help='Re-run countries with an existing completed snapshot.')
    ap.add_argument('--headed', action='store_true',
                    help='Use a visible Chrome session when the site withholds cards from headless Chrome.')
    args = ap.parse_args()
    try:
        checkin = date.fromisoformat(args.checkin)
    except ValueError:
        raise SystemExit('--checkin must be YYYY-MM-DD')
    if not CHROME.exists(): raise SystemExit(f'Chrome not found: {CHROME}')
    conn = sqlite3.connect(Path(args.db).resolve())
    todo = countries(conn, args.country)
    known = existing_codes(conn)
    conn.close()
    if args.limit_countries: todo = todo[:args.limit_countries]
    out_dir = ROOT/'data'/'snapshots'/'marriott'/'suggestion-location'
    evidence_dir = ROOT/'evidence'/'marriott'/'suggestion-location'
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME), headless=not args.headed)
        page = browser.new_page(viewport={'width': 1440, 'height': 900}, locale='id-ID')
        try:
            for number, country in enumerate(todo, 1):
                print(f'[{number}/{len(todo)}] {country}', flush=True)
                output = out_dir/f'{clean(country)}.json'
                if output.exists() and not args.force:
                    try:
                        prior = json.loads(output.read_text(encoding='utf-8'))
                        if prior.get('complete'):
                            print('  skipped=already-complete', flush=True)
                            continue
                    except (OSError, ValueError):
                        pass
                try:
                    result = scan_one(page, country, known, args.max_suggestions, args.min_delay, evidence_dir, checkin)
                    result['complete'] = True
                except Exception as exc:
                    result = {'country_query': country, 'suggestions': [], 'status': f'{type(exc).__name__}: {exc}', 'complete': False}
                result['observed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                result['checkin'] = checkin.isoformat()
                result['source'] = 'OFFICIAL_MARRIOTT_BOOKING_AUTOCOMPLETE'
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
                print(f"  suggestions={len(result.get('suggestions', []))} cards={sum(len(x.get('hotels', [])) for x in result.get('suggestions', []))}", flush=True)
        finally:
            browser.close()
    return 0

if __name__ == '__main__': raise SystemExit(main())
