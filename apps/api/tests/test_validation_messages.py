"""Validation failures have to be readable.

The bug these came from: registering without a name answered "String
should have at least 1 character", which does not say which field or what
to do. A user who sees that has to guess.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from quanta.core.validation import field_label, humanise, summarise


class TestFieldLabels:
    def test_a_known_field_uses_the_name_on_screen(self) -> None:
        assert field_label(("body", "display_name")) == "Name"

    def test_an_unknown_field_is_made_readable(self) -> None:
        assert field_label(("body", "quiet_hours_from")) == "Quiet hours from"

    def test_wrapper_segments_are_dropped(self) -> None:
        assert field_label(("body",)) == "That value"

    def test_a_nested_field_uses_the_innermost_name(self) -> None:
        """That is the box the user is looking at."""
        assert field_label(("body", "limits", "max_leverage")) == "Max leverage"

    def test_list_indices_do_not_become_the_label(self) -> None:
        assert field_label(("body", "destinations", 0, "kind")) == "Kind"


class TestSentences:
    def test_an_empty_required_string_reads_as_required(self) -> None:
        """Not "must be at least 1 character", which is the same thing
        said in schema vocabulary."""
        sentence = humanise(
            {"type": "string_too_short", "loc": ("body", "display_name"), "ctx": {"min_length": 1}}
        )
        assert sentence == "Name is required."

    def test_a_real_length_rule_says_the_number(self) -> None:
        sentence = humanise(
            {"type": "string_too_short", "loc": ("body", "api_key"), "ctx": {"min_length": 8}}
        )
        assert sentence == "API key must be at least 8 characters."

    def test_a_missing_field_names_itself(self) -> None:
        assert humanise({"type": "missing", "loc": ("body", "email")}) == "Email is required."

    def test_a_bad_email_says_so_plainly(self) -> None:
        sentence = humanise(
            {
                "type": "value_error",
                "loc": ("body", "email"),
                "msg": "value is not a valid email address",
            }
        )
        assert sentence == "That email address does not look right."

    def test_a_number_out_of_range(self) -> None:
        sentence = humanise(
            {"type": "greater_than", "loc": ("body", "max_leverage"), "ctx": {"gt": 0}}
        )
        assert sentence == "Max leverage must be more than 0."

    def test_a_non_numeric_value(self) -> None:
        sentence = humanise({"type": "int_parsing", "loc": ("body", "max_leverage")})
        assert sentence == "Max leverage must be a number."

    def test_an_unmapped_error_still_names_the_field(self) -> None:
        """The part Pydantic leaves out is the part the user needs."""
        sentence = humanise(
            {"type": "something_new", "loc": ("body", "symbol"), "msg": "Is not supported"}
        )
        assert sentence.startswith("Symbol:")
        assert "is not supported" in sentence


class TestSummaries:
    def test_every_problem_is_reported_at_once(self) -> None:
        """A form that reveals its problems one at a time makes the user
        submit four times to learn four things."""
        text = summarise(
            [
                {"type": "missing", "loc": ("body", "email")},
                {"type": "missing", "loc": ("body", "password")},
            ]
        )
        assert "Email is required." in text
        assert "Password is required." in text

    def test_duplicates_are_said_once(self) -> None:
        text = summarise(
            [
                {"type": "missing", "loc": ("body", "email")},
                {"type": "missing", "loc": ("body", "email")},
            ]
        )
        assert text.count("Email is required.") == 1

    def test_an_empty_list_still_says_something(self) -> None:
        assert summarise([]) == "That request was not valid."


class TestOverHttp:
    async def test_registering_without_a_name_names_the_field(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        response = await client.post(
            f"{api_prefix}/auth/register",
            json={
                "email": "someone@example.com",
                "display_name": "",
                "password": "Quanta-Test-2026!",
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail == "Name is required."
        # The old message, which started this.
        assert "String should have" not in detail

    async def test_the_detail_is_a_string_not_a_list(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """The web client shows `detail` directly when it is a string."""
        response = await client.post(f"{api_prefix}/auth/register", json={})
        assert isinstance(response.json()["detail"], str)

    async def test_a_bad_email_is_readable(self, client: AsyncClient, api_prefix: str) -> None:
        response = await client.post(
            f"{api_prefix}/auth/register",
            json={
                "email": "not-an-email",
                "display_name": "Someone",
                "password": "Quanta-Test-2026!",
            },
        )
        assert "email address" in response.json()["detail"]

    @pytest.mark.parametrize("payload", [{}, {"email": "a@b.com"}])
    async def test_nothing_leaks_schema_vocabulary(
        self, client: AsyncClient, api_prefix: str, payload: dict
    ) -> None:
        response = await client.post(f"{api_prefix}/auth/register", json=payload)
        detail = response.json()["detail"]
        for jargon in ("String should", "Input should", "ctx", "loc", "value_error"):
            assert jargon not in detail
