"""Local marketplace brand identification. No runtime CDN."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PLATFORM_ALIBABA = "alibaba"
PLATFORM_FACEBOOK = "facebook"
PLATFORM_ML = "mercadolibre"

_ASSETS_ROOT = Path(__file__).resolve().parents[3] / "assets" / "brands"


@dataclass(frozen=True, slots=True)
class BrandSpec:
    platform: str
    label: str
    alt: str
    kind: str
    src: str
    local_path: Path | None


def _image_spec(platform: str, filename: str, label: str) -> BrandSpec:
    path = _ASSETS_ROOT / filename
    return BrandSpec(
        platform=platform,
        label=label,
        alt=label,
        kind="image",
        src=f"/brands/{filename}",
        local_path=path,
    )


BRANDS: dict[str, BrandSpec] = {
    PLATFORM_ALIBABA: _image_spec(PLATFORM_ALIBABA, "alibaba.svg", "Alibaba"),
    PLATFORM_FACEBOOK: _image_spec(PLATFORM_FACEBOOK, "facebook.svg", "Facebook Marketplace"),
    PLATFORM_ML: _image_spec(PLATFORM_ML, "mercado-libre.svg", "Mercado Libre"),
}


def brand_spec(platform: str) -> BrandSpec:
    try:
        return BRANDS[platform]
    except KeyError as exc:
        raise ValueError(f"unknown marketplace brand: {platform}") from exc


def local_brand_files() -> tuple[Path, Path, Path]:
    alibaba = brand_spec(PLATFORM_ALIBABA).local_path
    facebook = brand_spec(PLATFORM_FACEBOOK).local_path
    mercado_libre = brand_spec(PLATFORM_ML).local_path
    if alibaba is None or facebook is None or mercado_libre is None:
        raise FileNotFoundError(
            "Alibaba, Facebook, and Mercado Libre brand files must exist locally"
        )
    return alibaba, facebook, mercado_libre


def brand_uses_runtime_cdn(spec: BrandSpec) -> bool:
    src = spec.src.strip().casefold()
    return src.startswith("http://") or src.startswith("https://")
