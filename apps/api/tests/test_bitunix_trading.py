"""Bitunix private calls, against a stub transport.

There is no live key here, so these pin the two things that are ours to get
right whatever the venue does: the shape of the signature, and that the
bytes we sign are the bytes we send. The concatenation order itself is
documented as unverified in `bitunix_trading` — these tests are what makes
correcting it a one-line change with immediate feedback.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from quanta.exchanges.bitunix_trading import (
    BitunixTradingAdapter,
    sign_request,
    signature_payload,
)
from quanta.exchanges.trading import (
    Credentials,
    MarginMode,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    StopType,
    TimeInForce,
    TradeSide,
    TradingError,
)

CREDENTIALS = Credentials(api_key="key-123", api_secret="secret-456")


class Recorder:
    """A transport that records what was sent and replies with canned data."""

    def __init__(self, payload: Any = None, status: int = 200, code: str = "0") -> None:
        self.requests: list[httpx.Request] = []
        self._payload = payload
        self._status = status
        self._code = code

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            self._status, json={"code": self._code, "msg": "ok", "data": self._payload}
        )

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def adapter_for(recorder: Recorder) -> BitunixTradingAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(recorder.handler),
        base_url="https://fapi.test",
        headers={"Content-Type": "application/json"},
    )
    return BitunixTradingAdapter(client=client)


class TestSignaturePayload:
    def test_fields_appear_in_the_documented_order(self) -> None:
        assert (
            signature_payload(nonce="N", timestamp="T", api_key="K", query=None, body="BODY")
            == "NTKBODY"
        )

    def test_query_parameters_are_sorted_and_joined_without_separators(self) -> None:
        payload = signature_payload(
            nonce="N",
            timestamp="T",
            api_key="K",
            query={"symbol": "BTCUSDT", "limit": 10},
            body="",
        )
        # limit before symbol, each as key immediately followed by value.
        assert payload == "NTKlimit10symbolBTCUSDT"

    def test_none_parameters_are_dropped_because_they_are_not_sent(self) -> None:
        with_none = signature_payload(
            nonce="N", timestamp="T", api_key="K", query={"symbol": "X", "other": None}, body=""
        )
        without = signature_payload(
            nonce="N", timestamp="T", api_key="K", query={"symbol": "X"}, body=""
        )
        assert with_none == without


class TestSigning:
    def test_two_rounds_with_the_secret_only_in_the_second(self) -> None:
        first = hashlib.sha256(b"NTkey-123BODY").hexdigest()
        expected = hashlib.sha256(f"{first}secret-456".encode()).hexdigest()

        assert sign_request(CREDENTIALS, nonce="N", timestamp="T", body="BODY") == expected

    def test_the_secret_never_appears_in_the_signature(self) -> None:
        signed = sign_request(CREDENTIALS, nonce="N", timestamp="T", body="")
        assert "secret-456" not in signed

    def test_a_different_body_changes_the_signature(self) -> None:
        one = sign_request(CREDENTIALS, nonce="N", timestamp="T", body="a")
        two = sign_request(CREDENTIALS, nonce="N", timestamp="T", body="b")
        assert one != two


class TestRequestShape:
    async def test_headers_carry_the_key_nonce_timestamp_and_sign(self) -> None:
        recorder = Recorder(payload=[])
        await adapter_for(recorder).positions(CREDENTIALS)

        headers = recorder.last.headers
        assert headers["api-key"] == "key-123"
        assert len(headers["nonce"]) == 32
        assert headers["timestamp"].isdigit()
        assert len(headers["sign"]) == 64

    async def test_the_secret_is_never_a_header(self) -> None:
        recorder = Recorder(payload=[])
        await adapter_for(recorder).positions(CREDENTIALS)
        assert "secret-456" not in str(dict(recorder.last.headers))

    async def test_the_signed_bytes_are_the_sent_bytes(self) -> None:
        """A body serialised twice would sign one string and send another."""
        recorder = Recorder(payload={"orderId": "1"})
        await adapter_for(recorder).place_order(
            CREDENTIALS,
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal("0.5"),
                client_id="abc",
            ),
        )

        sent = recorder.last.content.decode()
        expected = sign_request(
            CREDENTIALS,
            nonce=recorder.last.headers["nonce"],
            timestamp=recorder.last.headers["timestamp"],
            body=sent,
        )
        assert recorder.last.headers["sign"] == expected

    async def test_each_call_uses_a_fresh_nonce(self) -> None:
        recorder = Recorder(payload=[])
        adapter = adapter_for(recorder)
        await adapter.positions(CREDENTIALS)
        await adapter.positions(CREDENTIALS)

        nonces = {r.headers["nonce"] for r in recorder.requests}
        assert len(nonces) == 2


class TestOrderPayload:
    async def test_the_spec_field_names_are_used(self) -> None:
        recorder = Recorder(payload={"orderId": "1"})
        await adapter_for(recorder).place_order(
            CREDENTIALS,
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                qty=Decimal("1.25"),
                client_id="cid-1",
                price=Decimal("64000.5"),
                trade_side=TradeSide.OPEN,
                time_in_force=TimeInForce.POST_ONLY,
                reduce_only=True,
            ),
        )
        body = json.loads(recorder.last.content)

        assert body["symbol"] == "BTCUSDT"
        assert body["side"] == "SELL"
        assert body["orderType"] == "LIMIT"
        assert body["effect"] == "POST_ONLY"
        assert body["tradeSide"] == "OPEN"
        assert body["clientId"] == "cid-1"
        assert body["reduceOnly"] is True

    async def test_decimals_are_sent_as_strings(self) -> None:
        """A float would round the quantity on its way to the exchange."""
        recorder = Recorder(payload={"orderId": "1"})
        await adapter_for(recorder).place_order(
            CREDENTIALS,
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                qty=Decimal("0.00000001"),
                client_id="cid",
                price=Decimal("64000.123456"),
            ),
        )
        body = json.loads(recorder.last.content)
        # Not "1E-8": scientific notation is not a quantity any venue reads
        # back as one satoshi.
        assert body["qty"] == "0.00000001"
        assert body["price"] == "64000.123456"

    async def test_attached_exits_are_sent_with_the_order(self) -> None:
        recorder = Recorder(payload={"orderId": "1"})
        await adapter_for(recorder).place_order(
            CREDENTIALS,
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal(1),
                client_id="cid",
                sl_price=Decimal(60000),
                tp_price=Decimal(70000),
                sl_stop_type=StopType.MARK_PRICE,
            ),
        )
        body = json.loads(recorder.last.content)
        assert body["slPrice"] == "60000"
        assert body["tpPrice"] == "70000"
        assert body["slStopType"] == "MARK_PRICE"

    async def test_unset_exits_are_omitted_rather_than_sent_as_null(self) -> None:
        recorder = Recorder(payload={"orderId": "1"})
        await adapter_for(recorder).place_order(
            CREDENTIALS,
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal(1),
                client_id="cid",
            ),
        )
        body = json.loads(recorder.last.content)
        assert "slPrice" not in body
        assert "price" not in body


class TestResponses:
    async def test_an_error_code_becomes_an_exception(self) -> None:
        recorder = Recorder(payload=None, code="10001")
        with pytest.raises(TradingError, match="ok"):
            await adapter_for(recorder).positions(CREDENTIALS)

    async def test_positions_are_parsed(self) -> None:
        recorder = Recorder(
            payload=[
                {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "qty": "0.5",
                    "avgOpenPrice": "64000",
                    "leverage": 10,
                    "marginMode": "ISOLATION",
                    "markPrice": "64500",
                    "unrealizedPNL": "250",
                }
            ]
        )
        (position,) = await adapter_for(recorder).positions(CREDENTIALS)

        assert position.qty == Decimal("0.5")
        assert position.entry_price == Decimal(64000)
        assert position.margin_mode is MarginMode.ISOLATED
        assert position.unrealised_pnl == Decimal(250)

    async def test_one_unparseable_row_does_not_lose_the_others(self) -> None:
        recorder = Recorder(
            payload=[
                {"nonsense": True},
                {
                    "symbol": "ETHUSDT",
                    "side": "SELL",
                    "qty": "2",
                    "avgOpenPrice": "3000",
                    "leverage": 5,
                },
            ]
        )
        positions = await adapter_for(recorder).positions(CREDENTIALS)
        assert [p.symbol for p in positions] == ["ETHUSDT"]

    async def test_a_placed_order_is_reported_as_new_not_filled(self) -> None:
        """The place response says an id, not an outcome."""
        recorder = Recorder(payload={"orderId": "99"})
        order = await adapter_for(recorder).place_order(
            CREDENTIALS,
            OrderRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal(1),
                client_id="cid",
            ),
        )
        assert order.status is OrderStatus.NEW
        assert order.order_id == "99"
        assert order.filled_qty == Decimal(0)


class TestRetryability:
    async def test_a_timed_out_order_is_not_retryable(self) -> None:
        """It may have been placed. Resending would double the position."""

        def timeout(_: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("too slow")

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(timeout), base_url="https://fapi.test"
        )
        adapter = BitunixTradingAdapter(client=client)

        with pytest.raises(TradingError) as caught:
            await adapter.place_order(
                CREDENTIALS,
                OrderRequest(
                    symbol="BTCUSDT",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    qty=Decimal(1),
                    client_id="cid",
                ),
            )
        assert caught.value.retryable is False

    async def test_a_timed_out_read_is_retryable(self) -> None:
        def timeout(_: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("too slow")

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(timeout), base_url="https://fapi.test"
        )
        adapter = BitunixTradingAdapter(client=client)

        with pytest.raises(TradingError) as caught:
            await adapter.positions(CREDENTIALS)
        assert caught.value.retryable is True
