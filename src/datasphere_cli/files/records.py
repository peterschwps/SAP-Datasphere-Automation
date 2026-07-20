from typing import TypedDict

# ===== Task file rows =====

class ViewRef(TypedDict):
    entity: str
    space: str


class PartitionTask(TypedDict):
    entity: str
    space: str
    attribute: str


class ModelRef(TypedDict):
    modelname: str
    space: str


# ===== Result file rows =====

class ViewAttributeMatch(TypedDict):
    entity: str
    space: str
    businessName: str
    attribute: str


class PersistenceCandidate(TypedDict):
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


# ===== Analytical model exports =====

class ModelWithViews(TypedDict):
    name: str
    dependencies: dict[str, str | tuple[str, str]]


type ModelsWithViews = dict[str, ModelWithViews]


class ViewRuntimeDetails(TypedDict):
    space: str
    name: str
    runtime: int | None
    alreadyPersisted: bool
    removedPersistence: bool


class ModelRuntimeReport(TypedDict):
    name: str
    dependencies: dict[str, ViewRuntimeDetails]


type ModelsRuntimeReport = dict[str, ModelRuntimeReport]
