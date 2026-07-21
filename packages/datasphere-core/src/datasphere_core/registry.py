from datasphere_core.commands.analytical_models import (
    ANALYTICAL_MODELS_COMMAND_DEFINITIONS,
)
from datasphere_core.commands.remote_tables import (
    REMOTE_TABLES_COMMAND_DEFINITIONS,
)
from datasphere_core.commands.task_chains import (
    TASK_CHAINS_COMMAND_DEFINITIONS,
)
from datasphere_core.commands.views import VIEWS_COMMAND_DEFINITIONS
from datasphere_core.definitions import build_command_registry

# Build mapping of all commands to their definitions
COMMANDS = build_command_registry(
    (
        *ANALYTICAL_MODELS_COMMAND_DEFINITIONS,
        *REMOTE_TABLES_COMMAND_DEFINITIONS,
        *TASK_CHAINS_COMMAND_DEFINITIONS,
        *VIEWS_COMMAND_DEFINITIONS,
    )
)

__all__ = ["COMMANDS"]
