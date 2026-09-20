"""
Regression tests for semantics adjacent to the transition-lookup refactor.

These behaviors do not live in the index itself, but an indexing change can
silently break them (an output invoked twice, an ordering change that swallows
an exception, a self-loop that disappears from the outgoing index).  They are
kept separate from the shared lookup contract on purpose so each failure
points at one precise design assumption.
"""

from __future__ import annotations

from unittest import TestCase

from .. import MethodicalMachine, NoTransition


class OutputRaising(Exception):
    """
    Raised deliberately by an output action below.
    """


def _machine_with_raising_output():
    class Mechanism:
        m = MethodicalMachine()

        @m.state(initial=True)
        def start(self):
            "start"

        @m.state()
        def end(self):
            "end"

        @m.input()
        def go(self):
            "go"

        @m.output()
        def explode(self):
            raise OutputRaising("boom")

        start.upon(go, enter=end, outputs=[explode])

    return Mechanism


def _machine_with_two_outputs(ran):
    class Mechanism:
        m = MethodicalMachine()

        @m.state(initial=True)
        def start(self):
            "start"

        @m.state()
        def end(self):
            "end"

        @m.input()
        def go(self):
            "go"

        @m.output()
        def first(self):
            ran.append("first")
            raise OutputRaising()

        @m.output()
        def second(self):
            ran.append("second")

        start.upon(go, enter=end, outputs=[first, second])

    return Mechanism


def _machine_with_duplicate():
    captured = {}

    class Mechanism:
        m = MethodicalMachine()

        @m.state(initial=True)
        def start(self):
            "start"

        @m.state()
        def first(self):
            "first destination"

        @m.state()
        def second(self):
            "second destination"

        @m.input()
        def event(self):
            "event"

        start.upon(event, enter=first, outputs=[])
        captured.update(start=start, first=first, second=second, event=event)

    return captured


class OutputActionErrorTests(TestCase):
    """
    When an output action raises, the exception must propagate unchanged and
    the state transition itself must already have happened, exactly as with
    the pre-index implementation.
    """

    def test_exception_propagates_after_state_change(self) -> None:
        Mechanism = _machine_with_raising_output()
        mechanism = Mechanism()
        with self.assertRaises(OutputRaising):
            mechanism.go()
        # The state moved before the output ran; the following input only
        # exists on `start`, so the indexed lookup must now report `end` in
        # the diagnostic context.
        with self.assertRaises(NoTransition) as cm:
            mechanism.go()
        message = str(cm.exception)
        self.assertIn("go", message)
        self.assertIn("end", message)
        self.assertNotIn("start", message)

    def test_later_outputs_not_run_after_raise(self) -> None:
        """
        Outputs execute in registration order; once one raises, no later
        output in the same transition may execute.
        """
        ran: list[str] = []
        Mechanism = _machine_with_two_outputs(ran)
        with self.assertRaises(OutputRaising):
            Mechanism().go()
        self.assertEqual(ran, ["first"])


class TerminalStateTests(TestCase):
    """
    A state with no outgoing edges is still a state, and sending any input in
    that state raises L{NoTransition} carrying the terminal state's name.
    """

    def test_terminal_state_raises_with_context(self) -> None:
        class Mechanism:
            m = MethodicalMachine()

            @m.state(initial=True)
            def running(self):
                "running"

            @m.state(terminal=True)
            def finished(self):
                "finished"

            @m.input()
            def finish(self):
                "finish"

            running.upon(finish, enter=finished, outputs=[])

        mechanism = Mechanism()
        mechanism.finish()
        with self.assertRaises(NoTransition) as cm:
            mechanism.finish()
        message = str(cm.exception)
        self.assertIn("finish", message)
        self.assertIn("finished", message)
        self.assertNotIn("running", message)

    def test_terminal_state_appears_in_graph(self) -> None:
        class Mechanism:
            m = MethodicalMachine()

            @m.state(initial=True)
            def running(self):
                "running"

            @m.state(terminal=True)
            def finished(self):
                "finished"

            @m.input()
            def finish(self):
                "finish"

            @m.output()
            def note(self):
                "note"

            running.upon(finish, enter=finished, outputs=[note])

        source = "".join(Mechanism.m.asDigraph())
        self.assertIn("running", source)
        self.assertIn("finished", source)


class SelfLoopTests(TestCase):
    """
    Self-loops exercise the outgoing-edge index: the in-state and out-state
    key coincide, so the state set must not accidentally drop the state.
    """

    def test_selfLoop_stays_in_state_and_runs_output(self) -> None:
        calls = []

        class Mechanism:
            m = MethodicalMachine()

            @m.state(initial=True)
            def looping(self):
                "looping"

            @m.input()
            def tick(self):
                "tick"

            @m.output()
            def beat(self):
                calls.append("beat")

            # Omit `enter`, per the public API: loops back to itself.
            looping.upon(tick, outputs=[beat])

        mechanism = Mechanism()
        mechanism.tick()
        mechanism.tick()
        mechanism.tick()
        self.assertEqual(calls, ["beat", "beat", "beat"])

    def test_selfLoop_outgoingIndex_lists_the_edge(self) -> None:
        from .._core import Automaton

        a: Automaton[str, str, str] = Automaton("looping")
        a.addTransition("looping", "tick", "looping", ("beat",))
        self.assertEqual(
            a.outputsFromState("looping"),
            [("tick", "looping", ("beat",))],
        )
        self.assertEqual(a.states(), frozenset({"looping"}))


class DuplicateRegistrationTests(TestCase):
    """
    The methodical-layer duplicate error must keep its exact wording and
    report the first registration's destination.
    """

    def test_duplicate_transition_error_text(self) -> None:
        captured = _machine_with_duplicate()
        with self.assertRaises(ValueError) as cm:
            captured["start"].upon(
                captured["event"], enter=captured["second"], outputs=[]
            )
        message = str(cm.exception)
        self.assertIn("already have transition", message)
        self.assertIn("Mechanism.event", message)
        self.assertIn("Mechanism.first", message)
        self.assertNotIn("Mechanism.second", message)
