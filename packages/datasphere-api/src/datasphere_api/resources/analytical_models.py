import logging
from urllib.parse import quote, urlencode
from uuid import uuid4

from datasphere_api.models import AnalyticalModelsDetailsDict
from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


class AnalyticalModels(BaseResource):

    async def get_all_analytical_models(
        self,
    ) -> list[AnalyticalModelsDetailsDict]:
        """
        Returns all analytical models as a list of dictionaries.

        Returns:
            list[AnalyticalModelsDetailsDict]: List of dictionaries with
                                               the analytical models.
        """
        # Fetch all analytical models
        url = f"{self._base_url}/deepsea/repository/search/$all"
        params = {
            "$top": 1000,  # can't be omitted, else request won't work
            "$skip": 0,
            "whyfound": "true",
            "$count": "true",
            "valuehierarchy": "folder_id",
            "facets": "all",
            "facetlimit": 5,
            "$apply": (
                "filter(Search.search(query='SCOPE:SEARCH_DESIGN "
                '(technical_type_description:EQ(S):"Analysemodell" AND '
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
        response = await self.session.get(
            url=f"{url}?{urlencode(params, safe='()*', quote_via=quote)}",
            headers={
                "Accept": "application/json",
                "Accept-Language": "de",
                "Cache-Control": "no-cache",
            },
        )
        all_analytical_models: list[AnalyticalModelsDetailsDict] = (
            response.json()["value"]
        )

        return all_analytical_models

    async def get_analytical_models_in_space(
        self, space_name: str
    ) -> list[AnalyticalModelsDetailsDict]:
        """
        Returns all analytical models of a specific space.

        Args:
            space_name (str): Name of the space.

        Returns:
            list[AnalyticalModelsDetailsDict]: List of dictionaries with
                                               the analytical models.
        """
        # Fetch all analytical models
        all_analytical_models_in_space = [
            model
            for model in await self.get_all_analytical_models()
            if model["space_name"] == space_name
        ]
        return all_analytical_models_in_space

    async def get_views_for_analytical_model(
        self, analytical_model_id: str
    ) -> dict[str, dict[str, str]]:
        """
        Returns all views that are used in an analytical model.

        Args:
            analytical_model_id (str): ID of the analytical model.

        Returns:
            dict[str, dict[str, str]]: Dictionary with analytical model
                                       ID as key and dictionary as value.
                                       This dictionary has view IDs as
                                       keys and view names as values.
        """
        # Fetch details
        url = f"{self._base_url}/deepsea/repository/dependencies/"
        params = {
            "ids": analytical_model_id,
            "recursive": True,
            "impact": True,
            "lineage": True,
            "details": (
                "#spaceName,#spaceLabel,qualified_name,@EndUserText.label,"
                "@EnterpriseSearch.enabled,owner,deployment_date,"
                "modification_date,#objectStatus,#businessType,#technicalType,"
                "@Analytics.provider,#isViewEntity,"
                "@DataWarehouse.remote.connection,#isToolingHidden,"
                "releaseStateValue,releaseDate,deprecationDate,"
                "decommissioningDate,@ObjectModel.supportedCapabilities,"
                "@DataWarehouse.consumption.external,#columnsCount,"
                "@Analytics.dbViewType,isMissingColumnLineage"
            ),
            "dependencyTypes": (
                "csn.query.from,sap.dis.source,sap.dis.targetOf,"
                "sap.dis.replicationflow.source,"
                "sap.dis.replicationflow.targetOf,"
                "sap.dwc.transformationflow.source,"
                "sap.dwc.transformationflow.targetOf,sap.dwc.idtEntity,"
                "csn.derivation.lookupEntity,csn.valueHelp.entity"
            ),
        }
        response = await self.session.get(
            url=url,
            params=params,
            headers={
                "Accept": "*/*",
                "x-request-id": str(uuid4()).replace("-", ""),
            },
        )
        model_details = response.json()[0]

        # Function for recursive iteration
        all_ids: list[tuple[str, str]] = []

        def iterate_recursively(entity: dict):
            if entity["properties"].get("#isViewEntity", "false") == "true":
                all_ids.append((entity["id"], entity["name"]))
            if len(entity["dependencies"]) > 0:
                for dependency in entity["dependencies"]:
                    iterate_recursively(dependency)

        # Iterate over all dependencies
        iterate_recursively(model_details)

        # Reverse list for bottom-up order
        all_ids.reverse()
        analytical_model_to_view_mapping = {analytical_model_id: dict(all_ids)}
        return analytical_model_to_view_mapping
