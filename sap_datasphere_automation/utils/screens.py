import logging
from abc import abstractmethod
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any, cast

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
    _APP_VERSION = f"Version {pkg_version('sap-datasphere-automation')}"
except PackageNotFoundError:
    _APP_VERSION = "dev"

from datasphere_api import DatasphereClient

from sap_datasphere_automation import actions
from sap_datasphere_automation.static.logo import ASCII_LOGO
from sap_datasphere_automation.utils.filehandler import (
    SETTINGS_FILE,
    build_config,
    settings,
)
from sap_datasphere_automation.utils.logging import (
    LIBRARY_LOGGER_NAME,
    STREAM_FORMAT,
    logger,
)

# Mapping of all menu categories, sub-categories and its options
type MenuOption = dict[str, Callable]
type SubCategory = dict[str, MenuOption]
MENU_OPTIONS: dict[str, MenuOption | SubCategory] = {
    "Analytical Models": {
        "Export all models with views": (
            actions.get_all_views_for_analytical_models
        ),
        "Export all models with views (by space)": (
            actions.get_all_views_for_analytical_models_in_space
        ),
        "Save runtime of all views of models": (
            actions.check_runtime_for_all_views_of_analytical_models
        ),
    },
    "Remote Tables": {
        "Create statistics for all tables": actions.create_statistics,
        "Refresh statistics for all tables": actions.refresh_statistics,
    },
    "Task Chains": {
        "Run task chains": actions.run_task_chains,
    },
    "Views": {
        "Analytics": {
            "Export views with persistence score 10": (
                actions.create_view_analytics
            ),
            "Export views where attribute contains": (
                actions.get_all_views_where_attribute_contains
            ),
        },
        "Partitions": {
            "Create Partitions": actions.create_partitioning_for_views,
            "Remove Partitions": actions.remove_partitioning_for_views,
            "Lock Partitions until Year": actions.lock_partitions_until_year,
            "Unlock All Partitions": actions.unlock_all_partitions,
        },
        "Persistence": {
            "Persist Views": actions.persist_views,
            "Unpersist Views": actions.unpersist_views,
        },
    },
}

# Default thread count per action (all others default to 1)
DEFAULT_THREAD_COUNTS: dict[Callable, int] = {
    actions.create_statistics: 5,
    actions.refresh_statistics: 5,
}

# Method-specific parameter definitions
# List of dicts, where every dict represents a question/prompt
# Available options:
#   name     – the method's keyword argument name
#   label    – text to display above the entry form
#   type     – "str" | "int" | "bool" | "choice"
#   choices  – list of strings (only for type "choice")
#   default  – optional default value
PARAM_DEFINITIONS: dict[Callable, list[dict]] = {
    actions.get_all_views_for_analytical_models: [
        {
            "name": "skip_duplicates",
            "label": "Skip duplicates?",
            "type": "bool",
            "default": False,
        },
    ],
    actions.get_all_views_for_analytical_models_in_space: [
        {
            "name": "space_name",
            "label": "Space name (e.g. CENTRAL_IT):",
            "type": "str",
        },
        {
            "name": "skip_duplicates",
            "label": "Skip duplicates?",
            "type": "bool",
            "default": False,
        },
    ],
    actions.create_statistics: [
        {
            "name": "statistics_type",
            "label": "Statistics type",
            "type": "choice",
            "choices": ["RECORD_COUNT", "SIMPLE", "HISTOGRAM"],
            "default": "HISTOGRAM",
        },
    ],
    actions.get_all_views_where_attribute_contains: [
        {
            "name": "word",
            "label": "Search word:",
            "type": "str",
        },
    ],
    actions.create_partitioning_for_views: [
        {
            "name": "partition_start",
            "label": "Lower bound of first partition (>=):",
            "type": "int",
        },
        {
            "name": "partition_end",
            "label": "Upper bound of last partition (<):",
            "type": "int",
        },
        {
            "name": "overwrite_existing_partitions",
            "label": "Overwrite existing partitions?",
            "type": "bool",
            "default": False,
        },
    ],
    actions.lock_partitions_until_year: [
        {
            "name": "year",
            "label": "Year (locked up to and including):",
            "type": "int",
        },
    ],
    actions.persist_views: [
        {
            "name": "timer",
            "label": "Save runtime?",
            "type": "bool",
            "default": False,
        },
    ],
}


class LogHandler(logging.Handler):
    """
    Custom logging handler that writes log messages to a Textual RichLog
    widget. Temporarily added to the logger before method execution and removed
    afterwards.
    """

    def __init__(self, log_widget: RichLog) -> None:
        super().__init__()
        self._log = log_widget

    def emit(self, record: logging.LogRecord) -> None:
        self._log.write(self.format(record))


class BaseScreen(Screen):
    """
    BaseScreen class to inherit from. Creates the global header and footer for
    the CLI.

    Provides the method 'compose_content' which needs to be overridden by any
    inheriting classes.
    """

    def compose(self) -> ComposeResult:
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
        yield Horizontal(
            Static("[b]Quit[/b] - Ctrl+C", id="footer-left"),
            Static("[b]Settings[/b] - Ctrl+S", id="footer-center"),
            Static(_APP_VERSION, id="footer-right"),
            id="footer",
        )

    @abstractmethod
    def compose_content(self) -> ComposeResult:
        raise NotImplementedError


class EntryScreen(BaseScreen):
    """
    Screen with the main menu. Shown after starting the CLI.
    """

    def __init__(self) -> None:
        super().__init__()

        # Holds all currently expanded menu options
        self._expanded: set[str] = set()

    def compose_content(self) -> ComposeResult:
        """
        Show menu in the main content widget.

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
        Event handler called after widget was added to the CLI.
        """
        self._rebuild_menu()

    def _rebuild_menu(self, restore_id: str | None = None) -> None:
        """
        Build the interactive menu.

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
        Event handler called when list option is selected.
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
                method = cast(Callable, MENU_OPTIONS[category][action])
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

    def __init__(self, action: Callable) -> None:
        super().__init__()
        self._action = action
        self._step: int = 0
        self._answers: dict[str, Any] = {}

        # Build list with all questions/prompts
        # Thread count is always the final prompt before starting the method
        self._steps: list[dict] = list(PARAM_DEFINITIONS.get(action, []))
        self._steps.append(
            {
                "name": "thread_count",
                "label": "Number of threads:",
                "type": "int",
                "default": DEFAULT_THREAD_COUNTS.get(action, 1),
            }
        )

    def compose_content(self) -> ComposeResult:
        """
        Load structure with all components. Content is populated in on_mount.

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
        Event handler called after widget was added to the CLI.
        """
        await self._show_step()

    def _build_widget(self, step: dict) -> Input | OptionList:
        """
        Builds the input widget for the current step, pre-filled with any
        previously entered answer or the parameter default.
        """
        name = step["name"]
        param_type = step["type"]
        value = self._answers.get(name, step.get("default", ""))

        # Input prompt for strings
        if param_type in ("str", "int"):
            return Input(
                value=str(value) if value != "" else "",
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
            *[Option(c, id=f"opt-{i}") for i, c in enumerate(step["choices"])],
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
        self.query_one("#param-label", Static).update(f"\n{step['label']}\n")

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
            ptype = step["type"]
            if ptype == "bool":
                val = self._answers.get(
                    step["name"], step.get("default", True)
                )
                widget.highlighted = 0 if bool(val) else 1
            elif ptype == "choice":
                current = self._answers.get(step["name"], step.get("default"))
                choices = step["choices"]
                widget.highlighted = (
                    choices.index(current) if current in choices else 0
                )

        # Focus widget to retrieve input from user
        widget.focus()

    def _validate_current(self) -> Any | None:
        """
        Reads and validates the current widget value.

        Returns:
            Validated value or None on validation error.
        """
        step = self._steps[self._step]
        param_type = step["type"]

        # Clear error message
        error = self.query_one("#param-error", Static)
        error.update("")

        # Check for errors
        if param_type in ("str", "int"):
            raw = self.query_one("#current-widget", Input).value.strip()
            if param_type == "str":
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
        return step["choices"][idx]

    async def _handle_confirm(self) -> None:
        """
        Validates the current step, stores the answer and advances to the next
        step or pushes ExecutionScreen on the final step.
        """
        # Check for errors (value=None)
        value = self._validate_current()
        if value is None:
            return

        # Get current step and add answer
        step = self._steps[self._step]
        self._answers[step["name"]] = value

        # On final step: Convert all answers to pass it as args to the method
        if self._step == len(self._steps) - 1:
            params = dict(self._answers)

            # Convert partition range to the list expected by the method
            if "partition_start" in params and "partition_end" in params:
                start = params.pop("partition_start")
                end = params.pop("partition_end")
                params["partitions"] = [str(y) for y in range(start, end + 1)]

            # Start ExecutionScreen to execute method
            self.app.push_screen(
                ExecutionScreen(self._action, params)
            )

        # On any other steps: increase step count and display next step
        else:
            self._step += 1
            await self._show_step()

    async def _handle_back(self) -> None:
        """
        Go back one step, or pop to EntryScreen if already on the first step.
        """
        if self._step == 0:
            self.app.pop_screen()
        else:
            self._step -= 1
            await self._show_step()

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        """
        Event handler called when Enter is pressed inside an Input widget.
        """
        await self._handle_confirm()

    async def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """
        Event handler called when an option is selected in a bool OptionList.
        OptionList consumes the Enter key itself, so we confirm here instead
        of in on_key.
        """
        if event.option_list.id == "current-widget":
            await self._handle_confirm()

    async def on_key(self, event: events.Key) -> None:
        """
        Event handler called when a key is pressed.
        """
        if event.key == "escape":
            await self._handle_back()


class ExecutionScreen(BaseScreen):
    """
    Screen that executes the selected action and shows live log output.
    """

    def __init__(
        self,
        action: Callable,
        params: dict[str, Any],
    ) -> None:
        super().__init__()
        self._action = action
        self._params = params
        self._done = False

    def compose_content(self) -> ComposeResult:
        """
        Show live log output and status for the running action.

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
        Event handler called after widget was added to the CLI. Starts the
        action worker.
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
        # datasphere-api library logs)
        handler = LogHandler(log_widget)
        handler.setFormatter(STREAM_FORMAT)
        library_logger = logging.getLogger(LIBRARY_LOGGER_NAME)
        logger.addHandler(handler)
        library_logger.addHandler(handler)

        # Create client, log in and call the action
        client: DatasphereClient | None = None
        try:
            client = DatasphereClient(build_config())
            await client.login()
            await self._action(client, **self._params)
            status.update("Done. Press Enter or Escape to return to the menu.")

        # Stop on any unhandled exceptions
        except Exception as e:
            status.update(
                f"[b][#AA0808]Error: {e}[/]\n"
                f"Press Enter or Escape to return."
            )

        # Remove handler to prevent multiple handlers co-existing if this
        # screen gets called more than once
        finally:
            if client is not None:
                await client.aclose()
            logger.removeHandler(handler)
            library_logger.removeHandler(handler)
            self._done = True

    def on_key(self, event: events.Key) -> None:
        """
        Event handler for key presses. Returns to EntryScreen after completion.
        """
        # Pop ExecutionScreen and ParamScreen to return to EntryScreen
        if self._done and event.key in ("enter", "escape"):
            self.app.pop_screen()
            self.app.pop_screen()


class SettingsScreen(BaseScreen):
    """
    Screen to view and edit the settings.ini file.
    Ctrl+S saves and reloads settings. Escape closes without saving.
    """

    BINDINGS = [Binding("ctrl+s", "save", "Save", show=False)]

    def compose_content(self) -> ComposeResult:
        yield Container(
            Static("Edit the settings:", id="settings-label"),
            TextArea(id="settings-editor"),
            Static("", id="settings-status"),
            id="content",
        )

    def compose_footer(self) -> ComposeResult:
        """
        Show custom footer with shortcuts to edit settings.

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
        Event handler called after widget was added to the CLI.
        """
        content = Path(SETTINGS_FILE).read_text(encoding="utf-8")
        self.query_one("#settings-editor", TextArea).load_text(content)

    def action_save(self) -> None:
        """
        Event handler called when settings are saved.
        """
        text = self.query_one("#settings-editor", TextArea).text
        Path(SETTINGS_FILE).write_text(text, encoding="utf-8")
        settings.read(SETTINGS_FILE)
        self.query_one("#settings-status", Static).update(
            "[green]Saved.[/green]"
        )

    async def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.app.pop_screen()


class DatasphereApp(App):
    """
    Global app configuration for the CLI. Calls the EntryScreen.
    """

    CSS_PATH = "../static/style.tcss"
    MIN_WIDTH = 112
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+s", "open_settings", "Settings", show=False),
    ]

    # Override unused bindings
    def action_copy_text(self) -> None: pass
    def action_focus_next(self) -> None: pass
    def action_focus_previous(self) -> None: pass

    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen())

    def on_mount(self) -> None:
        self.push_screen(EntryScreen())
