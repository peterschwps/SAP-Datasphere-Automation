from datasphere_core.models.common import (
    CommandProgress,
    CommandProgressPhase,
)
from textual.widgets import Input

from datasphere_cli import actions
from datasphere_cli.cli.screens import (
    DatasphereApp,
    ParamScreen,
    _outcome_segment_widths,
    progress_line,
    progress_status,
)


async def test_app_uses_native_terminal_colors() -> None:
    """
    Checks that ANSI defaults pass through instead of becoming dark RGB.
    """
    async with DatasphereApp().run_test() as pilot:
        assert pilot.app.theme == "ansi-dark"
        assert pilot.app.native_ansi_color


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


def test_progress_line_lists_only_recorded_outcomes() -> None:
    """
    Checks that the status line names the counters that are not zero.
    """
    line = progress_line(
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=34,
            total_items=53,
            succeeded_items=30,
            failed_items=3,
            skipped_items=1,
            timed_out_items=0,
        )
    )

    # A zero counter would only pad the line
    assert line == "34/53 · 30 succeeded, 3 failed, 1 skipped"


def test_progress_line_without_outcomes_shows_the_count_alone() -> None:
    """
    Checks that the status line falls back to the bare item count.
    """
    line = progress_line(
        CommandProgress(
            command="views.persist_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=1,
            total_items=2,
        )
    )

    assert line == "1/2"


def test_progress_status_ignores_updates_without_a_count() -> None:
    """
    Checks that an update without counters leaves the line alone. The screen
    already says that the action is running, and the command name is an
    internal identifier the user has no use for.
    """
    for phase in (
        CommandProgressPhase.STARTED,
        CommandProgressPhase.COMPLETED,
        CommandProgressPhase.CANCELLED,
    ):
        update = CommandProgress(command="views.persist_batch", phase=phase)
        assert progress_status(update) is None


def test_progress_status_switches_to_the_counter_once_items_finish() -> None:
    """
    Checks that a counted update replaces the announcement.
    """
    line = progress_status(
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.ADVANCED,
            completed_items=1,
            total_items=3,
            succeeded_items=1,
        )
    )

    assert line == "1/3 · 1 succeeded"


def test_progress_status_initializes_a_known_batch() -> None:
    """
    Checks that a newly initialized batch displays zero completed items.
    """
    line = progress_status(
        CommandProgress(
            command="task_chains.run_batch",
            phase=CommandProgressPhase.STARTED,
            completed_items=0,
            total_items=1,
            succeeded_items=0,
            failed_items=0,
            skipped_items=0,
            timed_out_items=0,
        )
    )

    assert line == "0/1"


def test_outcome_segments_leave_unknown_progress_unfilled() -> None:
    """
    Checks that a batch without a known size renders as entirely pending.
    """
    update = CommandProgress(
        command="views.persist_batch",
        phase=CommandProgressPhase.STARTED,
    )

    widths = _outcome_segment_widths(update, 20)

    assert widths == (0, 0, 20, 0)


def test_outcome_segments_split_completed_and_pending_items() -> None:
    """
    Checks that each outcome receives its proportional part of the bar.
    """
    update = CommandProgress(
        command="views.persist_batch",
        phase=CommandProgressPhase.ADVANCED,
        completed_items=7,
        total_items=10,
        succeeded_items=3,
        skipped_items=2,
        failed_items=1,
        timed_out_items=1,
    )

    widths = _outcome_segment_widths(update, 20)

    # Errors stay anchored to the right with pending work before them
    assert widths == (6, 4, 6, 4)


def test_outcome_segments_fill_successful_batch_in_green() -> None:
    """
    Checks that an entirely successful batch fills the first segment.
    """
    update = CommandProgress(
        command="task_chains.run_batch",
        phase=CommandProgressPhase.COMPLETED,
        completed_items=4,
        total_items=4,
        succeeded_items=4,
    )

    widths = _outcome_segment_widths(update, 20)

    assert widths == (20, 0, 0, 0)
