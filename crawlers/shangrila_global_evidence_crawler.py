"""SUPERSEDED - kept only so old shortcuts keep working. There is no second crawler and no second write path.

The former UI-scraping crawler of this file (Playwright page text, min-price regex, single-row legacy writer)
stored 'Tax & Fee Excl.' amounts as final prices and is gone. Everything is done by
crawlers/shangrila_master_365_and_percentiles_crawler.py (all-in prices from the CRS booking gateway, one
transaction per hotel, harvest_status state). This shim forwards its command line to it unchanged.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shangrila_master_365_and_percentiles_crawler import main  # noqa: E402

if __name__ == "__main__":
    print("shangrila_global_evidence_crawler.py is superseded: running shangrila_master_365_and_percentiles_crawler.py", flush=True)
    sys.exit(main())
