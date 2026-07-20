# SAP Datasphere CLI

[![PyPI](https://img.shields.io/pypi/v/Datasphere-CLI?label=PyPI)](https://pypi.org/project/Datasphere-CLI/)
[![Python](https://img.shields.io/pypi/pyversions/Datasphere-CLI?label=Python)](https://pypi.org/project/Datasphere-CLI/)
[![CI](https://github.com/peterschwps/SAP-Datasphere-CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/peterschwps/SAP-Datasphere-CLI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.txt)

**Retro-styled CLI for SAP Datasphere** that automates various tasks such as managing
analytical models, remote tables, task chains and views.

![Preview of the CLI](./src/datasphere_cli/static/cli.png)

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

This program enables the automation of recurring tasks in SAP Datasphere. It
provides scripts for managing:

- Analytical Models
- Remote Tables
- Task Chains
- Views

## ✨ Features

### Analytical Models

- Export all analytical models with their views
- Export all analytical models of a specific space with their views
- Runtime analysis for persisting all views of analytical models

### Remote Tables

- Create statistics (Record Count, Simple Statistics, Histogram)
- Refresh existing statistics

### Task Chains

- Run task chains

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

- **Python**: Version 3.12 or newer
- **Package Installer**: [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/stable/)

## 📦 Installation

### Quick Start

1. Install the CLI as a tool with [uv](https://docs.astral.sh/uv/):

    ```bash
    uv tool install datasphere-cli
    ```

    **or** with [pipx](https://pipx.pypa.io/stable/):

    ```bash
    pipx install datasphere-cli
    ```

2. Run it from the terminal **using any of the following commands**:

    ```bash
    datasphere
    ```

    ```bash
    datasphere-cli
    ```

Update to the latest release with `uv tool upgrade datasphere-cli`
 / `pipx upgrade datasphere-cli`.

----

### Command Layer

The presentation-independent command layer can be installed without Textual
or Rich. It is intended for integrations such as Datasphere-MCP:

```bash
pip install datasphere-core
```

The full `datasphere-cli` package continues to include the TUI and depends on
this command layer.

### Direct Commands

Providing no arguments continues to open the TUI. Individual operations can
also be executed directly:

```bash
datasphere taskchain start TC_TEST_DEV --space DEV
datasphere taskchain start TC_TEST_DEV --space DEV --timeout 600
datasphere taskchain start TC_TEST_DEV --space DEV --output json
```

The task-chain command waits for the terminal SAP status. It exits with code
zero only when the run completes successfully. JSON output is written only to
`stdout`; errors are written to `stderr`.

----

### Install from Git (all platforms)

1. Clone the repository:

    ```bash
    git clone https://github.com/peterschwps/SAP-Datasphere-CLI.git
    cd SAP-Datasphere-CLI
    ```

2. Install with uv (recommended):

    ```bash
    uv sync --all-packages
    ```

3. Install the required browsers for Playwright:

    ```bash
    uv run playwright install
    ```

    Docs: <https://playwright.dev/docs/intro>.

### For Developers

1. Clone the repository and navigate to the project directory

2. Install dev dependencies:

    ```bash
    uv sync --all-packages --group dev
    ```

3. Install Playwright:

    ```bash
    uv run playwright install
    ```

## 🔧 Configuration

The configuration is quite similar to the
[official SAP Datasphere CLI](Configuration). In Datasphere you need to create
an [OAuth Client for Interactive Usage](https://help.sap.com/docs/SAP_DATASPHERE/c8a54ee704e94e15926551293243fd1d/3f92b46fe0314e8ba60720e409c219fc.html).
This client will be used to authenticate and execute commands on SAP
Datasphere. The full configuration of the settings file (`settings.toml`) is
described down below.

> [!IMPORTANT]
> Please set the **Redirect URI** to `http://localhost:8080` when creating the
OAuth Client. This is the default port that the CLI listens on to retrieve the
callback code.

**This is how your OAuth Client should look like:**

<img src="./src/datasphere_cli/static/setup.png" alt="example-setup" width="600"/>

### Creating settings.toml

In order to create the settings file you need to run the CLI once. This will
create a `settings.toml` in your user configuration directory:

- **macOS**: `~/Library/Application Support/Datasphere/settings.toml`
- **Linux**: `~/.config/Datasphere/settings.toml`
- **Windows**: `%LOCALAPPDATA%\Datasphere\settings.toml`

> [!NOTE]
> Version 0.4.0 replaced the previous `settings.ini` with a validated
> `settings.toml`. If you are upgrading, run the CLI once and copy your
> values into the new file.

### Configuring settings.toml

Open the `settings.toml` file and configure the following settings:

```toml
[setup]
# Your SAP Datasphere URL
# (System > Administration > Tenant Links: SAP Datasphere URL)
datasphere_url = "https://example.eu10.hcs.cloud.sap"

# The Authorization URL for OAuth Clients
# (System > Administration > App Integration: Authorization URL)
authorization_url = "https://example.authentication.eu10.hana.ondemand.com/oauth/authorize"

# The Token URL for OAuth Clients
# (System > Administration > App Integration: Token URL)
token_url = "https://example.authentication.eu10.hana.ondemand.com/oauth/token"

# Browser to use for the initial authentication: 'CHROME' or 'EDGE'
browser_to_use = "EDGE"

[credentials]
# OAuth Client ID of your Configured Client
# (System > Administration > App Integration: Configured Clients)
client_id = ""

# Secret of your Configured Client
# Must be provided here or with the environment variable 'SECRET'.
secret = ""
```

## 🚀 Usage

### Execution

Run it from the terminal **using any of the following commands**:

```bash
datasphere
```

```bash
datasphere-cli
```

### First Run / Expired Tokens

On first execution (or if your refresh token has expired), the CLI will open a
browser window. After logging in the site will automatically redirect to
`http://localhost:8080`, fetch the callback code and close the browser window.

This will create a login session which can be refreshed automatically in the
future. The session tokens are stored as `session.json` in the user data
directory of `Datasphere`, so other tools built on the
[Datasphere-API](https://github.com/peterschwps/SAP-Datasphere-API) library
can share the same session.

### Menu Navigation

The program starts with an interactive menu:

1. Select a category
2. Choose a function
3. Enter the required parameters
4. Optionally select the number of threads for parallel execution

### Directory Structure

The `datasphere/` folder will be created in the directory where you run the
program:

```
datasphere/
  tasks.csv                             # shared task list (input)
  runs/
    2026-07-12_14-30-05_persist-views/  # one folder per executed action
      results.csv                       # uniform result report
      export.json / export.csv          # extracted data (export actions only)
```

- **`tasks.csv`**: One shared task list for all task-driven actions with the
                   columns `entity`, `space` and `attribute`. The `entity`
                   column holds the view, task chain or analytical model name
                   depending on the action. `attribute` is only required for
                   creating partitions and can be left empty otherwise. The
                   file is created automatically on first use.
- **`runs/`**: Every executed action writes into its own timestamped folder —
               previous results are never overwritten.
- **`results.csv`**: Same columns for every action: `entity`, `space`,
                     `success`, `detail` and `runtime`. `detail` explains
                     skips and outcomes (e.g. `no_partitions`,
                     `missing_attribute`, `skipped_same_type`), `runtime` is
                     in seconds where measured.
- **`export.json` / `export.csv`**: Data extracted by the export actions
                                    (action-specific structure, see the
                                    function overview below).

### Threading

For time-intensive tasks, threads can be used to process multiple tasks in
"parallel" using asynchronous requests. This can significantly improve
performance but should be used with caution to avoid triggering rate limits.
A thread count of 5-10 has proven to work well.

### Stopping the Program

You can stop program execution at any time by pressing `Ctrl + C`.

## 📖 Detailed Function Overview

### 1. Analytical Models

<details>
<summary>
    <strong>
        1.1 Export All Analytical Models with their Views
    </strong>
</summary>

Creates an overview of **ALL** analytical models with their views in JSON format.

**Required task file:** None

**Parameters:**

- **Skip duplicates** (yes/no): If enabled, views that already occur in
                                multiple analytical models are only saved once
                                and not for every model.

**Output file:** `export.json` in the run folder

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
<summary>
    <strong>
        1.2 Export All Analytical Models of a Specific Space with their Views
    </strong>
</summary>

Performs the same logic as 1.1, but only processes analytical models from a
specific space.

**Required task file:** None

**Parameters:**

- **Space name**: The technical name of the space (e.g., `CENTRAL_IT`)
- **Skip duplicates** (yes/no): If enabled, views that already occur in
                                multiple analytical models are only saved once
                                and not for every model.

**Output file:** `export_<space_name>.json` in the run folder

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
<summary>
    <strong>
        1.3 Runtime Analysis for Persisting All Views of Analytical Models
    </strong>
</summary>

Checks the persistence time for all views of the analytical models listed in
the task file.

**Required task file:** `datasphere/tasks.csv` (`entity` = analytical model
name)

**Parameters:** None

**Output file:** `export.json` in the run folder

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

**Note:** A `runtime` value of `null` indicates an error occurred (or the
          program is still running if the file is opened during execution).

</details>

### 2. Remote Tables

<details>
<summary>
    <strong>
        2.1 Create Statistics (Record Count, Simple Statistics or Histogram)
    </strong>
</summary>

Creates statistics for all remote tables that do not have a statistic or those
that have a statistic of a different type. Existing tables with the same
statistics type are skipped.<br>

**Please note:**: For remote tables that already have the same statistics type,
                  you should use the refresh statistics script (2.2).

**Required task file:** None

**Parameters:**

- **Statistics type**:
  1. Record Count
  2. Simple Statistics
  3. Histogram

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
SALES_ORDERS,,True,created,
CUSTOMERS,,True,skipped_same_type,
LEGACY_TABLE,,False,skipped_unsupported,
```

**Reference:** [SAP Datasphere Documentation - Statistics for Remote Tables](https://help.sap.com/docs/SAP_DATASPHERE)

</details>

<details>
<summary><strong>2.2 Refresh Existing Statistics</strong></summary>

Updates all existing statistics for remote tables.

**Required task file:** None

**Parameters:** None

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
SALES_ORDERS,,True,refreshed,
LEGACY_TABLE,,False,skipped_no_statistics,
```

</details>

### 3. Task Chains

<details>
<summary><strong>3.1 Run Task Chains</strong></summary>

Runs all task chains in the task file and exports the results of the runs.

**Required task file:** `datasphere/tasks.csv` (`entity` = task chain name)

**Parameters:** None

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
AnalyzeSales2025,SALES_DEPARTMENT,True,,1025
```

</details>

### 4. Views

<details>
<summary>
    <strong>
        4.1 Export All Views with a Perfect Persistence Score of 10
            (Using View Analyzer)
    </strong>
</summary>

Performs view analysis on all views and saves all views with a perfect
persistence score of 10.

**Required task file:** None

**Parameters:** None

**Output file:** `export.csv` in the run folder

**Example output:**

```csv
entity,space,businessName,isPersisted
Sales2025,SALES_DEPARTMENT,Sales (2025),True
```

</details>

<details>
<summary>
    <strong>
        4.2 Export All Views That Have an Attribute That Contains a Specific
            Substring
    </strong>
</summary>

Finds all views that have an attribute containing a specific substring.

**Required task file:** None

**Parameters:**

- **Search word**: The substring to search for (e.g., `YEAR`)

**Output file:** `export.csv` in the run folder

**Example output (searching for "YEAR"):**

```csv
entity,space,businessName,attribute
Sales2025,SALES_DEPARTMENT,Sales (2025),FISCAL_YEAR
Customers,SALES_DEPARTMENT,All Customers,YEAR
```

</details>

<details>
<summary><strong>4.3 Create Partitions by Year</strong></summary>

Creates partitions for views based on a yearly interval. Only columns with full
year numbers can be used (in Datasphere: `STRING(4)`).

**Required task file:** `datasphere/tasks.csv` (`entity` = view name,
`attribute` = column to partition by)

**Parameters:**

- **Lower bound** (>=): Start year for first partition (e.g., `2000`)
- **Upper bound** (<): End year for last partition (e.g., `2040`)
- **Overwrite existing partitions** (yes/no): Whether to overwrite if
                                              partitions already exists

**Example:** For input `2000` to `2040`:

- Partition 1: `>= 2000 AND < 2001`
- Partition 2: `>= 2001 AND < 2002`
- ...
- Partition 40: `>= 2039 AND < 2040`

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
Sales2025,SALES_DEPARTMENT,True,created,
Customers,SALES_DEPARTMENT,False,missing_attribute,
```

</details>

<details>
<summary><strong>4.4 Remove Partitions</strong></summary>

Removes all existing partitions from specified views.

**Required task file:** `datasphere/tasks.csv` (`entity` = view name)

**Parameters:** None

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
Sales2025,SALES_DEPARTMENT,True,,
```

</details>

<details>
<summary><strong>4.5 Lock Partitions Up to a Specific Year</strong></summary>

Locks partitions up to and including a specific year (<= year entered).
Requires that the views already have partitions. Only partitions with yearly
values can be locked (in Datasphere `STRING(4)`).

**Required task file:** `datasphere/tasks.csv` (`entity` = view name)

**Parameters:**

- **Year**: The year up to which partitions should be locked
            (the entered year is also locked)

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
Sales2025,SALES_DEPARTMENT,True,locked,
Customers,SALES_DEPARTMENT,False,no_partitions,
```

</details>

<details>
<summary><strong>4.6 Unlock Partitions</strong></summary>

Unlocks all existing partitions for specified views.

**Required task file:** `datasphere/tasks.csv` (`entity` = view name)

**Parameters:** None

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
Sales2025,SALES_DEPARTMENT,True,unlocked,
```

</details>

<details>
<summary><strong>4.7 Persist Views</strong></summary>

Persists all views listed in the task file.

**Required task file:** `datasphere/tasks.csv` (`entity` = view name)

**Parameters:**

- **Save runtime** (yes/no): Whether to record and save the persistence runtime

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
Sales2025,SALES_DEPARTMENT,True,,37
Customers,SALES_DEPARTMENT,True,,9
```

</details>

<details>
<summary><strong>4.8 Unpersist Views</strong></summary>

Removes persistence from all views listed in the task file.

**Required task file:** `datasphere/tasks.csv` (`entity` = view name)

**Parameters:** None

**Output file:** `results.csv` in the run folder

**Example output:**

```csv
entity,space,success,detail,runtime
Sales2025,SALES_DEPARTMENT,True,,
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
    uv sync --all-packages --group dev
    ```

3. Run pre-commit checks:

    ```bash
    uv run ruff check .
    uv run pyright .
    ```

### Logging

The program uses logging. Log files are created for each day and saved in the
`.logs/` folder of the directory where you run the program.

## 📃 Notes

- **Credentials**: OAuth tokens are stored in the operating system credential
                   store, separated by tenant and OAuth client ID. The client
                   secret must be provided through `settings.toml` or the
                   `SECRET` environment variable whenever the CLI runs.
- **Session Duration**: Stored refresh tokens are used to renew the session
                        before an action starts. A browser opens only when no
                        valid stored session is available.
- **Threading**: "Parallel" execution is implemented using asynchronous
                 requests. Running tasks simoultaneously can improve
                 performance but should be used with caution to avoid
                 triggering rate limits.
- **Export/Results**: All files in `exports/` and `results/` are overwritten on
                      the next program start. You can either move or rename
                      them to prevent results being overwritten.
- **Browser**: Browser authentication uses a temporary Playwright context and
               a loopback-only OAuth callback.

## 🚨 Disclaimer

**Important Note**: This tool is designed for use with SAP Datasphere. Please
                    ensure you have the necessary permissions before executing
                    automation tasks.

**Disclaimer:** It is in no way affiliated with, authorized, maintained, or
                endorsed by SAP or any of its affiliates or subsidiaries. It is
                an independent and unofficial project. Use it at your own risk.
