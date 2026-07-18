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
