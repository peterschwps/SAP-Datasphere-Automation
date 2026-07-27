# ruff: noqa: F401

from datasphere_cli.actions.analytical_models import (
    export_analytical_model_view_dependencies,
    measure_analytical_model_view_persistence_from_file,
)
from datasphere_cli.actions.remote_tables import (
    configure_remote_table_statistics,
    refresh_remote_table_statistics,
)
from datasphere_cli.actions.task_chains import run_task_chains_from_file
from datasphere_cli.actions.views import (
    create_view_partitioning_from_file,
    delete_view_partitioning_from_file,
    export_view_attribute_matches,
    export_view_persistence_candidates,
    lock_view_partitions_from_file,
    persist_views_from_file,
    unlock_view_partitions_from_file,
    unpersist_views_from_file,
)
