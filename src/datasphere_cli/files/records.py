from typing import Literal, TypedDict


class AnalyticalModelTaskRecord(TypedDict):
    analytical_model: str
    space: str


class TaskChainTaskRecord(TypedDict):
    task_chain: str
    space: str


class ViewTaskRecord(TypedDict):
    view: str
    space: str


class ViewPartitioningTaskRecord(ViewTaskRecord):
    attribute: str


class TaskChainResultRecord(TypedDict):
    task_chain: str
    space: str
    status: str
    sap_status: str | None
    log_id: str | None
    runtime_seconds: int | None


class ViewPersistenceResultRecord(TypedDict):
    view: str
    space: str
    status: str
    sap_status: str | None
    log_id: str | None
    runtime_seconds: int | None


class ViewStatusResultRecord(TypedDict):
    view: str
    space: str
    status: str


class ViewPartitioningResultRecord(TypedDict):
    view: str
    space: str
    attribute: str
    status: str


class ViewAttributeResultRecord(TypedDict):
    view: str
    space: str
    business_name: str
    attribute: str
    status: str


class ViewPersistenceCandidateResultRecord(TypedDict):
    source_view: str
    source_space: str
    view: str | None
    space: str | None
    business_name: str | None
    score: int | float | None
    is_persisted: bool | None
    status: str
    log_id: str | None


class BatchSummaryRecord(TypedDict):
    total: int
    succeeded: int
    failed: int
    skipped: int
    timed_out: int


class AnalyticalModelDependencyRecord(TypedDict):
    view_id: str
    view: str
    space: str | None
    status: str


class AnalyticalModelDependenciesResultRecord(TypedDict):
    analytical_model: str
    space: str
    status: str
    analytical_model_id: str | None
    dependencies: list[AnalyticalModelDependencyRecord]


class AnalyticalModelDependenciesBatchRecord(TypedDict):
    results: list[AnalyticalModelDependenciesResultRecord]
    summary: BatchSummaryRecord


class AnalyticalModelPersistenceItemRecord(TypedDict):
    view_id: str
    view: str
    space: str | None
    status: str
    previously_persisted: bool | None
    runtime_seconds: int | None
    persistence_sap_status: str | None
    persistence_log_id: str | None
    cleanup_sap_status: str | None
    cleanup_log_id: str | None
    persistence_removed: bool | None
    manual_intervention: bool


class AnalyticalModelPersistenceResultRecord(TypedDict):
    analytical_model: str
    space: str
    status: str
    analytical_model_id: str | None
    dependencies: list[AnalyticalModelPersistenceItemRecord]


class AnalyticalModelPersistenceBatchRecord(TypedDict):
    results: list[AnalyticalModelPersistenceResultRecord]
    summary: BatchSummaryRecord


type StatisticsType = Literal["RECORD_COUNT", "SIMPLE", "HISTOGRAM"]
