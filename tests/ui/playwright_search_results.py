# mypy: ignore-errors
"""Offline Playwright validation for search images, diagnostics, and CSV export."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ART = Path("/opt/cursor/artifacts")
ART.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:3000"
VIEWPORT = {"width": 1440, "height": 900}


def _shot(page, name: str) -> None:
    page.screenshot(path=str(ART / name), full_page=False)


def main() -> int:
    report: dict[str, object] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/local/bin/google-chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport=VIEWPORT, accept_downloads=True)
        page = context.new_page()
        page.goto(BASE, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1000)
        page.get_by_role("button", name="Búsquedas").click()
        page.wait_for_timeout(1500)
        _shot(page, "search_idle_1440.png")

        complete = page.get_by_role("button", name="Vista de prueba · completa")
        if complete.count() == 0:
            report["fixtures"] = "missing"
            _shot(page, "search_fixtures_missing.png")
            context.close()
            browser.close()
            (ART / "playwright_report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, indent=2))
            return 1
        complete.click()
        page.wait_for_timeout(1500)
        _shot(page, "search_complete_three_images_1440.png")

        images = page.locator("img.bera-product-thumb-img")
        report["thumb_images"] = images.count()
        srcs = [images.nth(i).get_attribute("src") or "" for i in range(images.count())]
        report["thumb_srcs"] = srcs
        report["alibaba_image"] = any("fixture-alibaba" in src for src in srcs)
        report["facebook_image"] = any("fixture-facebook" in src for src in srcs)
        report["ml_image"] = any("fixture-ml" in src for src in srcs)
        report["no_cross_alibaba_on_facebook"] = not any(
            "fixture-alibaba" in (images.nth(i).get_attribute("src") or "")
            and "facebook" in (images.nth(i).get_attribute("alt") or "").casefold()
            for i in range(images.count())
        )

        details = page.get_by_role("button", name="Ver detalles")
        report["ver_detalles_count"] = details.count()
        if details.count() > 1:
            details.nth(1).click()
            page.wait_for_timeout(500)
            _shot(page, "search_facebook_diagnostic_1440.png")
            body = page.inner_text("body")
            report["facebook_diag_solicitados"] = "Solicitados" in body and "3" in body
            report["facebook_diag_gratis"] = "Gratis" in body
            report["facebook_diag_invalido"] = "Precio inválido" in body

        export_btn = page.get_by_role("button", name="Exportar resultados a CSV")
        if export_btn.count() == 0:
            export_btn = page.get_by_role("button", name="Exportar")
        report["export_disabled_complete"] = export_btn.is_disabled()
        csv_text = ""
        if not export_btn.is_disabled():
            with page.expect_download(timeout=10000) as download_info:
                export_btn.click()
            download = download_info.value
            dest = ART / (download.suggested_filename or "bera-search.csv")
            download.save_as(str(dest))
            payload = dest.read_bytes()
            report["csv_filename"] = dest.name
            report["csv_bom"] = payload.startswith("\ufeff".encode("utf-8"))
            csv_text = payload.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(csv_text)))
            report["csv_rows"] = len(rows)
            report["csv_markets"] = [row.get("marketplace") for row in rows]
            report["csv_accents"] = any("sóftball" in (row.get("title") or "") for row in rows) or (
                "Mouse" in csv_text
            )
            report["csv_urls_intact"] = any(
                "fixture-facebook.png" in (row.get("image_url") or "") for row in rows
            )
            alibaba_rows = [row for row in rows if row.get("marketplace") == "Alibaba"]
            facebook_rows = [
                row for row in rows if row.get("marketplace") == "Facebook Marketplace"
            ]
            ml_rows = [row for row in rows if row.get("marketplace") == "Mercado Libre"]
            report["csv_no_cross_market"] = True
            if alibaba_rows and facebook_rows:
                report["csv_no_cross_market"] = (
                    "facebook.com" not in (alibaba_rows[0].get("listing_url") or "")
                    and "fixture-alibaba" not in (facebook_rows[0].get("image_url") or "")
                    and (
                        not ml_rows or "fixture-alibaba" not in (ml_rows[0].get("image_url") or "")
                    )
                )

        page.get_by_role("button", name="Nueva búsqueda").first.click()
        page.wait_for_timeout(1000)
        _shot(page, "search_after_nueva_busqueda_1440.png")
        report["results_cleared"] = page.get_by_text("Comparación de productos").count() == 0
        report["setup_visible"] = page.get_by_text("Buscar productos").count() > 0

        zero = page.get_by_role("button", name="Vista de prueba · diagnósticos")
        zero.click()
        page.wait_for_timeout(1500)
        _shot(page, "search_zero_alibaba_missing_ml_image_1440.png")
        body = page.inner_text("body")
        report["sin_imagen"] = "Sin imagen" in body
        report["sin_resultados"] = "Sin resultados" in body or "0 resultados" in body
        first_details = page.get_by_role("button", name="Ver detalles")
        if first_details.count():
            first_details.first.click()
            page.wait_for_timeout(500)
            _shot(page, "search_alibaba_empty_diagnostic_1440.png")
            diag = page.inner_text("body")
            report["alibaba_diag"] = "Solicitados" in diag and "Recibidos" in diag

        page.get_by_role("button", name="Nueva búsqueda").first.click()
        page.wait_for_timeout(800)
        export_after = page.get_by_role("button", name="Exportar")
        report["export_after_new_search_present"] = export_after.count() > 0
        report["ok"] = bool(
            report.get("alibaba_image")
            and report.get("facebook_image")
            and report.get("csv_rows", 0) >= 3
            and report.get("sin_imagen")
        )
        context.close()
        browser.close()
    (ART / "playwright_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PlaywrightTimeout as exc:
        print("timeout", exc)
        raise
