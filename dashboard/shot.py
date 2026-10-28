# shot.py  [desk] render site/ with headless chromium -> preview.png (desktop) + preview_mobile.png
import subprocess, sys, time, os
from playwright.sync_api import sync_playwright
here = os.path.dirname(os.path.abspath(__file__))
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8765", "--bind", "127.0.0.1"], cwd=os.path.join(here, "site"),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, vp in (("preview.png", {"width": 1366, "height": 900}), ("preview_mobile.png", {"width": 390, "height": 844})):
            pg = b.new_page(viewport=vp, device_scale_factor=1 if "mobile" not in name else 2)
            errs = []
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:8765/", wait_until="networkidle")
            pg.wait_for_timeout(1500)
            pg.screenshot(path=os.path.join(here, name), full_page=True)
            print(name, "errors:", errs, "chart.js:", pg.evaluate("!!window.Chart"),
                  "overflowX:", pg.evaluate("document.documentElement.scrollWidth > window.innerWidth"))
        b.close()
finally:
    srv.terminate()
