import logging
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import Any, Literal, cast

from pydantic import ValidationError
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Input,
    OptionList,
    RichLog,
    Static,
    TextArea,
)
from textual.widgets.option_list import Option

try:
    _APP_VERSION = f"Version {pkg_version('Datasphere-CLI')}"
except PackageNotFoundError:
    _APP_VERSION = "dev"

from datasphere_core import CommandContext, DatasphereSession
from datasphere_core.models.common import CommandProgress, CommandProgressPhase
from datasphere_core.models.remote_tables import StatisticsType

from datasphere_cli import actions
from datasphere_cli.cli.logo import ASCII_LOGO
from datasphere_cli.logging import (
    LIBRARY_LOGGER_NAME,
    STREAM_FORMAT,
    logger,
)
from datasphere_cli.settings import (
    SETTINGS_FILE,
    build_session_config,
    reload_settings,
)
from datasphere_cli.utils.tokens import TokenStore

# Mapping of all menu categories, sub-categories and its options
type Action = Callable[..., Awaitable[object]]
type MenuOption = dict[str, Action]
type SubCategory = dict[str, MenuOption]

type ParameterType = Literal["str", "optional_str", "int", "bool", "choice"]


@dataclass(frozen=True, slots=True)
class ParameterDefinition:
    """
    Definition of one Textual parameter prompt.
    """
    name: str
    label: str
    type: ParameterType
    choices: tuple[str, ...] = ()
    default: object = None


MENU_OPTIONS: dict[str, MenuOption | SubCategory] = {
    "Analytical Models": {
        "Export model view dependencies": (
            actions.export_analytical_model_view_dependencies
        ),
        "Measure model view persistence from file": (
            actions.measure_analytical_model_view_persistence_from_file
        ),
    },
    "Remote Tables": {
        "Configure statistics for all tables": (
            actions.configure_remote_table_statistics
        ),
        "Refresh statistics for all tables": (
            actions.refresh_remote_table_statistics
        ),
    },
    "Task Chains": {
        "Run task chains from file": actions.run_task_chains_from_file,
    },
    "Views": {
        "Analytics": {
            "Export persistence candidates": (
                actions.export_view_persistence_candidates
            ),
            "Export matching attributes": (
                actions.export_view_attribute_matches
            ),
        },
        "Partitions": {
            "Create partitions from file": (
                actions.create_view_partitioning_from_file
            ),
            "Delete partitions from file": (
                actions.delete_view_partitioning_from_file
            ),
            "Lock partitions from file": (
                actions.lock_view_partitions_from_file
            ),
            "Unlock partitions from file": (
                actions.unlock_view_partitions_from_file
            ),
        },
        "Persistence": {
            "Persist views from file": actions.persist_views_from_file,
            "Unpersist views from file": actions.unpersist_views_from_file,
        },
    },
}

DEFAULT_MAX_CONCURRENCY = 4

# Method-specific parameter definitions
PARAM_DEFINITIONS: dict[Action, list[ParameterDefinition]] = {
    actions.export_analytical_model_view_dependencies: [
        ParameterDefinition(
            "space",
            "Space (leave empty for all spaces):",
            "optional_str",
        ),
        ParameterDefinition(
            "deduplicate_views",
            "Deduplicate views?",
            "bool",
            default=False,
        ),
    ],
    actions.configure_remote_table_statistics: [
        ParameterDefinition("space", "Space:", "str"),
        ParameterDefinition(
            "statistics_type",
            "Statistics type",
            "choice",
            choices=tuple(StatisticsType),
            default=StatisticsType.HISTOGRAM,
        ),
    ],
    actions.refresh_remote_table_statistics: [
        ParameterDefinition("space", "Space:", "str"),
    ],
    actions.export_view_persistence_candidates: [
        ParameterDefinition(
            "minimum_candidate_score",
            "Minimum persistence score (10 is the highest):",
            "int",
            default=10,
        ),
    ],
    actions.export_view_attribute_matches: [
        ParameterDefinition(
            "attribute_substring",
            "Attribute substring:",
            "str",
        ),
    ],
    actions.create_view_partitioning_from_file: [
        ParameterDefinition("start_year", "Start year:", "int"),
        ParameterDefinition("end_year", "End year:", "int"),
        ParameterDefinition(
            "overwrite_existing",
            "Overwrite existing partitions?",
            "bool",
            default=False,
        ),
    ],
    actions.lock_view_partitions_from_file: [
        ParameterDefinition(
            "until_year",
            "Year (locked up to and including):",
            "int",
        ),
    ],
}


class LogHandler(logging.Handler):
    """
    Custom logging handler that writes log messages to a Textual RichLog
    widget. Temporarily added to the logger before method execution and removed
    afterwards.
    """

    def __init__(self, log_widget: RichLog) -> None:
        """
        Initializes the handler with the widget to write to.

        Args:
            log_widget (RichLog): Widget receiving the log messages.
        """
        super().__init__()
        self._log = log_widget

    def emit(self, record: logging.LogRecord) -> None:
        """
        Writes one formatted log record to the widget.

        Args:
            record (logging.LogRecord): Log record to write.
        """
        self._log.write(self.format(record))


class BaseScreen(Screen):
    """
    BaseScreen class to inherit from. Creates the global header and footer for
    the CLI.

    Provides the method 'compose_content' which needs to be overridden by any
    inheriting classes.
    """

    def compose(self) -> ComposeResult:
        """
        Builds the screen from the shared header, the screen content,
        and the footer.

        Yields:
            ComposeResult: Widgets of the whole screen.
        """
        yield Container(
            Static(ASCII_LOGO, id="header-logo"),
            Static(
                Text.from_markup(
                    "[dim]by [link=https://github.com/peterschwps]"
                    "@peterschwps[/link][/dim]"
                ),
                id="header-byline",
            ),
            id="header",
        )
        yield from self.compose_content()
        yield from self.compose_footer()

    def compose_footer(self) -> ComposeResult:
        """
        Builds the default footer with the global shortcuts.

        Yields:
            ComposeResult: Footer of the screen.
        """
        yield Horizontal(
            Static("[b]Quit[/b] - Ctrl+C", id="footer-left"),
            Static("[b]Settings[/b] - Ctrl+S", id="footer-center"),
            Static(_APP_VERSION, id="footer-right"),
            id="footer",
        )

    @abstractmethod
    def compose_content(self) -> ComposeResult:
        """
        Builds the content between header and footer. Every screen has
        to implement this.

        Raises:
            NotImplementedError: If a screen does not implement it.

        Yields:
            ComposeResult: Content widgets of the screen.
        """
        raise NotImplementedError


class EntryScreen(BaseScreen):
    """
    Screen with the main menu. Shown after starting the CLI.
    """

    def __init__(self) -> None:
        """
        Initializes the main menu with every option collapsed.
        """
        super().__init__()

        # Holds all currently expanded menu options
        self._expanded: set[str] = set()

    def compose_content(self) -> ComposeResult:
        """
        Builds the main menu container.

        Yields:
            ComposeResult: Interactive menu widget.
        """
        yield Container(
            Static("\nSelect an option:"),
            OptionList(id="menu"),
            id="content",
        )

    def on_mount(self) -> None:
        """
        Handles the mount event and builds the menu.
        """
        self._rebuild_menu()

    def _rebuild_menu(self, restore_id: str | None = None) -> None:
        """
        Rebuilds the interactive menu from the expansion state.

        Args:
            restore_id (str | None, optional): ID of the cursor's position. If
                                               None the cursor will be set to
                                               the first menu entry.
                                               Defaults to None.
        """
        # Fetch menu from DOM (only OptionList)
        menu = self.query_one(OptionList)

        # Clear menu and rebuild it
        menu.clear_options()
        for category, content in MENU_OPTIONS.items():
            # Display category
            is_expanded = category in self._expanded
            prefix = "▼ " if is_expanded else "▶ "
            menu.add_option(
                Option(
                    prompt=f"{prefix}{category}",
                    id=f"cat:{category}",
                )
            )

            # Show contents if expanded
            if is_expanded:
                for key, value in content.items():
                    # Show sub-categories (only for "Views")
                    if isinstance(value, dict):
                        is_sub = f"{category}::{key}" in self._expanded
                        subprefix = "  ▼ " if is_sub else "  ▶ "
                        menu.add_option(
                            Option(
                                prompt=f"{subprefix}{key}",
                                id=f"subcat:{category}::{key}",
                            )
                        )

                        # Show options if sub-category expanded
                        if is_sub:
                            for action in value:
                                menu.add_option(
                                    Option(
                                        prompt=f"      {action}",
                                        id=f"act:{category}::{key}::{action}",
                                    )
                                )

                    # Show options
                    else:
                        menu.add_option(
                            Option(
                                prompt=f"    {key}",
                                id=f"act:{category}::{key}",
                            )
                        )

        # Set cursor back to previous position
        # Textual offers no public lookup from option ID to index
        if restore_id:
            for i, opt in enumerate(menu._options):
                if opt.id == restore_id:
                    menu.highlighted = i
                    break
        else:
            # Set first menu entry to be highlighted
            # Otherwise the user would have to press an arrow key before any
            # menu option appears highlighted
            menu.highlighted = 0

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        """
        Handles a menu selection: expands a category or starts an action.

        Args:
            event (OptionList.OptionSelected): Selection event to handle.
        """
        # Get ID of current cursor position
        option_id = str(event.option.id)

        # Categories
        if option_id.startswith("cat:"):
            category = option_id[4:]
            if category in self._expanded:
                self._expanded = {
                    e
                    for e in self._expanded
                    if not e.startswith(f"{category}::")
                }
                self._expanded.discard(category)
            else:
                self._expanded.add(category)
            self._rebuild_menu(restore_id=option_id)

        # Subcategories (only for "Views")
        elif option_id.startswith("subcat:"):
            path = option_id[7:]
            if path in self._expanded:
                self._expanded.discard(path)
            else:
                self._expanded.add(path)
            self._rebuild_menu(restore_id=option_id)

        # Options (that execute a method)
        elif option_id.startswith("act:"):
            parts = option_id[4:].split("::")
            if len(parts) == 2:
                category, action = parts
                method = cast(Action, MENU_OPTIONS[category][action])
            elif len(parts) == 3:
                category, subcat, action = parts
                subcontent = cast(SubCategory, MENU_OPTIONS[category])
                method = subcontent[subcat][action]
            else:
                return
            self.app.push_screen(ParamScreen(method))


class ParamScreen(BaseScreen):
    """
    Screen to collect parameters for the selected action before execution.
    Shows one question at a time (wizard-style).
    """

    def __init__(self, action: Action) -> None:
        """
        Initializes the wizard for the selected action.

        Args:
            action (Action): Action whose parameters are collected.
        """
        super().__init__()
        self._action = action
        self._step: int = 0
        self._answers: dict[str, Any] = {}

        # Build the prompts and always ask for bounded concurrency last.
        self._steps: list[ParameterDefinition] = list(
            PARAM_DEFINITIONS.get(action, [])
        )
        self._steps.append(
            ParameterDefinition(
                "max_concurrency",
                "Maximum concurrency:",
                "int",
                default=DEFAULT_MAX_CONCURRENCY,
            )
        )

    def compose_content(self) -> ComposeResult:
        """
        Builds the empty wizard layout. Content is filled in on_mount.

        Yields:
            ComposeResult: Container with step counter, label, widget area,
                           error and hint.
        """
        yield Container(
            Static("", id="step-counter"),
            Static("", id="param-label"),
            Container(id="param-widget-area"),
            Static("", id="param-error"),
            Static("", id="param-hint"),
            id="content",
        )

    async def on_mount(self) -> None:
        """
        Handles the mount event and shows the first step.
        """
        await self._show_step()

    def _build_widget(
        self,
        step: ParameterDefinition,
    ) -> Input | OptionList:
        """
        Builds the input widget for the current step, pre-filled with any
        previously entered answer or the parameter default.

        Args:
            step (ParameterDefinition): Parameter the widget asks for.

        Returns:
            Input | OptionList: Widget matching the parameter type.
        """
        name = step.name
        param_type = step.type
        value = self._answers.get(name, step.default)

        # Input prompt for strings and whole numbers
        if param_type in ("str", "optional_str", "int"):

            # Start empty when there is neither an answer nor a default
            return Input(
                value="" if value is None else str(value),
                id="current-widget",
            )

        # Option lists for bools
        elif param_type == "bool":
            return OptionList(
                Option("Yes", id="opt-yes"),
                Option("No", id="opt-no"),
                id="current-widget",
            )

        # Option list for type "choice"
        return OptionList(
            *[Option(c, id=f"opt-{i}") for i, c in enumerate(step.choices)],
            id="current-widget",
        )

    async def _show_step(self) -> None:
        """
        Renders the current step: update labels, replace the input
        widget, and set focus.
        """
        step = self._steps[self._step]
        is_last = self._step == len(self._steps) - 1

        # Update step counter and label
        self.query_one("#step-counter", Static).update(
            f"Step {self._step + 1} of {len(self._steps)}"
        )
        self.query_one("#param-label", Static).update(f"\n{step.label}\n")

        # Reset any error messages
        self.query_one("#param-error", Static).update("")

        # Display hint
        hint = "Enter to start" if is_last else "Enter to confirm"
        self.query_one("#param-hint", Static).update(
            f"{hint} · Escape to go back"
        )

        # Remove old input widget
        area = self.query_one("#param-widget-area")
        await area.query("*").remove()

        # Add new input widget
        widget = self._build_widget(step)
        await area.mount(widget)
        step = self._steps[self._step]

        # Format text fields (disables text being highlighted and sets the
        # cursor position behind the last character of the default value)
        if isinstance(widget, Input):
            widget.select_on_focus = False
            widget.cursor_position = len(widget.value)

        # Handle option lists and restore previous selection if one was made
        # already, else set to default
        elif isinstance(widget, OptionList):
            ptype = step.type
            if ptype == "bool":
                val = self._answers.get(
                    step.name,
                    step.default if step.default is not None else True,
                )
                widget.highlighted = 0 if bool(val) else 1
            elif ptype == "choice":
                current = self._answers.get(step.name, step.default)
                choices = step.choices
                widget.highlighted = (
                    choices.index(current) if current in choices else 0
                )

        # Focus widget to retrieve input from user
        widget.focus()

    def _validate_current(self) -> Any | None:
        """
        Reads and validates the current widget value.

        Returns:
            Any | None: Validated value, or None if the input was
                        rejected or an optional field was left empty.
        """
        step = self._steps[self._step]
        param_type = step.type

        # Clear error message
        error = self.query_one("#param-error", Static)
        error.update("")

        # Check for errors
        if param_type in ("str", "optional_str", "int"):
            raw = self.query_one("#current-widget", Input).value.strip()
            if param_type in ("str", "optional_str"):
                if param_type == "optional_str" and not raw:
                    return None
                if not raw:
                    error.update("This field must not be empty.")
                    return None
                return raw
            try:
                return int(raw)
            except ValueError:
                error.update("Please enter a whole number.")
                return None

        # Get selection of bool
        ol = self.query_one("#current-widget", OptionList)
        if param_type == "bool":
            return ol.highlighted == 0

        # Get selection of "choice" type
        idx = ol.highlighted
        if idx is None:
            error.update("Please select an option.")
            return None
        return step.choices[idx]

    async def _handle_confirm(self) -> None:
        """
        Validates the current step, stores the answer and advances to the next
        step or pushes ExecutionScreen on the final step.
        """
        # Stay on the step while the input is rejected
        # None also marks an optional string left empty on purpose
        step = self._steps[self._step]
        value = self._validate_current()
        if value is None and step.type != "optional_str":
            return

        # Get current step and add answer
        self._answers[step.name] = value

        # On final step: Convert all answers to pass it as args to the method
        if self._step == len(self._steps) - 1:
            params = dict(self._answers)

            # Start ExecutionScreen to execute method
            self.app.push_screen(ExecutionScreen(self._action, params))

        # On any other steps: increase step count and display next step
        else:
            self._step += 1
            await self._show_step()

    async def _handle_back(self) -> None:
        """
        Returns to the previous step, or leaves the wizard on the first
        step.
        """
        if self._step == 0:
            self.app.pop_screen()
        else:
            self._step -= 1
            await self._show_step()

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        """
        Handles Enter inside an Input widget and confirms the step.

        Args:
            _event (Input.Submitted): Unused submit event.
        """
        await self._handle_confirm()

    async def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """
        Handles a selection in an OptionList and confirms the step.
        OptionList consumes the Enter key itself, so the confirmation
        happens here instead of in on_key.

        Args:
            event (OptionList.OptionSelected): Selection event to handle.
        """
        if event.option_list.id == "current-widget":
            await self._handle_confirm()

    async def on_key(self, event: events.Key) -> None:
        """
        Handles Escape and steps back through the wizard.

        Args:
            event (events.Key): Key event to handle.
        """
        if event.key == "escape":
            await self._handle_back()


def progress_line(update: CommandProgress) -> str:
    """
    Builds the status line of a running batch.

    Args:
        update (CommandProgress): Progress update carrying the counters.

    Returns:
        str: Completed items and the outcomes counted so far.
    """
    total = "?" if update.total_items is None else str(update.total_items)
    counts = {
        "succeeded": update.succeeded_items,
        "failed": update.failed_items,
        "skipped": update.skipped_items,
        "timed out": update.timed_out_items,
    }

    # Outcomes that never occurred would only pad the line
    outcomes = ", ".join(
        f"{count} {name}" for name, count in counts.items() if count
    )
    completed = f"{update.completed_items}/{total}"
    return f"{completed} · {outcomes}" if outcomes else completed


def progress_status(update: CommandProgress) -> str | None:
    """
    Builds the status line for one progress update.

    Args:
        update (CommandProgress): Progress update to show.

    Returns:
        str | None: Line to show, or None if the update carries nothing the
                    status line does not say already.
    """
    # Only completed items carry a count, so a batch reports its start
    # without one. Skipping it would leave the screen unchanged until the
    # first item is done, which can take minutes.
    if update.completed_items is None:
        if update.phase is CommandProgressPhase.STARTED:
            return f"Running {update.command}..."
        return None
    return progress_line(update)


class ExecutionScreen(BaseScreen):
    """
    Screen that executes the selected action and shows live log output.
    """

    def __init__(
        self,
        action: Action,
        params: dict[str, Any],
    ) -> None:
        """
        Initializes the screen with the action to execute.

        Args:
            action (Action): Action to execute.
            params (dict[str, Any]): Collected parameters of the
                                     action.
        """
        super().__init__()
        self._action = action
        self._params = params
        self._done = False

    def compose_content(self) -> ComposeResult:
        """
        Builds the live log output and status of the running action.

        Yields:
            ComposeResult: Log widget and status indicator.
        """
        yield Container(
            RichLog(id="log", wrap=True, markup=True),
            Static("Running...", id="result-status"),
            id="content",
        )

    def on_mount(self) -> None:
        """
        Handles the mount event and starts the action worker.
        """
        self.run_worker(self._run_action(), exclusive=True)

    async def _run_action(self) -> None:
        """
        Creates the Datasphere client, logs in and executes the selected
        action. Captures log output to the RichLog widget.
        """
        log_widget = self.query_one("#log", RichLog)
        status = self.query_one("#result-status", Static)

        # Configure LogHandler for RichLog widget (also captures the
        # datasphere-core library logs)
        handler = LogHandler(log_widget)
        handler.setFormatter(STREAM_FORMAT)
        library_logger = logging.getLogger(LIBRARY_LOGGER_NAME)
        logger.addHandler(handler)
        library_logger.addHandler(handler)

        # Create session, log in and call the action
        session: DatasphereSession | None = None
        try:
            config = build_session_config()
            session = DatasphereSession(config)
            await session.authenticate(
                interactive=True,
            )

            async def report_progress(update: CommandProgress) -> None:
                """
                Updates the status line with the progress of a batch.

                Args:
                    update (CommandProgress): Progress update to show.
                """
                line = progress_status(update)
                if line is not None:
                    status.update(line)

            context = CommandContext(
                session=session.client,
                progress_callback=report_progress,
            )
            await self._action(context, **self._params)
            status.update("Done. Press Enter or Escape to return to the menu.")

        # Stop on any unhandled exceptions
        except Exception as e:
            status.update(
                f"[b][#AA0808]Error: {e}[/]\nPress Enter or Escape to return."
            )

        # Remove handler to prevent multiple handlers co-existing if this
        # screen gets called more than once
        finally:
            if session is not None:
                await session.aclose()
            logger.removeHandler(handler)
            library_logger.removeHandler(handler)
            self._done = True

    def on_key(self, event: events.Key) -> None:
        """
        Handles key presses and returns to the EntryScreen once done.

        Args:
            event (events.Key): Key event to handle.
        """
        # Pop ExecutionScreen and ParamScreen to return to EntryScreen
        if self._done and event.key in ("enter", "escape"):
            self.app.pop_screen()
            self.app.pop_screen()


class SettingsScreen(BaseScreen):
    """
    Screen to view and edit the settings.toml file.
    Ctrl+S saves and reloads settings. Escape closes without saving.
    """
    BINDINGS = [Binding("ctrl+s", "save", "Save", show=False)]

    def compose_content(self) -> ComposeResult:
        """
        Builds the settings editor.

        Yields:
            ComposeResult: Content widgets of the settings screen.
        """
        yield Container(
            Static("Edit the settings:", id="settings-label"),
            TextArea(id="settings-editor"),
            Static("", id="settings-status"),
            id="content",
        )

    def compose_footer(self) -> ComposeResult:
        """
        Builds a custom footer with the settings shortcuts.

        Yields:
            ComposeResult: Footer with special shortcuts.
        """
        yield Horizontal(
            Static("[b]Quit[/b] - Ctrl+C", id="footer-left"),
            Static("[b]Save[/b] - Ctrl+S", id="footer-center-left"),
            Static("[b]Close[/b] - Esc", id="footer-center-right"),
            Static(_APP_VERSION, id="footer-right"),
            id="footer",
        )

    def on_mount(self) -> None:
        """
        Handles the mount event and loads the settings file.
        """
        content = SETTINGS_FILE.read_text(encoding="utf-8")
        self.query_one("#settings-editor", TextArea).load_text(content)

    def action_save(self) -> None:
        """
        Saves the edited settings and reloads them.
        """
        text = self.query_one("#settings-editor", TextArea).text
        SETTINGS_FILE.write_text(text, encoding="utf-8")
        status = self.query_one("#settings-status", Static)
        try:
            reload_settings()
            status.update("[green]Saved.[/green]")
        except ValidationError as error:
            status.update(
                f"[red]Saved, but invalid: "
                f"{error.error_count()} error(s).[/red]"
            )

    async def on_key(self, event: events.Key) -> None:
        """
        Closes the settings screen when escape is pressed.

        Args:
            event (events.Key): Key event to handle.
        """
        if event.key == "escape":
            self.app.pop_screen()


class DatasphereApp(App):
    """
    Global app configuration for the CLI. Calls the EntryScreen.
    """
    CSS_PATH = "style.tcss"
    MIN_WIDTH = 112
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+s", "open_settings", "Settings", show=False),
    ]

    # Override unused bindings of the Textual defaults
    def action_copy_text(self) -> None:
        """
        Ignores the default copy binding.
        """

    def action_focus_next(self) -> None:
        """
        Ignores the default focus-next binding.
        """

    def action_focus_previous(self) -> None:
        """
        Ignores the default focus-previous binding.
        """

    def action_open_settings(self) -> None:
        """
        Opens the settings screen.
        """
        self.push_screen(SettingsScreen())

    def on_mount(self) -> None:
        """
        Shows the main menu after the app started.
        """
        self.push_screen(EntryScreen())
