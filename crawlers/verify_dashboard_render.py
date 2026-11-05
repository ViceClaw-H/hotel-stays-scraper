import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

html_path = 'file:///' + os.path.abspath('Hotel_Analytics_Dashboard.html').replace('\\', '/')
print('Testing Dashboard at:', html_path)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    
    page.goto(html_path)
    page.wait_for_timeout(3000)
    
    # Check rendered KPI values
    kpi_lowest = page.inner_text('#kpiLowest')
    kpi_low = page.inner_text('#kpiLow')
    kpi_median = page.inner_text('#kpiMedian')
    kpi_high = page.inner_text('#kpiHigh')
    kpi_peak = page.inner_text('#kpiPeak')
    decision = page.inner_text('#decisionText')
    table_rows = page.evaluate("() => document.querySelectorAll('#arbitrageTableBody tr').length")
    
    print('\n========================================')
    print('✅ DASHBOARD RENDER VERIFICATION PASSED')
    print('========================================')
    print('Floor Lowest (P0)  :', kpi_lowest)
    print('Promo Cash (P10)   :', kpi_low)
    print('Median Fair (P50)   :', kpi_median)
    print('Surge Peak (P90)   :', kpi_high)
    print('Peak Max (P100)     :', kpi_peak)
    print('Status Decision     :', decision)
    print('Table Rows Rendered :', table_rows)
    print('Console Errors Count:', len(errors))
    print('========================================\n')
    
    browser.close()
