from utils.filehandler import file_setup
from utils.screens import DatasphereApp

# Create all files
# Must be executed first
file_setup()

# Start app
app = DatasphereApp()
app.run(mouse=False)
