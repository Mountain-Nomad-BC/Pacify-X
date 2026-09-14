#!/usr/bin/env python3
"""Optional Playwright content-level atlas QA. Does not claim native URL/Obsidian acceptance.
Install/provide your own approved browser test environment; this tool installs nothing.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--atlas",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs/architecture",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--browser", help="Explicit already-installed browser executable")
    a = ap.parse_args()
    if a.out.exists():
        ap.error("use a new output directory; never overwrite prior QA")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        ap.exit(
            3,
            "Playwright is not available in this Python environment. No browser installation attempted.\n",
        )
    html = (a.atlas / "ATLAS_OFFLINE.html").read_bytes()
    graph = (a.atlas / "data/complete_graph.json").read_bytes()
    g = json.loads(graph)
    a.out.mkdir(parents=True)
    r = {
        "schema_version": "px.atlas-content-qa/1",
        "html_sha256": hashlib.sha256(html).hexdigest(),
        "graph_sha256": hashlib.sha256(graph).hexdigest(),
        "source_sha256": g["metadata"]["source_inventory_sha256"],
        "delivery": "exact self-contained HTML via set_content",
        "native_file_navigation_verified": False,
        "Obsidian_verified": False,
        "product_certified": False,
        "checks": [],
        "errors": [],
    }
    try:
        with sync_playwright() as p:
            kwargs = {"headless": True}
            if a.browser:
                kwargs["executable_path"] = a.browser
            b = p.chromium.launch(**kwargs)
            try:
                page = b.new_page(viewport={"width": 1600, "height": 1100})
                page.on("pageerror", lambda e: r["errors"].append(str(e)))
                page.on(
                    "request",
                    lambda req: (
                        r["errors"].append("Unexpected network dependency: " + req.url)
                        if req.url.startswith(("http:", "https:"))
                        else None
                    ),
                )
                start = time.perf_counter()
                page.set_content(html.decode("utf-8"))
                page.wait_for_function("window.PX_VIEWER_STATE?.drawn===true")
                r["initial_content_load_seconds"] = round(
                    time.perf_counter() - start, 3
                )
                assert (
                    page.evaluate("window.PX_VIEWER_STATE.visibleNodes")
                    == g["metrics"]["systems"]
                )
                r["checks"].append("complete semantic denominator")
                page.screenshot(path=str(a.out / "full_architecture.png"))
                for view in ("Runtime Observed", "Certified"):
                    page.select_option("#view", view)
                    page.wait_for_function("window.PX_VIEWER_STATE.visibleNodes===0")
                    r["checks"].append("empty unproved " + view)
                page.click("#home")
                page.select_option("#scope", "all")
                page.wait_for_function(
                    "window.PX_VIEWER_STATE.visibleNodes===window.PX_GRAPH.nodes.length"
                )
                r["checks"].append("complete combined denominator")
                page.screenshot(path=str(a.out / "combined_graph.png"))
                page.click("#home")
                page.fill("#search", "learning")
                page.wait_for_timeout(120)
                assert (
                    0
                    < page.evaluate("window.PX_VIEWER_STATE.visibleNodes")
                    < g["metrics"]["systems"]
                )
                r["checks"].append("search changes graph and text index")
                page.locator("#results button").first.click()
                page.click("#focus")
                assert page.evaluate("window.PX_VIEWER_STATE.selected") is not None
                r["checks"].append("selection and focus")
                page.click("#home")
                page.select_option("#journey", "F07")
                assert "Learning" in page.locator("#journeyDetail").inner_text()
                r["checks"].append("journey uses existing flow")
                for cam in g["cameras"]:
                    page.select_option("#camera", cam["name"])
                for view in g["views"]:
                    page.select_option("#view", view["name"])
                page.click("#home")
                page.locator("#canvas").focus()
                page.keyboard.press("ArrowRight")
                page.keyboard.press("+")
                r["checks"].append("eleven views/cameras and keyboard")
                assert not r["errors"]
                r["passed"] = True
            finally:
                b.close()
                r["browser_closed"] = True
    except Exception as e:
        r["passed"] = False
        r["errors"].append(str(e))
    (a.out / "browser_content_qa.json").write_text(json.dumps(r, indent=2) + "\n")
    print(json.dumps(r, indent=2))
    return 0 if r.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
