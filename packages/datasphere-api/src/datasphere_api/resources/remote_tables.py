import logging
from datetime import UTC, datetime

from datasphere_api.models import (
    StatisticsCreateOutcome,
    StatisticsDict,
    StatisticsInformationDict,
    StatisticsType,
    StatisticsUpdateOutcome,
)
from datasphere_api.resources.base import BaseResource

logger = logging.getLogger(__name__)


class RemoteTables(BaseResource):

    async def get_all_tables(
        self, space: str = "BWBRIDGESPACE"
    ) -> StatisticsDict:
        """
        Returns all remote tables of a space as a formatted dictionary.

        Args:
            space (str, optional): Space to load the remote tables from.
                                   Defaults to "BWBRIDGESPACE".

        Returns:
            StatisticsDict: Dictionary mapping table names to another
                            dictionary with information about the table.
        """
        # Fetch all table names
        logger.debug("Loading all remote tables...")
        response = await self.session.get(
            url=(
                f"{self._base_url}/dwaas-core/statistics/{space}"
                f"/remotetables?includeBusinessNames=true"
            ),
        )
        all_tables: StatisticsDict = {}
        for table in response.json()["tables"]:
            statistics_information: StatisticsInformationDict = {
                "statisticsSupported": table.get("statisticsSupported", True),
                "statisticsLimitedToRecordCount": table.get(
                    "statisticsLimitedToRecordCount", False
                ),
                "statisticsType": table.get("statisticsType"),
                "businessName": table.get("businessName", ""),
                "statisticsLatestUpdate": table.get("statisticsLatestUpdate"),
            }
            all_tables[table["tableName"]] = statistics_information

        # Convert "statisticsLatestUpdate" to an aware UTC datetime
        # (localization is up to the consumer)
        for table in all_tables.values():
            if isinstance(table["statisticsLatestUpdate"], str):
                converted_dt = datetime.strptime(
                    table["statisticsLatestUpdate"],
                    "%Y-%m-%d %H:%M:%S.%f000000",
                )
                table["statisticsLatestUpdate"] = converted_dt.replace(
                    tzinfo=UTC
                )

        return all_tables

    async def create_statistics(
        self,
        table: str,
        statistics_type: StatisticsType = "HISTOGRAM",
        space: str = "BWBRIDGESPACE",
    ) -> StatisticsCreateOutcome:
        """
        Creates statistics for a single remote table. Does not check if
        the table supports statistics or already has some.

        Args:
            table (str): Name of the remote table.
            statistics_type (StatisticsType): Type of the statistic.
                                              Default is 'HISTOGRAM'.
            space (str, optional): Space of the remote table.
                                   Defaults to "BWBRIDGESPACE".

        Returns:
            StatisticsCreateOutcome: 'created', 'already_exists' or 'failed'.
        """
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/statistics"
            f"/{space}/remoteTables/{table}"
            f"?type={statistics_type}",
            json={"type": statistics_type},
        )
        if (
            response.status_code == 500
            and "STATISTICS_ALREADY_EXISTS" in response.text
        ):
            return "already_exists"
        if response.status_code == 202:
            return "created"
        logger.error(
            "Error creating statistics for table '%s'. Status code: %s",
            table,
            response.status_code,
        )
        logger.debug("Response: %s\n", response.text)
        return "failed"

    async def update_statistics(
        self,
        table: str,
        statistics_type: StatisticsType = "HISTOGRAM",
        space: str = "BWBRIDGESPACE",
    ) -> StatisticsUpdateOutcome:
        """
        Changes the statistics type of a single remote table that
        already has statistics.

        Args:
            table (str): Name of the remote table.
            statistics_type (StatisticsType): New type of the statistic.
                                              Default is 'HISTOGRAM'.
            space (str, optional): Space of the remote table.
                                   Defaults to "BWBRIDGESPACE".

        Returns:
            StatisticsUpdateOutcome: 'updated', 'already_exists' or 'failed'.
        """
        response = await self.session.put(
            url=f"{self._base_url}/dwaas-core/statistics"
            f"/{space}/remoteTables/{table}"
            f"?type={statistics_type}",
            json={"type": statistics_type},
        )
        if (
            response.status_code == 500
            and "STATISTICS_ALREADY_EXISTS" in response.text
        ):
            return "already_exists"
        if response.status_code == 202:
            return "updated"
        logger.error(
            "Error updating statistics for table '%s'. Status code: %s",
            table,
            response.status_code,
        )
        logger.debug("Response: %s\n", response.text)
        return "failed"

    async def refresh_statistics(
        self,
        table: str,
        space: str = "BWBRIDGESPACE",
    ) -> bool:
        """
        Refreshes the statistics of a single remote table (keeping the same
        statistics type).

        Args:
            table (str): Name of the remote table.
            space (str, optional): Space of the remote table.
                                   Defaults to "BWBRIDGESPACE".

        Returns:
            bool: True if the refresh was started, else False.
        """
        response = await self.session.post(
            url=f"{self._base_url}/dwaas-core/statistics/"
            f"{space}/remoteTables/{table}/refresh"
        )
        if response.status_code != 202:
            logger.error(
                "Error refreshing statistics for table '%s'. "
                "Status code: %s",
                table,
                response.status_code,
            )
            logger.debug("Response: %s\n", response.text)
            return False
        return True
