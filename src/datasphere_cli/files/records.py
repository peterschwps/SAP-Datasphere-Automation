from typing import TypedDict


class AnalyticalModelTaskRecord(TypedDict):
    """
    One row of the analytical model task file.
    """
    analytical_model: str
    space: str


class TaskChainTaskRecord(TypedDict):
    """
    One row of the task chain task file.
    """
    task_chain: str
    space: str


class ViewTaskRecord(TypedDict):
    """
    One row of a view task file.
    """
    view: str
    space: str


class ViewPartitioningTaskRecord(ViewTaskRecord):
    """
    One row of the view partitioning task file.
    """
    attribute: str


class TaskChainResultRecord(TypedDict):
    """
    One row of the task chain result file.
    """
    task_chain: str
    space: str
    status: str
    log_status: str | None
    log_id: str | None
    runtime_seconds: int | None


class ViewPersistenceResultRecord(TypedDict):
    """
    One row of a view persistence result file.
    """
    view: str
    space: str
    status: str
    log_status: str | None
    log_id: str | None
    runtime_seconds: int | None


class ViewStatusResultRecord(TypedDict):
    """
    One row of a view result file that only carries a status.
    """
    view: str
    space: str
    status: str


class ViewPartitioningResultRecord(TypedDict):
    """
    One row of the view partitioning result file.
    """
    view: str
    space: str
    attribute: str
    status: str


class ViewAttributeResultRecord(TypedDict):
    """
    One row of the view attribute result file.
    """
    view: str
    space: str
    business_name: str
    attribute: str
    status: str


class ViewPersistenceCandidateResultRecord(TypedDict):
    """
    One row of the persistence candidate result file. A source view without
    candidates is written as a row with empty candidate fields.
    """
    source_view: str
    source_space: str
    view: str | None
    space: str | None
    business_name: str | None
    score: int | float | None
    is_persisted: bool | None
    status: str
    log_id: str | None


class RemoteTableStatisticsResultRecord(TypedDict):
    """
    One row of the remote table statistics configuration result file.
    """
    table: str
    space: str
    statistics_type: str
    status: str


class RemoteTableRefreshResultRecord(TypedDict):
    """
    One row of the remote table statistics refresh result file.
    """
    table: str
    space: str
    status: str


class BatchSummaryRecord(TypedDict):
    """
    Outcome counts of a batch in a JSON result file.
    """
    total: int
    succeeded: int
    failed: int
    skipped: int
    timed_out: int


class AnalyticalModelDependencyRecord(TypedDict):
    """
    One resolved view dependency in a JSON result file.
    """
    view_id: str
    view: str
    space: str | None
    status: str


class AnalyticalModelDependenciesResultRecord(TypedDict):
    """
    Dependencies of one analytical model in a JSON result file.
    """
    analytical_model: str
    space: str
    status: str
    analytical_model_id: str | None
    dependencies: list[AnalyticalModelDependencyRecord]


class AnalyticalModelDependenciesBatchRecord(TypedDict):
    """
    Full content of the analytical model dependencies result file.
    """
    results: list[AnalyticalModelDependenciesResultRecord]
    summary: BatchSummaryRecord


class AnalyticalModelPersistenceItemRecord(TypedDict):
    """
    Persistence measurement of one view in a JSON result file.
    """
    view_id: str
    view: str
    space: str | None
    status: str
    previously_persisted: bool | None
    runtime_seconds: int | None
    persistence_log_status: str | None
    persistence_log_id: str | None
    cleanup_log_status: str | None
    cleanup_log_id: str | None
    persistence_removed: bool | None
    manual_intervention: bool


class AnalyticalModelPersistenceResultRecord(TypedDict):
    """
    Persistence measurements of one analytical model in a JSON result file.
    """
    analytical_model: str
    space: str
    status: str
    analytical_model_id: str | None
    dependencies: list[AnalyticalModelPersistenceItemRecord]


class AnalyticalModelPersistenceBatchRecord(TypedDict):
    """
    Full content of the analytical model persistence result file.
    """
    results: list[AnalyticalModelPersistenceResultRecord]
    summary: BatchSummaryRecord
