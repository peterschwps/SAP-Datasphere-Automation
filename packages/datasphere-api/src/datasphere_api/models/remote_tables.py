from datetime import datetime
from typing import Literal, TypedDict

StatisticsType = Literal["RECORD_COUNT", "SIMPLE", "HISTOGRAM"]

# Outcomes of the single-table statistics operations
StatisticsCreateOutcome = Literal["created", "already_exists", "failed"]
StatisticsUpdateOutcome = Literal["updated", "already_exists", "failed"]


class StatisticsInformationDict(TypedDict):
    statisticsSupported: bool
    statisticsLimitedToRecordCount: bool
    statisticsType: StatisticsType | None
    businessName: str
    statisticsLatestUpdate: datetime | None


StatisticsDict = dict[str, StatisticsInformationDict]
