from __future__ import annotations

from urllib.parse import urlencode

from .models import Cabin, FlightOption, Priority, SearchRequest


def expedia_search_url(option: FlightOption, request: SearchRequest) -> str:
    """Build Expedia's documented flight-search deeplink for an option's trip."""
    outbound = option.legs[0]
    departure_date = outbound.departure.date()
    if request.return_date:
        if len(option.legs) > 1:
            return_date = option.legs[1].departure.date()
        else:
            shift = departure_date - request.departure_date
            return_date = request.return_date + shift
        trip_type = "Roundtrip"
    else:
        return_date = departure_date
        trip_type = "oneway"

    cabin_class = {
        Cabin.ECONOMY: 3,
        Cabin.PREMIUM_ECONOMY: 3,
        Cabin.BUSINESS: 2,
        Cabin.FIRST: 1,
    }[request.cabin]
    query: dict[str, str | int] = {
        "load": 1,
        "FromAirport": outbound.origin,
        "ToAirport": outbound.destination,
        "FromTime": 362,
        "NumAdult": min(request.adults, 6),
        "Class": cabin_class,
        "currency": request.currency,
    }
    if request.return_date:
        query["ToTime"] = 362
    if len(option.airline_codes) == 1:
        query["Airline"] = option.airline_codes[0]
    if request.priority == Priority.NONSTOP or option.stops == 0:
        query["Direct"] = 1

    return (
        "https://www.expedia.com/go/flight/search/"
        f"{trip_type}/{departure_date.isoformat()}/{return_date.isoformat()}?"
        f"{urlencode(query)}"
    )


def google_flights_url(option: FlightOption, request: SearchRequest) -> str:
    """Open a Google Flights comparison query without calling an API."""
    outbound = option.legs[0]
    query = (
        f"Flights from {outbound.origin} to {outbound.destination} "
        f"on {outbound.departure.date().isoformat()}"
    )
    if request.return_date:
        return_date = (
            option.legs[1].departure.date()
            if len(option.legs) > 1
            else request.return_date
        )
        query += f" returning {return_date.isoformat()}"
    query += f" for {request.adults} adult"
    if request.adults != 1:
        query += "s"
    query += f" in {request.cabin.value.replace('_', ' ').lower()}"
    return "https://www.google.com/travel/flights?" + urlencode({"q": query})


def kayak_search_url(option: FlightOption, request: SearchRequest) -> str:
    """Build a Kayak route/date comparison link without calling an API."""
    outbound = option.legs[0]
    dates = outbound.departure.date().isoformat()
    if request.return_date:
        returning = (
            option.legs[1].departure.date()
            if len(option.legs) > 1
            else request.return_date
        )
        dates += f"/{returning.isoformat()}"
    travelers = f"{request.adults}adult" + ("s" if request.adults != 1 else "")
    route = f"{outbound.origin}-{outbound.destination}/{dates}/{travelers}"
    return f"https://www.kayak.com/flights/{route}?sort=bestflight_a"
