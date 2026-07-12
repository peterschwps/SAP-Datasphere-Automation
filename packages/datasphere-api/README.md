# Datasphere-API

[![PyPI](https://img.shields.io/pypi/v/Datasphere-API?label=PyPI)](https://pypi.org/project/Datasphere-API/)
[![Python](https://img.shields.io/pypi/pyversions/Datasphere-API?label=Python)](https://pypi.org/project/Datasphere-API/)
[![CI](https://github.com/peterschwps/SAP-Datasphere-API/actions/workflows/ci.yml/badge.svg)](https://github.com/peterschwps/SAP-Datasphere-API/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Asynchronous client for the internal SAP Datasphere API. This library powers the
[SAP-Datasphere-CLI](https://github.com/peterschwps/SAP-Datasphere-CLI)
and can be used to build your own automations.

## Features

<detail open>
  <summary><b>Analytical Models</b></summary>
  <ul>
    <li>get all analytical models</li>
    <li>get all analytical models by space</li>
    <li>get mapping of all analytical models and their views</li>
  </ul>
</details>

<details open>
  <summary><b>Remote Tables</b></summary>
  <ul>
    <li>get all remote tables</li>
    <li>create statistics</li>
    <li>change statistics type</li>
    <li>refresh existing statistics</li>
  </ul>
</details>

<details open>
  <summary><b>Task Chains</b></summary>
  <ul>
    <li>start a task chain without awaiting its result</li>
    <li>run a task chain and await its execution result</li>
    <li>retrieve logs of running task chain</li>
  </ul>
</details>

<details open>
  <summary><b>Views</b></summary>
  <ul>
    <li>get all views</li>
    <li>get all attributes of a view</li>
    <li>get all partitions</li>
    <li>create partitions</li>
    <li>lock partitions</li>
    <li>unlock partitions</li>
    <li>delete partitions</li>
    <li>create persistence (with/without awaiting the result)</li>
    <li>remove persistence (with/without awaiting the result)</li>
    <li>get all logs of a view</li>
    <li>get logs of a persistence run</li>
    <li>analyze view using the view analyzer</li>
  </ul>
</details>

> [!TIP]
> Open an issue if you need another functionality.

## Installation

```bash
pip install datasphere-api
# or
uv add datasphere-api
```

The interactive login requires a Chrome or Edge installation.

## Quickstart

```python
import asyncio

from datasphere_api import DatasphereClient, DatasphereConfig


async def main() -> None:
    config = DatasphereConfig(
        base_url="https://example.eu10.hcs.cloud.sap",
        authorization_url=(
            "https://example.authentication.eu10.hana.ondemand.com"
            "/oauth/authorize"
        ),
        token_url=(
            "https://example.authentication.eu10.hana.ondemand.com"
            "/oauth/token"
        ),
        client_id="...",
        client_secret="...",
    )
    client = DatasphereClient(config)
    try:
        await client.login()
        success, log_details = await client.task_chains.run(
            "MY_CHAIN", "MY_SPACE"
        )
        print(success, log_details.get("runTime"))
    finally:
        await client.aclose()


asyncio.run(main())
```

The URLs and credentials can be found in your tenant under
System > Administration (Tenant Links and App Integration). The OAuth
client has to be of type "Interactive Usage" with the redirect URI
`http://localhost:8080`.

## Authentication

This client provides an interactive login. If no tokens are provided, it opens a browser window for the user to sign in. If tokens are provided, the client tries to refresh them first. After a valid session has been created it returns the tokens (from `client.login(tokens)`).

Make sure to store those tokens if you want to persist the session across multiple runs (see [SAP-Datasphere-CLI](https://github.com/peterschwps/SAP-Datasphere-CLI) for an example). The client itself does not persist any tokens!

## Layered results

This library aims to provide a thin client for the internal Datasphere API. It works on two levels:

- **Endpoint methods**: one method = one HTTP call, acting as an
  unofficial documentation of the internal Datasphere API (e.g.
  `views.get_partitioning()` or `remote_tables.create_statistics()`). They return the parsed payload or a small typed outcome.

- **Single-entity workflows**: minimal compositions of endpoint calls
  that every consumer needs identically, mostly start-and-poll flows (which can be triggered by clicking a button in Datasphere)
  like `views.persist_view()`, `views.analyze_view()` or
  `task_chains.run()`.

Both levels mirror single UI actions in SAP Datasphere, e.g. clicking a button or running a search query.

## Disclaimer

This project is not affiliated with, endorsed by, or supported by SAP. It uses the same internal HTTP endpoints as the SAP Datasphere web UI, which may change without notice.
