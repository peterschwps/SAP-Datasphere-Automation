# SAP Datasphere Automation

CLI tool for automating various tasks in SAP Datasphere, including managing analytical models, remote tables and views.

## 📋 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Detailed Function Overview](#-detailed-function-overview)
- [Development](#-development)
- [Notes](#-notes)
- [Disclaimer](#-disclaimer)

## 🎯 Overview

This program enables the automation of recurring tasks in SAP Datasphere. It provides scripts for managing:

- Analytical Models
- Remote Tables
- Views

## ✨ Features

### Analytical Models
- Export all analytical models with their views
- Export all analytical models of a specific space with their views
- Runtime analysis for persisting all views of analytical models

### Remote Tables
- Create statistics (Record Count, Simple Statistics, Histogram)
- Refresh existing statistics

### Views
- Export all views with a perfect persistence score of 10 (using view analyzer)
- Export all views that have an attribute that contains a specific substring
- Create partitions by year
- Remove partitions
- Lock partitions up to a specific year
- Unlock partitions
- Persist views
- Unpersist views

## 🔧 Prerequisites

- **Python**: Version 3.12 or 3.13 (see `pyproject.toml`)
- **uv** for package management
- **Browser** for authentication (optional, if browser method is used):
  - Chrome
  - Edge
  - Playwright

## 📦 Installation

### Option A: Windows (Release)

1. Download the latest release asset: `DatasphereAutomation-<version>-windows.exe`.
2. Run via double-click or from a terminal:
```bash
DatasphereAutomation-<version>-windows.exe
```

----

### Option B: macOS (Release, CLI)

1. Download the latest release asset: `DatasphereAutomation-<version>-macos`.
2. Remove Gatekeeper quarantine and make it executable:
```bash
xattr -d com.apple.quarantine DatasphereAutomation-<version>-macos
chmod +x DatasphereAutomation-<version>-macos
```
3. Run from the terminal:
```bash
./DatasphereAutomation-<version>-macos
```
Note: The Mac app can't be opened via double-click.

----

### Option C: Install from Git (all platforms)

1. Clone the repository:
```bash
git clone https://github.com/peterschwps/SAP-Datasphere-Automation.git
cd sap-datasphere
```

2. Install with uv (recommended):
```bash
uv sync
```

3. Optional: Install Playwright for browser-based authentication:
```bash
uv run playwright install
```
Docs: https://playwright.dev/docs/intro.

### For Developers

1. Clone the repository and navigate to the project directory
2. Install dev dependencies:
```bash
uv sync --group dev
```
3. Install Playwright:
```bash
uv run playwright install
```

## ⚙️ Configuration

On first run, a configuration file is created. This is located in your user configuration directory:

- **macOS/Linux**: `~/.config/Datasphere/settings.ini`
- **Windows**: `%APPDATA%\Datasphere\settings.ini`

### Configuring settings.ini

Open the `settings.ini` file and configure the following settings:

```ini
[URLs]
# Your SAP Datasphere URLs (e.g. Dev and Production)
DATASPHERE_TEST_URL = https://example-test.eu10.hcs.cloud.sap
DATASPHERE_PROD_URL = https://example-prod.eu10.hcs.cloud.sap
# ... you can add more variables here

[Setup]
# Which URL should be used
URL_TO_USE = DATASPHERE_PROD_URL

# Authentication method: BROWSER or REQUESTS
AUTHENTICATION_METHOD = BROWSER

# Which browser should be used (only relevant if AUTHENTICATION_METHOD = BROWSER):
# CHROME, EDGE, or PLAYWRIGHT
BROWSER_TO_USE = CHROME
```

### Authentication Methods

**BROWSER**: Opens a browser where you log in manually. Cookies are saved and reused for future sessions.

**REQUESTS**: Browserless login via Microsoft SSO. You will be prompted to enter your email address and password and receive an authenticator code for MFA confirmation.

## 🚀 Usage

### Execution
```bash
uv run python main.py
```

**Executable:**
```bash
.\DatasphereAutomation.exe
```

### First Run

On first execution (or if the cookies have expired), you will be prompted for authentication:

1. Type your email address when prompted and press Enter.
2. Type your password when prompted and press Enter (**Note**: Input is captured but not displayed!).
3. Wait for the authenticator code to be shown in the console and enter it in your Authenticator app.

### Menu Navigation

The program starts with an interactive menu:

1. Select a category (Views, Analytical Models, Remote Tables)
2. Choose a function
3. Enter the required parameters
4. Optionally select the number of threads for parallel execution

### Directory Structure

The `datasphere/` folder will be created in the directory where you run the program. It contains three important subdirectories:

- **`exports/`**: Contains all extracted data created during program execution (JSON, CSV files)
- **`results/`**: Contains an overview of executed tasks showing their status (successful / unsuccessful)
- **`tasks/`**: Contains all task files (CSV format) that specify what should be processed

**Important**: All files in `exports/` and `results/` are **reset on program start**! If you want to preserve files, rename or move them to a different location.

Tasks are **not automatically executed** - they are only being processed when you explicitly select the corresponding option in the program.

### Threading

For time-intensive tasks, threads can be used to process multiple tasks in parallel using asynchronous requests. This can significantly improve performance but should be used with caution to avoid triggering rate limits.

### Stopping the Program

You can stop program execution at any time by pressing `Ctrl + C`.

## 📖 Detailed Function Overview

### 1. Analytical Models

<details>
<summary><strong>1.1 Export All Analytical Models with their Views</strong></summary>

Creates an overview of **ALL** analytical models with their views in JSON format.

**Required task file:** None

**Parameters:**
- **Skip duplicates** (yes/no): If enabled, views that already occur in multiple analytical models are only saved once and not for every model.

**Output file:** `exports/analytical_models_with_all_views.json`

**Example output:**
```json
{
    "6BB18AB407AC02FH23804E421859F129": {
        "name": "Sales Analytical Model",
        "dependencies": {
            "606E8AB407FG02FB18004E438092F770": [
                "SALES_DEPARTMENT",
                "Sales2025"
            ],
            "606E8AB407FG02FB58929E438092F771": [
                "MASTER_DATA",
                "Customers"
            ]
        }
    }
}
```

</details>

<details>
<summary><strong>1.2 Export All Analytical Models of a Specific Space with their Views</strong></summary>

Performs the same logic as 1.1, but only processes analytical models from a specific space.

**Required task file:** None

**Parameters:**
- **Space name**: The technical name of the space (e.g., `CENTRAL_IT`)
- **Skip duplicates** (yes/no): If enabled, views that already occur in multiple analytical models are only saved once and not for every model.

**Output file:** `exports/analytical_models_with_all_views_in_<space_name>.json`

**Example output:**
```json
{
    "6BB18AB407AC02FH23804E421859F129": {
        "name": "Sales Analytical Model",
        "dependencies": {
            "606E8AB407FG02FB18004E438092F770": [
                "SALES_DEPARTMENT",
                "Sales2025"
            ],
            "606E8AB407FG02FB58929E438092F771": [
                "MASTER_DATA",
                "Customers"
            ]
        }
    }
}
```

</details>

<details>
<summary><strong>1.3 Runtime Analysis for Persisting All Views of Analytical Models</strong></summary>

Checks the persistence time for all views of the analytical models listed in the task file.

**Required task file:** `tasks/analytical_models_to_check_view_persistence_time.csv`

**Parameters:** None

**Output file:** `exports/analytical_models_with_all_views_and_persistence_time.json`

**Example output:**
```json
{
    "6BB18AB407AC02FH23804E421859F129": {
        "name": "Sales Analytical Model",
        "dependencies": {
            "606E8AB407FG02FB18004E438092F770": {
                "space": "SALES_DEPARTMENT",
                "name": "Sales2025",
                "runtime": 78,
                "alreadyPersisted": true,
                "removedPersistency": false
            },
            "606E8AB407FG02FB58929E438092F771": {
                "space": "MASTER_DATA",
                "name": "Customers",
                "runtime": 123,
                "alreadyPersisted": false,
                "removedPersistency": true
            }
        }
    }
}       
```

**Note:** A `runtime` value of `null` indicates an error occurred (or the program is still running if the file is opened during execution).

</details>

### 2. Remote Tables

<details>
<summary><strong>2.1 Create Statistics (Record Count, Simple Statistics or Histogram)</strong></summary>

Creates statistics for all remote tables that do not have a statistic or those that have a statistic of a different type. Existing tables with the same statistics type are skipped.<br>
**Please note:**: For remote tables that already have the same statistics type, you should use the refresh statistics script (2.2).

**Required task file:** None

**Parameters:**
- **Statistics type**:
  1. Record Count
  2. Simple Statistics
  3. Histogram

**Output file:** None

**Example output:** None

**Reference:** [SAP Datasphere Documentation - Statistics for Remote Tables](https://help.sap.com/docs/SAP_DATASPHERE)

</details>

<details>
<summary><strong>2.2 Refresh Existing Statistics</strong></summary>

Updates all existing statistics for remote tables.

**Required task file:** None

**Parameters:** None

**Output file:** None

**Example output:** None

</details>

### 3. Views

<details>
<summary><strong>3.1 Export All Views with a Perfect Persistence Score of 10 (Using View Analyzer)</strong></summary>

Performs view analysis on all views and saves all views with a perfect persistence score of 10.

**Required task file:** None

**Parameters:** None

**Output file:** `exports/best_views_to_persist.csv`

**Example output:**
```csv
entity,space,businessName,isPersisted
Sales2025,SALES_DEPARTMENT,Sales (2025),True 
```

</details>

<details>
<summary><strong>3.2 Export All Views That Have an Attribute That Contains a Specific Substring</strong></summary>

Finds all views that have an attribute containing a specific substring.

**Required task file:** None

**Parameters:**
- **Search word**: The substring to search for (e.g., `YEAR`)

**Output file:** `exports/view_attributes.csv`

**Example output (searching for "YEAR"):**
```csv
entity,space,businessName,attribute
Sales2025,SALES_DEPARTMENT,Sales (2025),FISCAL_YEAR
Customers,SALES_DEPARTMENT,All Customers,YEAR
```

</details>

<details>
<summary><strong>3.3 Create Partitions by Year</strong></summary>

Creates partitions for views based on a yearly interval. Only columns with full year numbers can be used (in Datasphere: `STRING(4)`).

**Required task file:** `tasks/views_to_create_partitions.csv`

**Parameters:**
- **Lower bound** (>=): Start year for first partition (e.g., `2000`)
- **Upper bound** (<): End year for last partition (e.g., `2040`)
- **Overwrite existing partitions** (yes/no): Whether to overwrite if partitions already exist

**Example:** For input `2000` to `2040`:
- Partition 1: `>= 2000 AND < 2001`
- Partition 2: `>= 2001 AND < 2002`
- ...
- Partition 40: `>= 2039 AND < 2040`

**Output file:** `results/views_partitions_created.csv`

**Example output:**
```csv
entity,space,attribute,createdPartition
Sales2025,SALES_DEPARTMENT,FISCAL_YEAR,True
Customers,SALES_DEPARTMENT,YEAR,True
```

</details>

<details>
<summary><strong>3.4 Remove Partitions</strong></summary>

Removes all existing partitions from specified views.

**Required task file:** `tasks/views_to_delete_partitions.csv`

**Parameters:** None

**Output file:** `results/views_partitions_deleted.csv`

**Example output:**
```csv
entity,space,removedPartition
Sales2025,SALES_DEPARTMENT,True
```

</details>

<details>
<summary><strong>3.5 Lock Partitions Up to a Specific Year</strong></summary>

Locks partitions up to and including a specific year (<= year entered). Requires that the views already have partitions. Only partitions with yearly values can be locked (in Datasphere `STRING(4)`).

**Required task file:** `tasks/views_to_lock_partitions.csv`

**Parameters:**
- **Year**: The year up to which partitions should be locked (the entered year is also locked)

**Output file:** `results/views_partitions_locked.csv`

**Example output:**
```csv
entity,space,lockedPartitions
Sales2025,SALES_DEPARTMENT,True
```

</details>

<details>
<summary><strong>3.6 Unlock Partitions</strong></summary>

Unlocks all existing partitions for specified views.

**Required task file:** `tasks/views_to_unlock_partitions.csv`

**Parameters:** None

**Output file:** `results/views_partitions_unlocked.csv`

**Example output:**
```csv
entity,space,unlockedPartitions
Sales2025,SALES_DEPARTMENT,True
```

</details>

<details>
<summary><strong>3.7 Persist Views</strong></summary>

Persists all views listed in the task file.

**Required task file:** `tasks/views_to_persist.csv`

**Parameters:**
- **Save runtime** (yes/no): Whether to record and save the persistence runtime

**Output file:** `results/views_persisted.csv`

**Example output:**
```csv
entity,space,isPersisted,runtime
Sales2025,SALES_DEPARTMENT,True,37
Customers,SALES_DEPARTMENT,True,9
```

</details>

<details>
<summary><strong>3.8 Unpersist Views</strong></summary>

Removes persistence from all views listed in the task file.

**Required task file:** `tasks/views_to_unpersist.csv`

**Parameters:** None

**Output file:** `results/views_unpersisted.csv`

**Example output:**
```csv
entity,space,isRemoved
Sales2025,SALES_DEPARTMENT,True
```

</details>

## 👨‍💻 Development

### Code Quality

The project uses:
- **ruff** for linting and code formatting
- **pyright** for type checking (in basic mode)

### Setting up Development Environment

1. Clone the repository
2. Install development environment:
```bash
uv sync --group dev
```

3. Run pre-commit checks:
```bash
uv run ruff check .
uv run pyright .
```

### Logging

The program uses logging. Log files are created for each day and saved in the user data directory:
- **macOS/Linux**: `~/.local/share/Datasphere/`
- **Windows**: `%LOCALAPPDATA%\Datasphere\`

## ⚠️ Notes

- **Cookies**: Authentication cookies are saved in `~/.config/Datasphere/.cookies.json` and automatically reused.
- **Session Duration**: The SAP Datasphere session expires after 1 hour and is automatically renewed using the persistent authentication cookies which last for 3 months.
- **Threading**: 'Parallel' execution is implemented using asynchronous requests. Running tasks simoultaneously can improve performance but should be used with caution to avoid triggering rate limits.
- **Export/Results**: All files in `exports/` and `results/` are overwritten on the next program start. You can either move or rename them to prevent results being overwritten.
- **Browser**: When using browser authentication, a new browser profile is being created to speed up future logins.


## 🚨 Disclaimer

**Important Note**: This tool is designed for use with SAP Datasphere. Please ensure you have the necessary permissions before executing automation tasks.<br>

**Disclaimer:** It is in no way affiliated with, authorized, maintained, or endorsed by SAP or any of its affiliates or subsidiaries. It is an independent and unofficial project. Use it at your own risk.
