from datetime import datetime
from typing import Literal, TypedDict

# NOTE: Some keys deliberately use camelCase because they mirror external
# formats (Datasphere API payloads and the CSV/JSON exports of consumers).


# Input types

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


# For RemoteTables

StatisticsType = Literal["RECORD_COUNT", "SIMPLE", "HISTOGRAM"]

StatisticsResultStatus = Literal[
    "created",
    "updated",
    "refreshed",
    "already_exists",
    "skipped",
    "failed",
]


class StatisticsInformationDict(TypedDict):
    statisticsSupported: bool
    statisticsLimitedToRecordCount: bool
    statisticsType: StatisticsType | None
    businessName: str
    statisticsLatestUpdate: datetime | None


StatisticsDict = dict[str, StatisticsInformationDict]


class StatisticsResult(TypedDict):
    """Outcome of a statistics create/update/refresh for one table."""

    tableName: str
    status: StatisticsResultStatus


# For Views

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


# For TaskChains

class TaskChainRunResult(TypedDict):
    entity: str
    space: str
    isCompleted: bool
    runtime: int | None


# For AnalyticalModels

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


# Full view details as returned by the repository search
# (as of 10.07.2025)
ViewDetailsDict = TypedDict(
    "ViewDetailsDict",
    {
        "@com.sap.vocabularies.Search.v1.Ranking": int | float,
        "@com.sap.vocabularies.Search.v1.WhyFound": dict,
        "@odata.context": str,
        "business_name": str,
        "business_purpose_purpose": None,
        "business_type": str,
        "business_type_description": str,
        "business_type_icon": str,
        "capabilities_list": None,
        "changed_by_user_name": str | None,
        "creation_date": str,
        "creator_user_name": str | None,
        "decommissioning_date": None,
        "deployment_date": str | None,
        "deployment_folder_id": None,
        "deployment_folder_id_ext": None,
        "deployment_folder_name": None,
        "deployment_name": None,
        "deployment_status": str,
        "deployment_status_description": str,
        "deployment_status_icon": str,
        "deprecation_date": None,
        "description": None,
        "exposed_for_consumption": str,
        "exposed_for_consumption_id": str,
        "favorites_user_id": None,
        "folder_icon": str | None,
        "folder_id": str | None,
        "folder_id_ext": str | None,
        "folder_name": str | None,
        "id": str,
        "is_shared": str | None,
        "is_shared_tag": str | None,
        "kind": str,
        "last_accessed": str | None,
        "last_accessed_globally": str | None,
        "modification_date": str,
        "name": str,
        "object_status": str,
        "object_status_description": str,
        "object_status_icon": str,
        "release_date": str | None,
        "release_state": str,
        "release_state_description": str,
        "release_state_icon": str,
        "remote_connection": None,
        "remote_connection_type": None,
        "remote_connection_type_description": None,
        "remote_entity": None,
        "repository_package": str | None,
        "repository_package_name": str | None,
        "space_description": str,
        "space_id": str,
        "space_name": str,
        "space_permission_user_is_member_in_source_space_id": str,
        "space_type": None,
        "technical_type": str,
        "technical_type_description": str,
        "technical_type_icon": str,
        "user_is_member_in_source_space_id": str,
        "business_purpose_description@com.sap.vocabularies.Search.v1.Snippets": str  # noqa: E501
        | None,
        "@com.sap.vocabularies.Search.v1.ParentHierarchies": list[dict],
    },
)

# Full analytical model details as returned by the repository search
# (as of 13.07.2025)
AnalyticalModelsDetailsDict = TypedDict(
    "AnalyticalModelsDetailsDict",
    {
        "@com.sap.vocabularies.Search.v1.Ranking": int | float,
        "@com.sap.vocabularies.Search.v1.WhyFound": dict,
        "@odata.context": str,
        "business_name": str,
        "business_purpose_purpose": None,
        "business_type": str,
        "business_type_description": str,
        "business_type_icon": str,
        "capabilities_list": None,
        "changed_by_user_name": str | None,
        "creation_date": str,
        "creator_user_name": str | None,
        "decommissioning_date": None,
        "deployment_date": str | None,
        "deployment_folder_id": None,
        "deployment_folder_id_ext": None,
        "deployment_folder_name": None,
        "deployment_name": None,
        "deployment_status": str,
        "deployment_status_description": str,
        "deployment_status_icon": str,
        "deprecation_date": None,
        "description": None,
        "exposed_for_consumption": str,
        "exposed_for_consumption_id": str,
        "favorites_user_id": None,
        "folder_icon": str | None,
        "folder_id": str | None,
        "folder_id_ext": str | None,
        "folder_name": str | None,
        "id": str,
        "is_shared": None,
        "is_shared_tag": None,
        "kind": str,
        "last_accessed": str | None,
        "last_accessed_globally": str | None,
        "modification_date": str,
        "name": str,
        "object_status": str,
        "object_status_description": str,
        "object_status_icon": str,
        "release_date": None,
        "release_state": None,
        "release_state_description": None,
        "release_state_icon": None,
        "remote_connection": None,
        "remote_connection_type": None,
        "remote_connection_type_description": None,
        "remote_entity": None,
        "repository_package": None,
        "repository_package_name": None,
        "space_description": str,
        "space_id": str,
        "space_name": str,
        "space_permission_user_is_member_in_source_space_id": str,
        "space_type": None,
        "technical_type": str,
        "technical_type_description": str,
        "technical_type_icon": str,
        "user_is_member_in_source_space_id": str,
        "business_purpose_entHierarchies": list[dict],
    },
)
