"""Estructuras de datos compartidas."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Offer:
    """Un producto con descuento."""

    product_id: str
    name: str
    price: float | None
    regular_price: float | None
    pct: int
    available: bool = True
    pro_only: bool = False
    viral: bool = False


@dataclass
class Candidate:
    """Restaurante de la lista "Promos" cuyo descuento anunciado supera el mínimo."""

    store_id: int
    slug: str
    name: str
    product_pct: int = 0
    product_tag: str = ""
    store_wide_pct: int = 0
    store_wide_text: str = ""
    distance_km: float | None = None

    @property
    def best_pct(self) -> int:
        return max(self.product_pct, self.store_wide_pct)


@dataclass
class Alert:
    """Lo que se envía al celular: una tienda y sus ofertas."""

    kind: str  # "restaurante" | "tienda" | "cadena"
    store_id: str
    store_name: str
    url: str
    offers: list[Offer] = field(default_factory=list)
    store_wide_text: str = ""
    store_wide_pct: int = 0
    # Descuento que el local anuncia pero cuyo producto no aparece en la web.
    announced_text: str = ""
    announced_pct: int = 0
    distance_km: float | None = None

    @property
    def best_pct(self) -> int:
        pcts = [offer.pct for offer in self.offers]
        if self.store_wide_text:
            pcts.append(self.store_wide_pct)
        if self.announced_text:
            pcts.append(self.announced_pct)
        return max(pcts, default=0)

    def is_empty(self) -> bool:
        return not (self.offers or self.store_wide_text or self.announced_text)


@dataclass
class ScanResult:
    """Resultado de revisar una sección (restaurantes, tiendas o cadenas)."""

    name: str
    alerts: list[Alert] = field(default_factory=list)
    checked: int = 0
    error: str | None = None
    blocked: bool = False
    notes: list[str] = field(default_factory=list)
    top_offers: list[tuple[int, str, str]] = field(default_factory=list)

    def remember_top(self, offers: list[Offer], store_name: str, limit: int = 5) -> None:
        """Guarda las mejores ofertas vistas (aunque no lleguen al mínimo)."""
        for offer in offers:
            if offer.available and offer.pct > 0:
                self.top_offers.append((offer.pct, offer.name, store_name))
        self.top_offers.sort(key=lambda item: -item[0])
        del self.top_offers[limit:]
