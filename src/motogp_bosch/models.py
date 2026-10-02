from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rider:
    id: int | None
    first_name: str
    last_name: str
    town: str = ""
    province: str = ""
    address: str = ""
    birth_date: str = ""  # ISO yyyy-mm-dd, empty if unknown
    phone: str = ""
    email: str = ""
    paid: bool = False
    insured: bool = False
    insurance_id: str = ""
    notes: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def eligible(self) -> bool:
        """Only riders who have paid AND are insured may appear in a starting grid."""
        return self.paid and self.insured


@dataclass
class Bike:
    id: int | None
    rider_id: int
    brand: str
    model: str = ""
    cc: int | None = None
    year: int | None = None
    kind: str = "moto"
    race_number: int | None = None
    class_override: str | None = None
    withdrawn: bool = False
    notes: str = ""

    @property
    def display_name(self) -> str:
        """Text printed in the MOTO column, e.g. 'HONDA FOUR 500'."""
        text = f"{self.brand} {self.model}".strip()
        if self.cc and str(self.cc) not in text:
            text = f"{text} {self.cc}"
        return " ".join(text.split()).upper()


@dataclass
class GridRow:
    """One line of a printed starting grid."""
    bike_id: int
    rider_id: int
    position: int
    race_number: int | None
    first_name: str
    last_name: str
    bike: str
    year: int | None
