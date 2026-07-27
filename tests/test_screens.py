from textual.widgets import Input

from datasphere_cli import actions
from datasphere_cli.cli.screens import ParamScreen


def test_optional_string_none_is_rendered_as_empty_input() -> None:
    screen = ParamScreen(actions.export_analytical_model_view_dependencies)
    screen._answers["space"] = None

    widget = screen._build_widget(screen._steps[0])

    assert isinstance(widget, Input)
    assert widget.value == ""
