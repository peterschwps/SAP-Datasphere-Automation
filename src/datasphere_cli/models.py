from typing import Literal, TypedDict

# NOTE: Some keys deliberately use camelCase because they mirror the
# CSV/JSON export formats of the task and result files.


# Task file rows

class ViewRef(TypedDict):
    """Reference to a view, task chain or other entity in a space."""
    entity: str
    space: str


class PartitionTask(TypedDict):
    """Reference to a view with the attribute to partition by."""
    entity: str
    space: str
    attribute: str


class ModelRef(TypedDict):
    """Reference to an analytical model in a space."""
    modelname: str
    space: str


# Result file rows

class ViewAttributeMatch(TypedDict):
    """View with an attribute that matched the search word."""
    entity: str
    space: str
    businessName: str
    attribute: str


class PersistenceCandidate(TypedDict):
    """View that received a persistence score of 10 from the advisor."""
    entity: str
    space: str
    businessName: str
    isPersisted: bool


class PartitionCreateResult(TypedDict):
    entity: str
    space: str
    attribute: str
    createdPartition: bool


class PartitionDeleteResult(TypedDict):
    entity: str
    space: str
    removedPartition: bool


class PartitionLockResult(TypedDict):
    entity: str
    space: str
    lockedPartitions: bool


class PartitionUnlockResult(TypedDict):
    entity: str
    space: str
    unlockedPartitions: bool


class PersistResult(TypedDict):
    entity: str
    space: str
    isPersisted: bool
    runtime: int | None


class UnpersistResult(TypedDict):
    entity: str
    space: str
    isRemoved: bool


class TaskChainRunResult(TypedDict):
    entity: str
    space: str
    isCompleted: bool
    runtime: int | None


# Statistics results (log output only, no result file)

StatisticsResultStatus = Literal[
    "created",
    "updated",
    "refreshed",
    "already_exists",
    "skipped",
    "failed",
]


class StatisticsResult(TypedDict):
    """Outcome of a statistics create/update/refresh for one table."""
    tableName: str
    status: StatisticsResultStatus


# Analytical model exports

class ModelWithViews(TypedDict):
    """Analytical model with all views it depends on. The dependencies
    map view IDs to a (space, name) tuple. Views whose space cannot be
    resolved keep their plain name."""
    name: str
    dependencies: dict[str, str | tuple[str, str]]


# Mapping of analytical model IDs to the models with their views
type ModelsWithViews = dict[str, ModelWithViews]


class ViewRuntimeDetails(TypedDict):
    """Persistence runtime details of a single view."""
    space: str
    name: str
    runtime: int | None
    alreadyPersisted: bool
    removedPersistence: bool


class ModelRuntimeReport(TypedDict):
    """Analytical model with the runtime details of all its views."""
    name: str
    dependencies: dict[str, ViewRuntimeDetails]


# Mapping of analytical model IDs to their runtime reports
type ModelsRuntimeReport = dict[str, ModelRuntimeReport]
