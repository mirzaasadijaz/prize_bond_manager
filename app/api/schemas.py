"""Request and response models of the HTTP API (Pydantic).

Bonds are sent in the *body* of a POST request, not in the address, so there is no limit on the
length of the web address: one request can carry 500, 1,000 or 10,000 bonds.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_BONDS = 100_000


class BondIn(BaseModel):
    """One bond to check.  A bare number (``"123456"`` or ``123456``) is accepted too."""

    number: str = Field(description="the bond number, e.g. 024132 (leading zeros do not matter)")
    denomination: int | None = Field(None, gt=0, description="the bond's price, e.g. 750")
    ref: str | None = Field(None, max_length=200,
                            description="anything you want back with a win, e.g. 'Copy 3 #12'")

    @model_validator(mode="before")
    @classmethod
    def _bare_number(cls, data):
        return {"number": data} if isinstance(data, (str, int)) and not isinstance(data, bool) \
            else data

    @field_validator("number", mode="before")
    @classmethod
    def _text(cls, value):
        return str(value).strip() if isinstance(value, (int, str)) and not isinstance(value, bool) \
            else value


class CheckRequest(BaseModel):
    bonds: list[BondIn] = Field(min_length=1, max_length=MAX_BONDS)
    denomination: int | None = Field(
        None, gt=0, description="price used for every bond that does not state its own")
    draw_ids: list[int] | None = Field(None, description="only look in these draws")
    since: date | None = Field(None, description="only look in draws on or after this date")

    model_config = {"json_schema_extra": {"example": {
        "denomination": 750,
        "bonds": ["100056", {"number": "777777", "ref": "Copy 2 #21"}, {"number": 900007,
                                                                      "denomination": 1500}]}}}


class WinOut(BaseModel):
    number: str
    denomination: int | None
    ref: str | None
    draw_id: int
    draw_date: str
    draw_label: str
    location: str
    prize_label: str
    prize_amount: int | None


class InvalidBond(BaseModel):
    index: int = Field(description="position of the bond in the request (0 = first)")
    number: str
    reason: str


class CheckResponse(BaseModel):
    checked: int
    winners: int = Field(description="how many bonds won at least once")
    hits: int = Field(description="how many wins in all (one bond can win in several draws)")
    draws_searched: int
    winning_numbers_searched: int
    elapsed_ms: float
    wins: list[WinOut]
    invalid: list[InvalidBond]


class DrawOut(BaseModel):
    id: int
    draw_date: str
    denomination: int | None
    label: str | None
    location: str | None
    source: str | None
    winning_numbers: int


class Health(BaseModel):
    status: str
    draws: int
    winning_numbers: int
