from datasphere_core import COMMANDS, CommandContext


async def dispatch_command[RequestT, ResultT](
    command: str,
    context: CommandContext,
    request: RequestT,
    request_type: type[RequestT],
    result_type: type[ResultT],
) -> ResultT:
    """Dispatch a registered command after validating its types.

    Args:
        command (str): Registered Core command name.
        context (CommandContext): Core context passed to the command handler.
        request (RequestT): Request object passed to the command handler.
        request_type (type[RequestT]): Expected request model type.
        result_type (type[ResultT]): Expected result model type.

    Returns:
        ResultT: Validated result returned by the command handler.
    """
    definition = COMMANDS[command]
    if definition.request_type is not request_type:
        raise TypeError(
            f"Command {command!r} expects registered request type "
            f"{definition.request_type.__name__}, not "
            f"{request_type.__name__}."
        )
    if definition.result_type is not result_type:
        raise TypeError(
            f"Command {command!r} expects registered result type "
            f"{definition.result_type.__name__}, not "
            f"{result_type.__name__}."
        )
    if not isinstance(request, request_type):
        raise TypeError(
            f"Command {command!r} requires a {request_type.__name__} "
            f"request, got {type(request).__name__}."
        )

    result = await definition.handler(context, request)
    if not isinstance(result, result_type):
        raise TypeError(
            f"Command {command!r} returned {type(result).__name__}; "
            f"expected {result_type.__name__}."
        )
    return result
