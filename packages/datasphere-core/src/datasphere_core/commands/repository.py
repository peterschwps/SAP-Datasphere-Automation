import logging
from typing import Any
from urllib.parse import quote, urlencode

from datasphere_core.logging import SUCCESS
from datasphere_core.models.analytical_models import (
    AnalyticalModelsDetailsDict,
)
from datasphere_core.models.views import ViewDetailsDict
from datasphere_core.runtime.context import CommandContext

logger = logging.getLogger(__name__)

# Page sizes the search needs, it returns nothing without one
_ANALYTICAL_MODEL_PAGE_SIZE = 1000
_VIEW_PAGE_SIZE = 10000


async def search_repository(
    context: CommandContext,
    type_description: str,
    page_size: int,
) -> list[Any]:
    """
    Searches the repository for every object of one type. Callers name the
    type the way the tenant describes it, not the way its technical type
    reads.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.
        type_description (str): Type description to match, for example 'View'.
        page_size (int): Largest number of objects the search may return.

    Returns:
        list[Any]: Details of every matching object, as the tenant sent them.
    """
    params = {
        # Without a page size the search returns nothing at all
        "$top": page_size,
        "$skip": 0,
        "whyfound": "true",
        "$count": "true",
        "valuehierarchy": "folder_id",
        "facets": "all",
        "facetlimit": 5,
        "$apply": (
            "filter(Search.search(query='SCOPE:SEARCH_DESIGN "
            f'(technical_type_description:EQ(S):"{type_description}" AND '
            '(technical_type:EQ(S):"DWC_REMOTE_TABLE" OR technical_type:'
            'EQ(S):"DWC_LOCAL_TABLE" OR technical_type:EQ(S):"DWC_VIEW" '
            'OR technical_type:EQ(S):"DWC_ERMODEL" OR technical_type:'
            'EQ(S):"DWC_DATAFLOW" OR technical_type:EQ(S):"DWC_IDT" OR '
            'technical_type:EQ(S):"DWC_BUSINESS_ENTITY" OR technical_type:'
            'EQ(S):"DWC_AUTH_SCENARIO" OR technical_type:EQ(S):'
            '"DWC_FACT_MODEL" OR technical_type:EQ(S):'
            '"DWC_CONSUMPTION_MODEL" OR technical_type:EQ(S):'
            '"DWC_PERSPECTIVE" OR kind:EQ(S):"sap.dis.dataflow" OR kind:'
            'EQ(S):"sap.dwc.dac" OR kind:EQ(S):"sap.repo.folder" OR kind:'
            'EQ(S):"sap.dwc.analyticModel" OR kind:EQ(S):'
            '"sap.dwc.taskChain" OR kind:EQ(S):"sap.dis.replicationflow" '
            'OR technical_type:EQ(S):"DWC_TRANSFORMATIONFLOW")) *\'))'
        ),
    }

    # The query is encoded by hand, because httpx would escape the
    # parentheses and asterisks the search syntax is built from
    logger.info("Searching the repository for '%s'...", type_description)
    response = await context.session.get(
        url=(
            "/deepsea/repository/search/$all"
            f"?{urlencode(params, safe='()*', quote_via=quote)}"
        ),
        headers={
            "Accept": "application/json",
            "Accept-Language": "en",
            "Cache-Control": "no-cache",
        },
    )
    objects = response.json()["value"]
    logger.log(
        SUCCESS,
        "Found %s objects of type '%s'.",
        len(objects),
        type_description,
    )
    return objects


async def search_views(context: CommandContext) -> list[ViewDetailsDict]:
    """
    Loads the metadata of every view of the tenant.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.

    Returns:
        list[ViewDetailsDict]: Details of every view.
    """
    return await search_repository(context, "View", _VIEW_PAGE_SIZE)


async def search_analytical_models(
    context: CommandContext,
) -> list[AnalyticalModelsDetailsDict]:
    """
    Loads the metadata of every analytical model of the tenant.

    Args:
        context (CommandContext): Authenticated session and progress
                                  callbacks.

    Returns:
        list[AnalyticalModelsDetailsDict]: Details of every analytical model.
    """
    return await search_repository(
        context,
        "Analytical Model",
        _ANALYTICAL_MODEL_PAGE_SIZE,
    )
