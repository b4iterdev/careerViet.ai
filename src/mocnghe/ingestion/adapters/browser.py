from __future__ import annotations


def fetch_rendered_html(
    url: str,
    *,
    timeout_seconds: float = 15.0,
    wait_selector: str | None = None,
) -> str:
    """Fetch dynamically rendered HTML using Playwright headless browser."""
    import importlib

    try:
        sync_playwright_module = importlib.import_module("playwright.sync_api")
        sync_playwright = sync_playwright_module.sync_playwright
    except (ImportError, ModuleNotFoundError) as err:
        raise RuntimeError(
            "Playwright is required for browser crawling. "
            "Install with `pip install 'mocnghe[browser]'` and run `playwright install chromium`."
        ) from err

    timeout_ms = int(timeout_seconds * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()
