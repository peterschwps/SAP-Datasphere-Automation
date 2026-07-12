from typing import NotRequired, TypedDict

# NOTE: Some keys deliberately use camelCase because they mirror the
# CSV/JSON export formats of the task and result files.


class TaskRow(TypedDict):
    """Row of the shared task file. 'entity' can be a view, task chain
    or analytical model name depending on the action. 'attribute' is
    only used by the partition creation."""
    entity: str
    space: str
    attribute: NotRequired[str]


class ResultRow(TypedDict):
    """Row of the uniform result file of a run."""
    entity: str
    space: str
    success: bool
    detail: str
    runtime: int | None


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
