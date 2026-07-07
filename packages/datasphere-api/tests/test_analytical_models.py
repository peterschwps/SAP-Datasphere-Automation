import httpx
import respx

from datasphere_api import DatasphereClient

SEARCH_PATH = "/deepsea/repository/search/$all"
DEPENDENCIES_PATH = "/deepsea/repository/dependencies/"


def dependency_payload(view_ids: list[tuple[str, str]]) -> list[dict]:
    """
    Builds a nested dependencies payload where each view depends on the
    next one.

    Args:
        view_ids (list[tuple[str, str]]): View (id, name) tuples from top
                                          to bottom.

    Returns:
        list[dict]: Payload as returned by the dependencies endpoint.
    """
    node: dict = {
        "id": "leaf",
        "name": "LEAF",
        "properties": {"#isViewEntity": "false"},
        "dependencies": [],
    }
    for view_id, view_name in reversed(view_ids):
        node = {
            "id": view_id,
            "name": view_name,
            "properties": {"#isViewEntity": "true"},
            "dependencies": [node],
        }
    return [
        {
            "id": "model",
            "name": "MODEL",
            "properties": {"#isViewEntity": "false"},
            "dependencies": [node],
        }
    ]


@respx.mock
async def test_get_views_for_analytical_model(
    client: DatasphereClient,
) -> None:
    respx.get(path=DEPENDENCIES_PATH).mock(
        return_value=httpx.Response(
            200,
            json=dependency_payload([("v1", "View1"), ("v2", "View2")]),
        )
    )
    mapping = await client.analytical_models.get_views_for_analytical_model(
        "model-id"
    )

    # Views are mapped bottom-up
    assert mapping == {"model-id": {"v2": "View2", "v1": "View1"}}


@respx.mock
async def test_get_all_views_for_analytical_models(
    client: DatasphereClient,
) -> None:
    # First search returns the models, second one the views
    respx.get(path=SEARCH_PATH).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "m1", "name": "Model1", "space_name": "SP"}
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "v1", "name": "View1", "space_name": "SP_V"}
                    ]
                },
            ),
        ]
    )
    respx.get(path=DEPENDENCIES_PATH).mock(
        return_value=httpx.Response(
            200,
            json=dependency_payload([("v1", "View1"), ("v2", "View2")]),
        )
    )

    models = (
        await client.analytical_models.get_all_views_for_analytical_models()
    )

    # Resolved views become (space, name) tuples, unresolved views keep
    # their plain name
    assert models == {
        "m1": {
            "name": "Model1",
            "dependencies": {
                "v1": ("SP_V", "View1"),
                "v2": "View2",
            },
        }
    }
