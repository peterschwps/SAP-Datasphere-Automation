# Datasphere-Core

Shared, presentation-independent commands for SAP Datasphere automation.
Datasphere-Core powers
[Datasphere-CLI](https://github.com/peterschwps/SAP-Datasphere-CLI) and
[Datasphere-MCP](https://github.com/peterschwps/SAP-Datasphere-MCP).

## Installation

```bash
pip install datasphere-core
```

## Example

```python
import asyncio

from datasphere_core import (
    CommandContext,
    DatasphereSession,
    SessionConfig,
    StartTaskChainRequest,
    start_task_chain,
)


async def main() -> None:
    config = SessionConfig(
        base_url="https://example.eu10.hcs.cloud.sap",
        authorization_url="https://example.authentication.sap.hana.ondemand.com/oauth/authorize",
        token_url="https://example.authentication.sap.hana.ondemand.com/oauth/token",
        client_id="client-id",
        client_secret="client-secret",
    )

    async with DatasphereSession(config) as session:
        await session.authenticate(interactive=True)
        result = await start_task_chain(
            CommandContext(client=session.client),
            StartTaskChainRequest(
                chain="TC_TEST_DEV",
                space="DEV",
                timeout_seconds=600,
            ),
        )
        print(result)


asyncio.run(main())
```

> [!NOTE]
> OAuth tokens are stored in the operating system credential store. Use an
> explicit interactive login before calling `authenticate(interactive=False)`
> from non-interactive applications.
