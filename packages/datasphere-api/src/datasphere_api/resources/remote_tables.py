import logging
from datetime import UTC, datetime

from datasphere_api.models import (
    StatisticsDict,
    StatisticsInformationDict,
    StatisticsResult,
    StatisticsType,
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
        statistics_type: StatisticsType = "HISTOGRAM",
        space: str = "BWBRIDGESPACE",
        thread_count: int = 5,
    ) -> list[StatisticsResult]:
        """
        Creates statistics for all tables of a space. Tables that don't
        support statistics or already have statistics of the given type
        are skipped.

        Args:
            statistics_type (StatisticsType): Type of the statistic.
                                              Default is 'HISTOGRAM'.
            space (str, optional): Space of the remote tables.
                                   Defaults to "BWBRIDGESPACE".
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 5.

        Returns:
            list[StatisticsResult]: Outcome for each table.
        """

        # Read all table names
        all_tables = await self.get_all_tables(space)
        results: list[StatisticsResult] = []

        # Function to create statistics
        async def create_statistics_for_table(table: str) -> None:
            # Only create statistics for tables that support them
            # and don't have statistics of the given type yet
            if not (
                all_tables[table]["statisticsSupported"]
                and all_tables[table]["statisticsType"] != statistics_type
            ):
                results.append({"tableName": table, "status": "skipped"})
                return

            # Create new statistics or update the existing type
            if all_tables[table]["statisticsType"] is None:
                status = "created"
                response = await self.session.post(
                    url=f"{self._base_url}/dwaas-core/statistics"
                    f"/{space}/remoteTables/{table}"
                    f"?type={statistics_type}",
                    json={"type": statistics_type},
                )
            else:
                status = "updated"
                response = await self.session.put(
                    url=f"{self._base_url}/dwaas-core/statistics"
                    f"/{space}/remoteTables/{table}"
                    f"?type={statistics_type}",
                    json={"type": statistics_type},
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
                results.append(
                    {"tableName": table, "status": "already_exists"}
                )
            elif response.status_code == 202:
                logger.info("Created statistics for table '%s'.", table)
                results.append({"tableName": table, "status": status})
            else:
                logger.error(
                    "Error creating statistics for table '%s'. "
                    "Status code: %s",
                    table,
                    response.status_code,
                )
                logger.debug("Response: %s\n", response.text)
                results.append({"tableName": table, "status": "failed"})

        # Iterate over all table names and create statistics
        await self._client.run_async_tasks(
            all_tables, create_statistics_for_table, thread_count
        )
        return results

    async def refresh_statistics(
        self,
        space: str = "BWBRIDGESPACE",
        thread_count: int = 5,
    ) -> list[StatisticsResult]:
        """
        Refreshes statistics for all tables of a space. Tables that don't
        support statistics or don't have statistics are skipped.

        Args:
            space (str, optional): Space of the remote tables.
                                   Defaults to "BWBRIDGESPACE".
            thread_count (int, optional): Amount of concurrent
                                          asynchronous requests.
                                          Default is 5.

        Returns:
            list[StatisticsResult]: Outcome for each table.
        """

        # Read all table names
        all_tables = await self.get_all_tables(space)
        results: list[StatisticsResult] = []

        # Function to refresh statistics
        # Only refresh statistics for tables that support them
        # and have statistics
        async def refresh_statistics_for_table(table: str) -> None:
            if not (
                all_tables[table]["statisticsSupported"]
                and all_tables[table]["statisticsType"] is not None
            ):
                results.append({"tableName": table, "status": "skipped"})
                return

            # Send refresh request
            response = await self.session.post(
                url=f"{self._base_url}/dwaas-core/statistics/"
                f"{space}/remoteTables/{table}/refresh"
            )
            if response.status_code == 202:
                logger.info("Refreshed statistics for table '%s'.", table)
                results.append({"tableName": table, "status": "refreshed"})
            else:
                logger.error(
                    "Error refreshing statistics for table '%s'. "
                    "Status code: %s",
                    table,
                    response.status_code,
                )
                logger.debug("Response: %s\n", response.text)
                results.append({"tableName": table, "status": "failed"})

        # Iterate over all table names and refresh statistics
        await self._client.run_async_tasks(
            all_tables, refresh_statistics_for_table, thread_count
        )
        return results
