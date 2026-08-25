"""Display helpers for Alibaba tracking history. No persistence changes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def parse_tracking_history(history: object) -> list[dict[str, str]]:
    """Split the stored history blob into timestamp / price / origin rows."""

    if not isinstance(history, str) or not history.strip():
        return []
    entries: list[dict[str, str]] = []
    for raw_line in history.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(" · ")]
        entries.append(
            {
                "raw": line,
                "timestamp": parts[0] if parts else line,
                "price": parts[1] if len(parts) > 1 else "",
                "origin": parts[2] if len(parts) > 2 else "",
            }
        )
    return entries


def history_is_collapsed(open_ids: Sequence[str] | None, product_id: object) -> bool:
    """History stays collapsed unless the product id is explicitly open."""

    if not isinstance(product_id, str) or not product_id:
        return True
    visible = [item for item in (open_ids or []) if isinstance(item, str)]
    return product_id not in visible


def history_toggle_label(snapshot_count: object) -> str:
    count = str(snapshot_count).strip() if snapshot_count is not None else "0"
    if not count:
        count = "0"
    return f"Ver historial ({count})"


def tracking_image_url(
    product_id: object,
    *,
    tracked_image: object = "",
    result_images: Mapping[str, str] | None = None,
) -> str:
    """Reuse an already-loaded Alibaba result image; never invent one."""

    from bera_price_tracker.gui.images import safe_public_image_url

    if isinstance(tracked_image, str):
        current = safe_public_image_url(tracked_image)
        if current:
            return current
    if not isinstance(product_id, str) or not product_id:
        return ""
    lookup = result_images or {}
    return safe_public_image_url(lookup.get(product_id, ""))
