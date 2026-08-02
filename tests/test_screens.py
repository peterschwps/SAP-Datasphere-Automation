from textual.widgets import Input

from datasphere_cli import actions
from datasphere_cli.cli.screens import DatasphereApp, ParamScreen


def test_optional_string_none_is_rendered_as_empty_input() -> None:
    """
    Checks that a cleared optional string leaves the field empty.
    """
    screen = ParamScreen(actions.export_analytical_model_view_dependencies)
    screen._answers["space"] = None

    widget = screen._build_widget(screen._steps[0])

    assert isinstance(widget, Input)
    assert widget.value == ""


def test_string_without_default_is_rendered_as_empty_input() -> None:
    """
    Checks that a required string without a default starts empty.
    """
    screen = ParamScreen(actions.export_view_attribute_matches)
    step = screen._steps[0]

    widget = screen._build_widget(step)

    # Without this the field would be pre-filled with the text 'None'
    assert step.name == "attribute_substring"
    assert isinstance(widget, Input)
    assert widget.value == ""


def test_number_without_default_is_rendered_as_empty_input() -> None:
    """
    Checks that a whole number without a default starts empty.
    """
    screen = ParamScreen(actions.create_view_partitioning_from_file)
    step = screen._steps[0]

    widget = screen._build_widget(step)

    assert step.name == "start_year"
    assert isinstance(widget, Input)
    assert widget.value == ""


async def test_number_with_default_is_pre_filled() -> None:
    """
    Checks that a default is still offered as the pre-filled answer.
    """
    screen = ParamScreen(actions.export_view_persistence_candidates)
    step = screen._steps[0]

    # A non-empty input value needs a running app, because Textual moves the
    # cursor behind it through a reactive watcher
    async with DatasphereApp().run_test():
        widget = screen._build_widget(step)

    # The fix for the empty field must not suppress real defaults
    assert step.name == "minimum_candidate_score"
    assert isinstance(widget, Input)
    assert widget.value == "10"
