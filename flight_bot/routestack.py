from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings
from .models import FlightOption, Leg, SearchRequest


class FlightSearchError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _duration_minutes(departure: datetime, arrival: datetime) -> int:
    try:
        return max(0, int((arrival - departure).total_seconds() // 60))
    except TypeError:
        # RouteStack sometimes returns local timestamps without offsets. Removing
        # offsets gives a useful schedule duration without pretending to convert
        # between airport time zones.
        start = departure.replace(tzinfo=None)
        end = arrival.replace(tzinfo=None)
        return max(0, int((end - start).total_seconds() // 60))


class RouteStackClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.routestack_base_url.rstrip("/"),
            timeout=httpx.Timeout(35.0),
            headers={"User-Agent": "on-demand-flight-telegram-bot/0.2"},
        )
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    def _signed_auth_body(self) -> dict[str, Any]:
        timestamp = int(time.time())
        nonce = secrets.token_urlsafe(24)
        message = f"{self.settings.routestack_api_key}:{timestamp}:{nonce}"
        digest = hmac.new(
            self.settings.routestack_api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).digest()
        signature = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return {
            "apiKey": self.settings.routestack_api_key,
            "timestamp": timestamp,
            "nonce": nonce,
            "hmac": signature,
        }

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at - 300:
            return self._token
        response = await self._client.post(
            "/mcp/auth/partner-token", json=self._signed_auth_body()
        )
        if response.is_error:
            raise FlightSearchError(
                f"RouteStack authentication failed ({response.status_code})."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise FlightSearchError(
                "RouteStack authentication returned invalid JSON."
            ) from exc
        token = payload.get("token")
        if not token:
            raise FlightSearchError("RouteStack authentication returned no token.")
        self._token = str(token)
        # RouteStack currently documents a 24-hour partner JWT.
        self._token_expires_at = time.monotonic() + 23 * 60 * 60
        return self._token

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = await self._access_token()
        response = await self._client.post(
            path,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            self._token = None
            token = await self._access_token()
            response = await self._client.post(
                path,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.is_error:
            raise FlightSearchError(
                f"RouteStack request failed ({response.status_code})."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise FlightSearchError("RouteStack returned invalid JSON.") from exc
        if payload.get("success") is False:
            detail = payload.get("message") or payload.get("code") or "unknown error"
            raise FlightSearchError(f"RouteStack rejected the search: {detail}")
        return payload

    async def resolve_location(
        self, query: str
    ) -> tuple[str, str, list[str]]:
        normalized = query.strip().upper()
        payload = await self._post(
            "/mcp/flight/locations", {"term": query.strip()}
        )
        raw_locations = payload.get("result") or []
        locations = [item for item in raw_locations if isinstance(item, dict)]
        exact = [
            item
            for item in locations
            if str(item.get("code", "")).upper() == normalized
        ]
        if exact:
            best = exact[0]
        elif locations:
            best = locations[0]
        elif re.fullmatch(r"[A-Z]{3}", normalized):
            return normalized, normalized, []
        else:
            raise FlightSearchError(
                f"I couldn't find an airport or city for “{query}”."
            )

        code = str(best.get("code", "")).upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise FlightSearchError(
                f"No searchable airport code was found for “{query}”."
            )
        label = best.get("fullname") or best.get("name") or code
        alternatives: list[str] = []
        for item in locations:
            alternate = str(item.get("code", "")).upper()
            if (
                re.fullmatch(r"[A-Z]{3}", alternate)
                and alternate != code
                and alternate not in alternatives
            ):
                alternatives.append(alternate)
            if len(alternatives) == 2:
                break
        return code, str(label), alternatives

    async def search(
        self, request: SearchRequest
    ) -> tuple[list[FlightOption], str, str]:
        origin_result, destination_result = await asyncio.gather(
            self.resolve_location(request.origin),
            self.resolve_location(request.destination),
        )
        origin_code, origin_label, nearby_origins = origin_result
        destination_code, destination_label, nearby_destinations = destination_result

        shifts = range(-3, 4) if request.flexible_dates else (0,)
        searches = []
        for shift in shifts:
            departure = request.departure_date + timedelta(days=shift)
            returning = (
                request.return_date + timedelta(days=shift)
                if request.return_date
                else None
            )
            if departure < date.today() or (returning and returning <= departure):
                continue
            searches.append(
                self._search_dates(
                    request,
                    origin_code,
                    destination_code,
                    departure,
                    returning,
                )
            )

        if request.nearby_airports:
            for alternate_origin in nearby_origins:
                searches.append(
                    self._search_dates(
                        request,
                        alternate_origin,
                        destination_code,
                        request.departure_date,
                        request.return_date,
                    )
                )
            for alternate_destination in nearby_destinations:
                searches.append(
                    self._search_dates(
                        request,
                        origin_code,
                        alternate_destination,
                        request.departure_date,
                        request.return_date,
                    )
                )

        # Keep concurrency modest because a flexible search can make several
        # RouteStack token-billed production calls.
        semaphore = asyncio.Semaphore(3)

        async def limited(coroutine: Any) -> Any:
            async with semaphore:
                return await coroutine

        results = await asyncio.gather(
            *(limited(search) for search in searches), return_exceptions=True
        )
        offers: list[FlightOption] = []
        errors: list[Exception] = []
        for result in results:
            if isinstance(result, Exception):
                errors.append(result)
            else:
                offers.extend(result)
        if not offers and errors:
            raise FlightSearchError(str(errors[0]))

        unique: dict[tuple[Any, ...], FlightOption] = {}
        for offer in offers:
            if request.max_budget is not None and offer.total_price > request.max_budget:
                continue
            key = (
                offer.airline_codes,
                tuple((leg.departure, leg.arrival) for leg in offer.legs),
                offer.total_price,
            )
            unique.setdefault(key, offer)
        return list(unique.values()), origin_label, destination_label

    async def _search_dates(
        self,
        request: SearchRequest,
        origin: str,
        destination: str,
        departure: date,
        returning: date | None,
    ) -> list[FlightOption]:
        body: dict[str, Any] = {
            "origin": origin,
            "destination": destination,
            "departureDate": departure.isoformat(),
            "adults": request.adults,
            "currency": request.currency,
            "cabinClass": request.cabin.value,
        }
        if returning:
            body["returnDate"] = returning.isoformat()
        payload = await self._post("/mcp/flight/search", body)
        raw_results = payload.get("result") or []
        if isinstance(raw_results, dict):
            raw_results = raw_results.get("result") or raw_results.get("flights") or []
        if not isinstance(raw_results, list):
            raise FlightSearchError(
                "RouteStack flight search returned an unsupported result shape."
            )

        currency = str(payload.get("currency") or request.currency).upper()
        parsed: list[FlightOption] = []
        for index, raw in enumerate(raw_results[: self.settings.max_results]):
            if not isinstance(raw, dict):
                continue
            option = self._parse_offer(
                raw,
                currency,
                index,
                origin,
                destination,
                returning is not None,
                payload.get("searchFilterObj"),
            )
            if option:
                parsed.append(option)
        return parsed

    @staticmethod
    def _parse_offer(
        raw: dict[str, Any],
        currency: str,
        index: int,
        origin: str,
        destination: str,
        round_trip: bool,
        search_filter: Any = None,
    ) -> FlightOption | None:
        raw_segments = raw.get("flights") or raw.get("segments") or []
        if not isinstance(raw_segments, list) or not raw_segments:
            return None

        segments: list[dict[str, Any]] = [
            segment for segment in raw_segments if isinstance(segment, dict)
        ]
        if not segments:
            return None

        split_at: int | None = None
        if round_trip:
            for candidate in range(1, len(segments)):
                departure_code = str(
                    segments[candidate].get("departure")
                    or segments[candidate].get("origin")
                    or ""
                ).upper()
                if departure_code == destination:
                    split_at = candidate
                    break
        segment_groups = (
            [segments[:split_at], segments[split_at:]]
            if split_at is not None
            else [segments]
        )

        legs: list[Leg] = []
        airlines: list[str] = []
        airline_codes: list[str] = []
        for group in segment_groups:
            if not group:
                continue
            first, last = group[0], group[-1]
            departure = _datetime(
                first.get("departureTime")
                or first.get("departureAt")
                or first.get("departure_time")
            )
            arrival = _datetime(
                last.get("arrivalTime")
                or last.get("arrivalAt")
                or last.get("arrival_time")
            )
            if not departure or not arrival:
                return None
            leg_origin = str(
                first.get("departure") or first.get("origin") or origin
            ).upper()
            leg_destination = str(
                last.get("arrival") or last.get("destination") or destination
            ).upper()
            layovers: list[tuple[str, int]] = []
            for current, following in zip(group, group[1:]):
                current_arrival = _datetime(
                    current.get("arrivalTime")
                    or current.get("arrivalAt")
                    or current.get("arrival_time")
                )
                next_departure = _datetime(
                    following.get("departureTime")
                    or following.get("departureAt")
                    or following.get("departure_time")
                )
                airport = str(
                    current.get("arrival")
                    or current.get("destination")
                    or ""
                ).upper()
                if current_arrival and next_departure and airport:
                    layovers.append(
                        (
                            airport,
                            _duration_minutes(current_arrival, next_departure),
                        )
                    )
            for segment in group:
                airline = str(
                    segment.get("airline")
                    or segment.get("airlineName")
                    or segment.get("carrierName")
                    or ""
                ).strip()
                code = str(
                    segment.get("airlineCode")
                    or segment.get("carrierCode")
                    or segment.get("flightCode")
                    or ""
                ).strip().upper()
                if airline and airline not in airlines:
                    airlines.append(airline)
                if code:
                    code = code[:2]
                    if code not in airline_codes:
                        airline_codes.append(code)
            legs.append(
                Leg(
                    origin=leg_origin,
                    destination=leg_destination,
                    departure=departure,
                    arrival=arrival,
                    duration_minutes=_duration_minutes(departure, arrival),
                    stops=max(0, len(group) - 1),
                    layovers=tuple(layovers),
                )
            )

        price = next(
            (
                parsed
                for parsed in (
                    _number(raw.get("showOurprice")),
                    _number(raw.get("ourprice")),
                    _number(raw.get("totalFare")),
                    _number(raw.get("totalPrice")),
                    _number(raw.get("price")),
                )
                if parsed is not None
            ),
            None,
        )
        if price is None or not legs:
            return None

        bags = raw.get("includedCheckedBags")
        if isinstance(bags, dict):
            bags = bags.get("quantity")
        checked_bags = int(bags) if isinstance(bags, (int, float)) else None
        offer_id = str(
            raw.get("fareSourceCode") or raw.get("id") or f"routestack-{index}"
        )
        display_airlines = tuple(airlines or airline_codes or ["Airline not reported"])
        return FlightOption(
            offer_id=offer_id,
            airlines=display_airlines,
            airline_codes=tuple(airline_codes),
            legs=tuple(legs),
            total_price=price,
            currency=currency,
            checked_bags=checked_bags,
            source="RouteStack",
            booking_payload=raw,
            search_filter=(
                search_filter if isinstance(search_filter, dict) else None
            ),
        )

    async def create_checkout_url(
        self, option: FlightOption, request: SearchRequest
    ) -> str:
        """Revalidate an offer and create RouteStack's external checkout URL."""
        if not option.booking_payload:
            raise FlightSearchError(
                "This result did not include the data needed for checkout."
            )

        revalidate_body: dict[str, Any] = {
            "fareSourceCode": option.offer_id,
            "searchListPrice": option.booking_payload,
        }
        if option.search_filter:
            revalidate_body["searchFilterObj"] = option.search_filter

        revalidated = await self._post(
            "/mcp/flight/revalidate", revalidate_body
        )
        revalidated_flight = (
            revalidated.get("result")
            or revalidated.get("revalidate")
            or option.booking_payload
        )
        first_leg = option.legs[0]
        payment_body: dict[str, Any] = {
            "flight": revalidated_flight,
            "origin": first_leg.origin,
            "destination": first_leg.destination,
            "departureDate": first_leg.departure.date().isoformat(),
            "adults": request.adults,
            "cabinClass": request.cabin.value,
            "currency": request.currency,
        }
        if request.return_date:
            payment_body["returnDate"] = request.return_date.isoformat()

        payload = await self._post(
            "/mcp/flight/get-payment-url", payment_body
        )
        result = payload.get("result")
        url = (
            payload.get("url")
            or (result.get("url") if isinstance(result, dict) else None)
            or (result if isinstance(result, str) else None)
        )
        if not isinstance(url, str) or urlparse(url).scheme != "https":
            raise FlightSearchError(
                "RouteStack did not return a secure checkout link."
            )
        return url
