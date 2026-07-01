from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from datasphere.analytical_models import AnalyticalModels
from datasphere.remote_tables import RemoteTables
from datasphere.task_chains import TaskChains
from datasphere.views import Views
from static.logo import ASCII_LOGO

MenuOptions: dict[str, type] = {
    "Analytical Models": AnalyticalModels,
    "Remote Tables": RemoteTables,
    "Task Chains": TaskChains,
    "Views": Views,
}

SubMenuOptions: dict[type, dict[str, Callable[..., Any]]] = {
    AnalyticalModels: {
        "Export all models with views": (
            AnalyticalModels.get_all_views_for_analytical_models
        ),
        "Export all models with views (by space)": (
            AnalyticalModels.get_all_views_for_analytical_models_in_space
        ),
        "Save runtime of all views of models": (
            AnalyticalModels.check_runtime_for_all_views_of_analytical_models
        ),
    },
    RemoteTables: {
        "Create statistics for all tables": RemoteTables.create_statistics,
        "Refresh statistics for all tables": RemoteTables.refresh_statistics,
    },
    TaskChains: {
        "Run task chains": TaskChains.run_task_chains,
    },
}

ViewsCategories: dict[str, dict[str, Callable[..., Any]]] = {
    "Analytics": {
        "Export views with persistence score 10": Views.create_view_analytics,
        "Export views where attribute contains": (
            Views.get_all_views_where_attribute_contains
        ),
    },
    "Partitions": {
        "Create Partitions": Views.create_partitioning_for_views,
        "Remove Partitions": Views.remove_partitioning_for_views,
        "Lock Partitions until Year": Views.lock_partitions_until_year,
        "Unlock All Partitions": Views.unlock_all_partitions,
    },
    "Persistence": {
        "Persist Views": Views.persist_views,
        "Unpersist Views": Views.unpersist_views,
    },
}


class BaseScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Static(id="header", content=ASCII_LOGO)
        yield from self.compose_content()
        yield Static(id="footer", content="Press Ctrl+C to exit at any time.")

    @abstractmethod
    def compose_content(self) -> ComposeResult:
        raise NotImplementedError


class EntryScreen(BaseScreen):
    def __init__(self) -> None:
        super().__init__()
        self._expanded: set[str] = set()

    def compose_content(self) -> ComposeResult:
        yield Container(
            Static("\nSelect an option:"),
            OptionList(id="menu"),
            id="content",
        )

    def on_mount(self) -> None:
        self._rebuild_menu()

    def _rebuild_menu(self, restore_id: str | None = None) -> None:
        menu = self.query_one(OptionList)
        menu.clear_options()
        for category in MenuOptions:
            is_expanded = category in self._expanded
            prefix = "▼ " if is_expanded else "▶ "
            menu.add_option(
                Option(f"{prefix}{category}", id=f"cat:{category}")
            )
            if is_expanded:
                cls = MenuOptions[category]
                if cls is Views:
                    for subcat in ViewsCategories:
                        is_sub = f"{category}::{subcat}" in self._expanded
                        subprefix = "  ▼ " if is_sub else "  ▶ "
                        menu.add_option(
                            Option(
                                f"{subprefix}{subcat}",
                                id=f"subcat:{category}::{subcat}",
                            )
                        )
                        if is_sub:
                            for action in ViewsCategories[subcat]:
                                menu.add_option(
                                    Option(
                                        f"      {action}",
                                        id=f"act:{category}::{subcat}::{action}",
                                    )
                                )
                else:
                    for action in SubMenuOptions[cls]:
                        menu.add_option(
                            Option(
                                f"    {action}",
                                id=f"act:{category}::{action}",
                            )
                        )
        if restore_id:
            for i, opt in enumerate(menu._options):
                if opt.id == restore_id:
                    menu.highlighted = i
                    break

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        option_id = str(event.option.id)
        if option_id.startswith("cat:"):
            category = option_id[4:]
            if category in self._expanded:
                self._expanded = {
                    e for e in self._expanded
                    if not e.startswith(f"{category}::")
                }
                self._expanded.discard(category)
            else:
                self._expanded.add(category)
            self._rebuild_menu(restore_id=option_id)
        elif option_id.startswith("subcat:"):
            path = option_id[7:]
            if path in self._expanded:
                self._expanded.discard(path)
            else:
                self._expanded.add(path)
            self._rebuild_menu(restore_id=option_id)
        elif option_id.startswith("act:"):
            parts = option_id[4:].split("::")
            if len(parts) == 2:
                category, action = parts
                self.app.exit(SubMenuOptions[MenuOptions[category]][action])
            elif len(parts) == 3:
                _, subcat, action = parts
                self.app.exit(ViewsCategories[subcat][action])


class DatasphereApp(App):
    CSS_PATH = "static/test.tcss"
    MIN_WIDTH = 112
    BINDINGS = [Binding("ctrl+c", "quit", "Quit", show=False)]

    def on_mount(self) -> None:
        self.push_screen(EntryScreen())


if __name__ == "__main__":
    selected_method = DatasphereApp().run(mouse=False)
