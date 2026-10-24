"""A small, explicitly illustrative crude-oil trade network.

All volumes are in thousand barrels per day (kb/d) and all unit costs in USD per barrel.
Supplies, demands, freight rates, differentials and chokepoint capacities are **illustrative
assumptions chosen for a portfolio demonstration**. They are not market quotes. Edit
``default_network`` (or build your own ``Network``) to model a different desk.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Origin:
    """A loading port: supply of crude priced off a benchmark plus a differential."""

    name: str
    benchmark: str
    differential: float  # USD/bbl added to the benchmark price
    supply_kbd: float


@dataclass(frozen=True)
class Destination:
    """A discharge port: demand for crude priced off a benchmark plus a differential."""

    name: str
    benchmark: str
    differential: float
    demand_kbd: float


@dataclass(frozen=True)
class Route:
    """A shipping lane between an origin and a destination."""

    name: str
    origin: str
    destination: str
    chokepoints: tuple[str, ...]
    freight: float  # USD/bbl
    transit_days: int
    tolls: float = 0.0  # USD/bbl (canal dues and similar)


@dataclass(frozen=True)
class Network:
    """Origins, destinations, routes and the capacity each chokepoint offers this desk."""

    origins: tuple[Origin, ...]
    destinations: tuple[Destination, ...]
    routes: tuple[Route, ...]
    chokepoint_capacity_kbd: dict[str, float] = field(default_factory=dict)
    base_insurance: float = 0.05  # USD/bbl on every cargo
    financing_rate: float = 0.06  # annual cost of carrying inventory in transit

    def __post_init__(self) -> None:
        origins = {o.name for o in self.origins}
        destinations = {d.name for d in self.destinations}
        for route in self.routes:
            if route.origin not in origins or route.destination not in destinations:
                raise ValueError(f"Route '{route.name}' refers to an unknown origin or destination")
            unknown = set(route.chokepoints) - set(self.chokepoint_capacity_kbd)
            if unknown:
                raise ValueError(
                    f"Route '{route.name}' uses chokepoints without capacity: {unknown}"
                )

    @property
    def benchmarks(self) -> set[str]:
        """Benchmarks that need a price in order to evaluate the network."""
        return {o.benchmark for o in self.origins} | {d.benchmark for d in self.destinations}

    def origin(self, name: str) -> Origin:
        """Look up an origin by name."""
        return next(o for o in self.origins if o.name == name)

    def destination(self, name: str) -> Destination:
        """Look up a destination by name."""
        return next(d for d in self.destinations if d.name == name)


def default_network() -> Network:
    """The demonstration network: three loading ports, three discharge ports, ten routes."""
    origins = (
        Origin("Houston", "WTI", 1.5, 1500.0),
        Origin("Ras Tanura", "BRENT", -1.0, 1800.0),
        Origin("Novorossiysk (CPC)", "BRENT", -2.0, 1200.0),
    )
    destinations = (
        Destination("Rotterdam", "BRENT", 0.0, 1400.0),
        Destination("Ningbo", "BRENT", 0.8, 1800.0),
        Destination("Sikka (India)", "BRENT", 0.4, 1200.0),
    )
    routes = (
        Route("Houston-Rotterdam", "Houston", "Rotterdam", (), 1.6, 14),
        Route(
            "Houston-Ningbo via Cape",
            "Houston",
            "Ningbo",
            ("Cape of Good Hope", "Malacca Strait"),
            4.2,
            45,
        ),
        Route(
            "Houston-Ningbo via Panama",
            "Houston",
            "Ningbo",
            ("Panama Canal", "Malacca Strait"),
            4.8,
            38,
            0.35,
        ),
        Route(
            "Houston-Sikka via Cape", "Houston", "Sikka (India)", ("Cape of Good Hope",), 3.8, 38
        ),
        Route(
            "Ras Tanura-Ningbo",
            "Ras Tanura",
            "Ningbo",
            ("Strait of Hormuz", "Malacca Strait"),
            1.5,
            18,
        ),
        Route("Ras Tanura-Sikka", "Ras Tanura", "Sikka (India)", ("Strait of Hormuz",), 0.7, 5),
        Route(
            "Ras Tanura-Rotterdam via Suez",
            "Ras Tanura",
            "Rotterdam",
            ("Strait of Hormuz", "Bab el-Mandeb Strait", "Suez Canal"),
            2.0,
            22,
            0.25,
        ),
        Route(
            "Ras Tanura-Rotterdam via Cape",
            "Ras Tanura",
            "Rotterdam",
            ("Strait of Hormuz", "Cape of Good Hope"),
            3.1,
            34,
        ),
        Route("CPC-Rotterdam", "Novorossiysk (CPC)", "Rotterdam", (), 0.9, 8),
        Route(
            "CPC-Ningbo via Suez",
            "Novorossiysk (CPC)",
            "Ningbo",
            ("Suez Canal", "Bab el-Mandeb Strait", "Malacca Strait"),
            2.6,
            32,
            0.25,
        ),
    )
    capacity = {
        "Strait of Hormuz": 4000.0,
        "Bab el-Mandeb Strait": 1500.0,
        "Suez Canal": 1500.0,
        "Malacca Strait": 4000.0,
        "Panama Canal": 600.0,
        "Cape of Good Hope": 4000.0,
    }
    return Network(origins, destinations, routes, capacity)
