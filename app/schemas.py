"""Request schemas for incoming webhook events."""
from typing import Annotated, Literal, Union

from pydantic import AwareDatetime, BaseModel, Field, TypeAdapter


class BookingCreatedData(BaseModel):
    booking_id: str = Field(min_length=1, max_length=100)
    customer_email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    customer_name: str = Field(min_length=1, max_length=200)
    # AwareDatetime: a timestamp without a timezone is ambiguous, so reject it.
    starts_at: AwareDatetime


class BookingCancelledData(BaseModel):
    booking_id: str = Field(min_length=1, max_length=100)


class BookingCreatedEvent(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    type: Literal["booking.created"]
    data: BookingCreatedData


class BookingCancelledEvent(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    type: Literal["booking.cancelled"]
    data: BookingCancelledData


Event = Annotated[
    Union[BookingCreatedEvent, BookingCancelledEvent], Field(discriminator="type")
]
EVENT_ADAPTER: TypeAdapter = TypeAdapter(Event)
