import sys
from collections.abc import Callable
from time import sleep
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.text import Text

from datasphere.analytical_models import AnalyticalModels
from datasphere.remote_tables import RemoteTables
from datasphere.task_chains import TaskChains
from datasphere.views import Views


# Override all error messages
class CustomizedPrompt(Prompt):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # Override error message
    def on_validate_error(self, value: str, *args, **kwargs):
        self.console.print("Please enter a valid value.", style="bold red")


class CustomizedIntPrompt(IntPrompt):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # Override error message
    def on_validate_error(self, value: str, *args, **kwargs):
        self.console.print("Please enter a valid number.", style="bold red")


class CustomizedConfirmPrompt(Confirm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # Override error message
    def on_validate_error(self, value: str, *args, **kwargs):
        self.console.print(
            "Please enter only 'y' or 'n'.\n",
            style="bold red",
            highlight=False,
        )


class Menu:
    def __init__(self):
        # Mapping of all classes
        self.classes = {
            "Analytical Models": AnalyticalModels,
            "Remote Tables": RemoteTables,
            "Task Chains": TaskChains,
            "Views": Views,
        }

        # Mapping of functions for the menus
        self.modules = {
            "Analytical Models": {
                "Export all models with views": (
                    AnalyticalModels.get_all_views_for_analytical_models
                ),
                "Export all models with views (by space)": AnalyticalModels.get_all_views_for_analytical_models_in_space,  # noqa: E501
                "Save runtime of all views of models": AnalyticalModels.check_runtime_for_all_views_of_analytical_models,  # noqa: E501
            },
            "Remote Tables": {
                "Create statistics for all tables": RemoteTables.create_statistics,  # noqa: E501
                "Refresh statistics for all tables": RemoteTables.refresh_statistics,  # noqa: E501
            },
            "Task Chains": {
                "Run task chains": TaskChains.run_task_chains,
            },
            "Views": {
                "Export all views with persistence score 10": Views.create_view_analytics,  # noqa: E501
                "Export all views that have an attribute with substring": Views.get_all_views_where_attribute_contains,  # noqa: E501
                "Create partitions for views": Views.create_partitioning_for_views,  # noqa: E501
                "Remove partitions for views": Views.remove_partitioning_for_views,  # noqa: E501
                "Lock partitions for views up to a specific year": Views.lock_partitions_until_year,  # noqa: E501
                "Unlock partitions for views": Views.unlock_all_partitions,  # noqa: E501
                "Persist views": Views.persist_views,
                "Unpersist views": Views.unpersist_views,
            },
        }

        # Initialize console and prompts
        self.console = Console(highlight=False)
        self.prompt = CustomizedPrompt(
            console=self.console, show_choices=False
        )
        self.int_prompt = CustomizedIntPrompt(
            console=self.console, show_choices=False
        )
        self.confirm_prompt = CustomizedConfirmPrompt(console=self.console)

        # Clear console
        self.console.clear()

        # Initialize variables
        self.chosen_class: type[Any] | None = None
        self.chosen_method: Callable[..., Any] | None = None
        self.all_params: dict[str, Any] = {}

    # Function to display menu
    def show_menu(
        self, options: dict | None = None, is_first_menu: bool = True
    ) -> tuple[type[Any], Callable[..., Any], dict[str, Any]]:
        """
        Displays a menu with header, subtitle, and available options.
        Returns the selected option (0 for exit, 1-n for options).

        Args:
            options (dict, optional): Dictionary with classes or their methods.
            is_first_menu (bool, optional): True if it's the first menu
                                            (shows "Exit" option, otherwise
                                            "Back" option is shown).
                                            Default is False.

        Returns:
            int: Selected option as an integer.
        """

        # Show first menu if no modules passed
        if options is None:
            options = self.classes

        # Header for all menus
        self.console.print(
            Panel(Text("SAP Automation", style="bold", justify="center"))
        )

        # Display subtitle
        self.console.print(
            Text(
                f"\n {'Categories' if is_first_menu else 'Available scripts'}"
                f"\n",
                style="bold",
            )
        )

        # Display all options (categories/scripts)
        for index, option in enumerate(options.keys()):
            self.console.print(f" {index + 1}. {option}", highlight=False)

        # Add exit / back option
        self.console.print(
            Text(
                f" 0. {'Exit' if is_first_menu else 'Back'}",
                style="grey42",
            )
        )

        # Request user input
        chosen_option = self.prompt.ask(
            "\nEnter number",
            show_choices=False,
            choices=[str(num) for num in range(len(options) + 1)],
        )
        chosen_option_int = int(chosen_option)
        self.console.clear()

        # Check if exit
        if chosen_option_int == 0:
            if is_first_menu:
                self.console.print("Exiting program...")
                for _ in range(5):
                    self.console.print(".", style="bold")
                    sleep(1 / 5)
                self.console.clear()
                sys.exit()
            else:
                return self.show_menu(is_first_menu=True)

        # Otherwise call menu of respective category or return selected
        # module
        else:
            if is_first_menu:
                self.chosen_class = self.classes[
                    list(options.keys())[chosen_option_int - 1]
                ]
                return self.show_menu(
                    options=self.modules[
                        list(options.keys())[chosen_option_int - 1]
                    ],
                    is_first_menu=False,
                )
            else:
                self.chosen_method = options[
                    list(options.keys())[chosen_option_int - 1]
                ]
                self.set_params_for_method()
                if self.chosen_class is None or self.chosen_method is None:
                    raise RuntimeError("Menu selection is incomplete.")
                return self.chosen_class, self.chosen_method, self.all_params

    def set_params_for_method(self) -> None:
        """
        Sets the parameters for the selected method and clears the console.
        """

        # Check if threads should be used
        use_threads = self.confirm_prompt.ask(
            "Use threads", case_sensitive=False
        )
        if use_threads:
            thread_count = self.int_prompt.ask("Number of threads")
            self.all_params["thread_count"] = thread_count
        self.console.print("")

        # Filter selected class and method
        # Analytical Models
        if self.chosen_method in AnalyticalModels.__dict__.values():
            if (
                self.chosen_method
                == AnalyticalModels.get_all_views_for_analytical_models
            ):
                self.all_params["skip_duplicates"] = self.confirm_prompt.ask(
                    "Skip duplicates", case_sensitive=False
                )

            elif (
                self.chosen_method
                == AnalyticalModels.get_all_views_for_analytical_models_in_space  # noqa: E501
            ):
                self.all_params["space_name"] = self.prompt.ask(
                    "Name of the space (e.g. CENTRAL_IT)"
                )
                self.all_params["skip_duplicates"] = self.confirm_prompt.ask(
                    "Skip duplicates", case_sensitive=False
                )

        # RemoteTables
        elif self.chosen_method in RemoteTables.__dict__.values():
            if self.chosen_method == RemoteTables.create_statistics:
                self.console.print("Select statistics type:")
                self.console.print("1. Record count")
                self.console.print("2. Simple statistics")
                self.console.print("3. Histogram")
                types = ["RECORD_COUNT", "SIMPLE", "HISTOGRAM"]
                index = self.int_prompt.ask(
                    "\nEnter number",
                    choices=["1", "2", "3"],
                    show_choices=False,
                )
                type = types[index - 1]
                self.all_params["type"] = type

            elif self.chosen_method == RemoteTables.refresh_statistics:
                pass

        # Views
        elif self.chosen_method in Views.__dict__.values():
            if (
                self.chosen_method
                == Views.get_all_views_where_attribute_contains
            ):
                self.all_params["word"] = self.prompt.ask("Search word")

            elif self.chosen_method == Views.create_partitioning_for_views:
                self.console.print("Please enter the partition range.")
                self.console.print(
                    "Partitions will be created in yearly intervals.\n"
                )
                partition_start = self.int_prompt.ask(
                    "Lower bound of first partition (>=):"
                )
                partition_end = self.int_prompt.ask(
                    "Upper bound of last partition (<):"
                )
                self.all_params["partitions"] = [
                    str(year)
                    for year in range(partition_start, partition_end + 1)
                ]
                self.all_params["overwrite_existing_partitions"] = (
                    self.confirm_prompt.ask(
                        "\nOverwrite existing partitions",
                        case_sensitive=False,
                    )
                )

            elif self.chosen_method == Views.persist_views:
                self.all_params["timer"] = self.confirm_prompt.ask(
                    "Save runtime", case_sensitive=False
                )

            elif self.chosen_method == Views.lock_partitions_until_year:
                self.console.print(
                    "Please enter the year up to which partitions "
                    "should be locked."
                )
                self.console.print(
                    "The entered year will be locked as well.\n"
                )
                self.all_params["year"] = self.int_prompt.ask("Year")

        # Clear console
        self.console.clear()
