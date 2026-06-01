from datetime import datetime

import httpx
from dateutil import tz

from datasphere.automation import DatasphereAutomation
from utils.filehandler import settings
from utils.logging import logger
from utils.types import (
    StatisticsDict,
    StatisticsInformationDict,
    StatisticsType,
)

# Important URLs from settings
DATASPHERE_URL: str = settings["Setup"]["DATASPHERE_URL"]


class RemoteTables(DatasphereAutomation):
    def __init__(self, session: httpx.AsyncClient | None = None):
        if session is not None:
            self.session = session
        else:
            super().__init__()

    async def initialize(self) -> None:
        """
        Initializes the Datasphere session.
        """
        self.session: httpx.AsyncClient = await (
            self.initialize_datasphere_session()
        )

    async def _get_all_table_names(self) -> StatisticsDict:
        """
        Returns all table names as a formatted dictionary.

        Returns:
            dict: Dictionary mapping table names to another dictionary with
                  information about the table.
        """

        # Fetch all table names
        logger.debug("Loading all remote tables...")
        response = await self.session.get(
            url=(
                f"{DATASPHERE_URL}/dwaas-core/statistics/BWBRIDGESPACE"
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

        # Convert "statisticsLatestUpdate" to datetime object with timezone
        for table in all_tables.values():
            if isinstance(table["statisticsLatestUpdate"], str):
                converted_dt = datetime.strptime(
                    table["statisticsLatestUpdate"],
                    "%Y-%m-%d %H:%M:%S.%f000000",
                )
                converted_dt = converted_dt.replace(tzinfo=tz.gettz("UTC"))
                converted_dt_with_timezone = converted_dt.astimezone(
                    tz.gettz("Europe/Berlin")
                )
                table["statisticsLatestUpdate"] = converted_dt_with_timezone

        return all_tables

    async def create_statistics(
        self, type: StatisticsType = "HISTOGRAM", thread_count: int = 5
    ) -> None:
        """
        Creates statistics for all tables.

        Args:
            type (StatisticsType): Type of the statistic.
                                   Default is 'HISTOGRAM'.
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 5.
        """

        # Read all table names
        all_tables = await self._get_all_table_names()

        # Function to create statistics
        async def create_statistics_for_table(table: str) -> None:
            # Only create statistics for tables that support them
            if (
                all_tables[table]["statisticsSupported"]
                and all_tables[table]["statisticsType"] != type
            ):
                if all_tables[table]["statisticsType"] is None:
                    response = await self.session.post(
                        url=f"{DATASPHERE_URL}/dwaas-core/statistics"
                        f"/BWBRIDGESPACE/remoteTables/{table}?type={type}",
                        json={"type": type},
                    )
                elif all_tables[table]["statisticsType"] != type:
                    response = await self.session.put(
                        url=f"{DATASPHERE_URL}/dwaas-core/statistics"
                        f"/BWBRIDGESPACE/remoteTables/{table}?type={type}",
                        json={"type": type},
                    )

                # Evaluate response
                if (
                    response.status_code == 500
                    and "STATISTICS_ALREADY_EXISTS" in response.text
                ):
                    logger.debug(
                        "Statistics for table '%s' already exists. "
                        "Skipping...",
                        table,
                    )
                elif response.status_code == 202:
                    logger.info("Created statistics for table '%s'.", table)
                else:
                    logger.error(
                        "Error creating statistics for table '%s'. "
                        "Status code: %s",
                        table,
                        response.status_code,
                    )
                    logger.debug("Response: %s\n", response.text)

        # Iterate over all table names and create statistics
        await self.run_async_tasks(
            all_tables, create_statistics_for_table, thread_count
        )

    async def refresh_statistics(self, thread_count: int = 5) -> None:
        """
        Refreshes statistics for all tables.

        Args:
            thread_count (int, optional): Amount of concurrent asynchronous
                                          requests. Default is 5.
        """

        # Read all table names
        all_tables = await self._get_all_table_names()

        # Function to refresh statistics
        # Only refresh statistics for tables that support them
        # and have statistics
        async def refresh_statistics_for_table(table: str) -> None:
            if (
                all_tables[table]["statisticsSupported"]
                and all_tables[table]["statisticsType"] is not None
            ):
                response = await self.session.post(
                    url=f"{DATASPHERE_URL}/dwaas-core/statistics/"
                    f"BWBRIDGESPACE/remoteTables/{table}/refresh"
                )
                if response.status_code == 202:
                    logger.info("Refreshed statistics for table '%s'.", table)
                else:
                    logger.error(
                        "Error refreshing statistics for table '%s'. "
                        "Status code: %s",
                        table,
                        response.status_code,
                    )
                    logger.debug("Response: %s\n", response.text)

        # Iterate over all table names and refresh statistics
        await self.run_async_tasks(
            all_tables, refresh_statistics_for_table, thread_count
        )
