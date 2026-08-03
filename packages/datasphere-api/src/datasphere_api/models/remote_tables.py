from datetime import datetime
from typing import Literal, TypedDict

StatisticsType = Literal["RECORD_COUNT", "SIMPLE", "HISTOGRAM"]

# What a write against the statistics endpoint achieved
StatisticsWriteOutcome = Literal["accepted", "already_exists", "failed"]


class StatisticsInformationDict(TypedDict):
    statisticsSupported: bool
    statisticsLimitedToRecordCount: bool
    statisticsType: StatisticsType | None
    businessName: str
    statisticsLatestUpdate: datetime | None


StatisticsDict = dict[str, StatisticsInformationDict]
