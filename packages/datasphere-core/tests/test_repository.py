from collections.abc import Callable
from typing import Any

import httpx
import respx
from datasphere_core import CommandContext
from datasphere_core.commands.repository import (
    search_analytical_models,
    search_views,
)

SEARCH_PATH = "/deepsea/repository/search/$all"


def _search_route(objects: list[dict[str, Any]]) -> respx.Route:
    """
    Mocks the repository search that both domains send.
    """
    return respx.get(path=SEARCH_PATH).mock(
        return_value=httpx.Response(200, json={"value": objects})
    )


@respx.mock
async def test_search_asks_for_the_requested_type(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that both searches differ only in their type and page size.
    """
    search = _search_route([])

    await search_views(context())
    await search_analytical_models(context())

    views, models = (call.request.url.params for call in search.calls)

    # The tenant describes its types in English, hence the Accept-Language
    assert 'technical_type_description:EQ(S):"View"' in views["$apply"]
    assert (
        'technical_type_description:EQ(S):"Analytic Model"'
        in models["$apply"]
    )
    assert search.calls[0].request.headers["Accept-Language"] == "en"

    # Each search keeps the page size it was written with
    assert views["$top"] == "10000"
    assert models["$top"] == "1000"


@respx.mock
async def test_search_sends_its_syntax_unescaped(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that the search filter reaches the tenant with its syntax intact.
    """
    search = _search_route([])

    await search_views(context())

    # Read the raw query: parsing it back would undo the escaping under test
    query = search.calls.last.request.url.query.decode()

    # Left to httpx, the parentheses and asterisks of the search syntax would
    # be escaped and the filter would stop matching
    assert "filter(Search.search(" in query
    assert query.endswith("%20*%27))")

    # Without a page size the search returns nothing at all
    assert "%24top=10000" in query


@respx.mock
async def test_search_keeps_its_headers_out_of_the_session(
    session: httpx.AsyncClient,
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that per-request headers never leak into the shared session.
    """
    session.headers.update(
        {
            "Authorization": "Bearer access-token",
            "X-Client-Default": "preserved",
        }
    )
    search = _search_route([])

    await search_views(context())

    # The request carries the session defaults next to its own headers
    headers = search.calls.last.request.headers
    assert headers["Authorization"] == "Bearer access-token"
    assert headers["X-Client-Default"] == "preserved"
    assert headers["Accept"] == "application/json"
    assert headers["Accept-Language"] == "en"
    assert headers["Cache-Control"] == "no-cache"

    # The session itself keeps none of them
    assert "Accept-Language" not in session.headers
    assert "Cache-Control" not in session.headers
    assert session.headers["Authorization"] == "Bearer access-token"


@respx.mock
async def test_search_returns_what_the_tenant_sent(
    context: Callable[..., CommandContext],
) -> None:
    """
    Checks that the search hands the repository entries through unchanged.
    """
    _search_route([{"id": "ID_1", "name": "VIEW_A", "space_name": "SPACE_A"}])

    views = await search_views(context())

    assert views == [
        {"id": "ID_1", "name": "VIEW_A", "space_name": "SPACE_A"}
    ]
