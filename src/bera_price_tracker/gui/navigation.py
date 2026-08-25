"""Sidebar destinations mapped to existing BERA views. No fake features."""

from __future__ import annotations

from typing import NamedTuple

WORKSPACE_DASHBOARD = "dashboard"
WORKSPACE_SEARCHES = "searches"
WORKSPACE_PRODUCTS = "products"
WORKSPACE_COMPARISONS = "comparisons"
WORKSPACE_TRACKING = "tracking"
WORKSPACE_IMPORT = "import"
WORKSPACE_TOOLS = "tools"
WORKSPACE_SETTINGS = "settings"

DEFAULT_WORKSPACE = WORKSPACE_DASHBOARD


class NavItem(NamedTuple):
    view: str
    label: str
    icon: str
    description: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem(WORKSPACE_DASHBOARD, "Dashboard", "layout-dashboard", "Resumen ejecutivo"),
    NavItem(WORKSPACE_SEARCHES, "Búsquedas", "search", "Búsqueda Alibaba"),
    NavItem(WORKSPACE_PRODUCTS, "Productos", "package", "Facebook Marketplace Venezuela"),
    NavItem(WORKSPACE_COMPARISONS, "Comparaciones", "git-compare", "Mercado Libre Venezuela"),
    NavItem(WORKSPACE_TRACKING, "Seguimiento", "refresh-cw", "Seguimiento Alibaba"),
    NavItem(WORKSPACE_IMPORT, "Importación", "download", "Costo puesto y negociación"),
    NavItem(WORKSPACE_TOOLS, "Herramientas", "wrench", "Facebook H0019"),
    NavItem(WORKSPACE_SETTINGS, "Configuración", "settings", "Ranking y filtros Alibaba"),
)

NAV_LABELS: tuple[str, ...] = tuple(item.label for item in NAV_ITEMS)


def marketplace_tab_for(view: str) -> str:
    """Keep the existing tab field aligned with the workspace destination."""

    mapping = {
        WORKSPACE_DASHBOARD: "alibaba",
        WORKSPACE_SEARCHES: "alibaba",
        WORKSPACE_PRODUCTS: "facebook_products",
        WORKSPACE_COMPARISONS: "mercadolibre",
        WORKSPACE_TRACKING: "alibaba",
        WORKSPACE_IMPORT: "alibaba",
        WORKSPACE_TOOLS: "facebook",
        WORKSPACE_SETTINGS: "alibaba",
    }
    return mapping.get(view, "alibaba")
