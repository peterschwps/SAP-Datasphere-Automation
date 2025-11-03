import asyncio
import sys

from utils.filehandler import file_setup
from utils.logging import logger
from utils.menu import Menu

# Create all files
# Must be executed first
file_setup()

# Show menu
menu = Menu()
chosen_module, chosen_method, all_params = menu.show_menu()

# Start tasks
exit_code = 1
try:
    # Create new instance of selected class
    app = chosen_module()

    async def run_task():
        # Execute initialization method of the class
        # (creates Datasphere Session)
        await app.initialize()

        # Return unbound method (receives instance as first argument)
        return await chosen_method(app, **all_params)

    result = asyncio.run(run_task())
    exit_code = 0

except KeyboardInterrupt:
    exit_code = 130

logger.warning(
    "Please note that all files in the exports and results folder will be "
    "overwritten on the next program start."
)

logger.info("Exiting program...")
sys.exit(exit_code)
