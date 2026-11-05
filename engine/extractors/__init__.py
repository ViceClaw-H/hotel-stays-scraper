"""Pure per-chain parsers: raw evidence bytes -> list[engine.rate_writer.RateRow].

Each chain module exposes `parse_evidence(evidence_bytes: bytes) -> list[RateRow]`. The harvester uses
it on the raw responses it just fetched; the verifier replays it offline on the saved file. If a
parsing rule changes (tax field, room choice), re-run the extractor over saved evidence - no
re-scrape needed. Extractors do no I/O and touch no database.
"""
