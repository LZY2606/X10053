# -*- test-case-name: automat._test.test_indexed_transitions -*-
"""
Contract tests for L{Automaton}'s indexed transition storage.

L{Automaton} keeps its transitions in indexes keyed by (state, input) and
by state, so that registration and lookup are O(1) rather than linear
scans.  These tests pin the observable contract that the indexing must
not drift from, by checking the indexed implementation against
L{ReferenceAutomaton}, a deliberately naive list-based parallel
implementation of the same contract:

- first-registration order is the canonical iteration order (never a
  global sort),
- the exact text and priority of registration errors is preserved,
- terminal states, self-loops, and unhandled-transition fallbacks behave
  the same,
- results handed out to callers are copies/snapshots (ownership does not
  leak),
- output-action failures still leave the machine in its new state,
- Graphviz output lists transitions in registration order,
  deterministically.
"""
from __future__ import annotations

from unittest import TestCase, skipIf

from .._core import Automaton, NoTransition, Transitioner
from .._methodical import MethodicalMachine
from .test_discover import isTwistedInstalled
from .test_visualize import isGraphvizModuleInstalled


class ReferenceAutomaton:
    """
    A naive, list-based parallel implementation of L{Automaton}'s
    transition-storage contract.  It performs linear scans on purpose; the
    indexed L{Automaton} must produce exactly the same observable results.
    """

    def __init__(self):
        self._transitions = []
        self._unhandled = None

    def addTransition(self, inState, inputSymbol, outState, outputSymbols):
        for anInState, anInputSymbol, anOutState, _ in self._transitions:
            if (anInState, anInputSymbol) == (inState, inputSymbol):
                raise ValueError(
                    "already have transition from {} to {} via {}".format(
                        inState, anOutState, inputSymbol
                    )
                )
        self._transitions.append((inState, inputSymbol, outState, tuple(outputSymbols)))

    def unhandledTransition(self, outState, outputSymbols):
        self._unhandled = (outState, tuple(outputSymbols))

    def outputForInput(self, inState, inputSymbol):
        for anInState, anInputSymbol, outState, outputSymbols in self._transitions:
            if (inState, inputSymbol) == (anInState, anInputSymbol):
                return (outState, list(outputSymbols))
        if self._unhandled is None:
            raise NoTransition(state=inState, symbol=inputSymbol)
        return self._unhandled

    def transitions(self):
        return tuple(self._transitions)

    def transitionsFrom(self, inState):
        return tuple(
            (inputSymbol, outState, outputSymbols)
            for (candidate, inputSymbol, outState, outputSymbols) in self._transitions
            if candidate == inState
        )


def registerMachine(auto, stateCount, inputsPerState):
    """
    Register C{stateCount * inputsPerState} transitions on C{auto}, in an
    order that is deliberately neither sorted nor reverse-sorted.
    """
    for state in range(stateCount):
        # Interleave input numbering so that registration order cannot be
        # reproduced by sorting the input symbols.
        for rawInput in range(inputsPerState):
            inputNumber = (rawInput * 7 + 3) % inputsPerState
            auto.addTransition(
                "state-{}".format(state),
                "input-{}".format(inputNumber),
                "state-{}".format((state + inputNumber + 1) % stateCount),
                ("out-{}-{}".format(state, inputNumber),),
            )


class RegistrationErrorContractTests(TestCase):
    """
    Duplicate-registration errors keep their exact text and priority.
    """

    def test_duplicateTransitionMessage(self):
        """
        Re-registering an existing (state, input) pair raises L{ValueError}
        naming the *first* registered target state, with the historical
        message text.
        """
        for auto in (Automaton(), ReferenceAutomaton()):
            auto.addTransition("begin", "go", "end", ("out",))
            with self.assertRaises(ValueError) as raised:
                auto.addTransition("begin", "go", "elsewhere", ("other",))
            self.assertEqual(
                str(raised.exception),
                "already have transition from begin to end via go",
            )

    def test_duplicateCheckPrecedesOutputValidation(self):
        """
        A duplicate (state, input) pair reports L{ValueError} even when the
        new outputs are also invalid; the duplicate check has priority over
        output validation.
        """
        for auto in (Automaton(), ReferenceAutomaton()):
            auto.addTransition("begin", "go", "end", ("out",))
            with self.assertRaises(ValueError):
                auto.addTransition("begin", "go", "elsewhere", 1)

    def test_invalidOutputsLeaveNoPartialRegistration(self):
        """
        Non-iterable outputs raise L{TypeError} and leave nothing
        registered: the same (state, input) pair can be registered
        successfully afterwards.
        """
        for auto in (Automaton(), ReferenceAutomaton()):
            with self.assertRaises(TypeError):
                auto.addTransition("begin", "go", "end", 1)
            self.assertEqual(auto.transitions(), ())
            self.assertEqual(auto.transitionsFrom("begin"), ())
            auto.addTransition("begin", "go", "end", ("out",))
            self.assertEqual(auto.outputForInput("begin", "go"), ("end", ["out"]))


class LookupContractTests(TestCase):
    """
    The indexed L{Automaton} and the L{ReferenceAutomaton} agree on every
    lookup for dense and sparse machines.
    """

    def assertSameBehavior(self, stateCount, inputsPerState):
        indexed = Automaton()
        reference = ReferenceAutomaton()
        registerMachine(indexed, stateCount, inputsPerState)
        registerMachine(reference, stateCount, inputsPerState)

        self.assertEqual(indexed.transitions(), reference.transitions())
        for state in range(stateCount):
            stateName = "state-{}".format(state)
            self.assertEqual(
                indexed.transitionsFrom(stateName),
                reference.transitionsFrom(stateName),
            )
            for inputNumber in range(inputsPerState):
                inputName = "input-{}".format(inputNumber)
                self.assertEqual(
                    indexed.outputForInput(stateName, inputName),
                    reference.outputForInput(stateName, inputName),
                )
            # Inputs that were never registered raise identically.
            with self.assertRaises(NoTransition):
                indexed.outputForInput(stateName, "no-such-input")
            with self.assertRaises(NoTransition):
                reference.outputForInput(stateName, "no-such-input")

    def test_denseMachine(self):
        """
        Dense machines (many inputs per state) behave identically under
        both implementations.
        """
        self.assertSameBehavior(stateCount=25, inputsPerState=16)

    def test_sparseMachine(self):
        """
        Sparse machines (one input per state, long chains) behave
        identically under both implementations.
        """
        self.assertSameBehavior(stateCount=400, inputsPerState=1)

    def test_terminalStateRaisesNoTransitionWithContext(self):
        """
        A state with no outgoing transitions raises L{NoTransition} that
        carries the state and input symbol for diagnosis.
        """
        for auto in (Automaton(), ReferenceAutomaton()):
            auto.addTransition("start", "finish", "done", ("fin",))
            with self.assertRaises(NoTransition) as raised:
                auto.outputForInput("done", "anything")
            self.assertEqual(raised.exception.state, "done")
            self.assertEqual(raised.exception.symbol, "anything")
            self.assertIn("done", str(raised.exception))
            self.assertIn("anything", str(raised.exception))

    def test_selfLoop(self):
        """
        A self-loop keeps the machine in the same state and emits its
        outputs in order, on every repetition.
        """
        for auto in (Automaton(), ReferenceAutomaton()):
            auto.addTransition("loop", "again", "loop", ("tick", "tock"))
            self.assertEqual(
                auto.outputForInput("loop", "again"), ("loop", ["tick", "tock"])
            )
            self.assertEqual(
                auto.outputForInput("loop", "again"), ("loop", ["tick", "tock"])
            )

        automaton = Automaton("loop")
        automaton.addTransition("loop", "again", "loop", ("tick",))
        transitioner = Transitioner(automaton, "loop")
        self.assertEqual(transitioner.transition("again"), (["tick"], None))
        self.assertEqual(transitioner.transition("again"), (["tick"], None))

    def test_unhandledTransitionFallback(self):
        """
        A registered unhandled-transition fallback handles unknown inputs,
        while known inputs still win; the fallback's outputs stay a tuple,
        exactly as historically returned.
        """
        for auto in (Automaton("start"), ReferenceAutomaton()):
            auto.addTransition("oops", "check", "start", ("checked",))
            auto.unhandledTransition("oops", ("oops-out",))
            self.assertEqual(
                auto.outputForInput("start", "check"), ("oops", ("oops-out",))
            )
            self.assertEqual(
                auto.outputForInput("oops", "check"), ("start", ["checked"])
            )


class OrderingContractTests(TestCase):
    """
    First-registration order is the canonical order; nothing is globally
    sorted to fake determinism.
    """

    def test_transitionsAreInRegistrationOrder(self):
        """
        L{Automaton.transitions} and L{Automaton.transitionsFrom} iterate
        transitions in the order they were first registered, which is
        deliberately neither sorted nor reverse-sorted here.
        """
        automaton = Automaton()
        automaton.addTransition("s1", "zulu", "s2", ("o1",))
        automaton.addTransition("s1", "alpha", "s3", ("o2",))
        automaton.addTransition("s2", "mike", "s1", ("o3",))

        registrationOrder = [("s1", "zulu"), ("s1", "alpha"), ("s2", "mike")]
        # The test data itself must defeat any global-sort implementation.
        inputOrder = [inputSymbol for (_, inputSymbol) in registrationOrder]
        self.assertNotEqual(inputOrder, sorted(inputOrder))
        self.assertNotEqual(inputOrder, sorted(inputOrder, reverse=True))

        self.assertEqual(
            [
                (state, inputSymbol)
                for (state, inputSymbol, _, _) in automaton.transitions()
            ],
            registrationOrder,
        )
        self.assertEqual(
            [inputSymbol for (inputSymbol, _, _) in automaton.transitionsFrom("s1")],
            ["zulu", "alpha"],
        )
        self.assertEqual(
            [inputSymbol for (inputSymbol, _, _) in automaton.transitionsFrom("s2")],
            ["mike"],
        )
        self.assertEqual(automaton.transitionsFrom("nowhere"), ())

    def test_rebuildsAreDeterministic(self):
        """
        Building the same machine twice yields exactly the same transition
        sequence.
        """

        def build():
            automaton = Automaton()
            registerMachine(automaton, stateCount=6, inputsPerState=6)
            return automaton

        self.assertEqual(build().transitions(), build().transitions())


class OwnershipContractTests(TestCase):
    """
    Callers cannot mutate the automaton's internal state through results.
    """

    def test_outputListIsACopy(self):
        """
        Mutating the output list returned by L{Automaton.outputForInput}
        does not corrupt the automaton.
        """
        automaton = Automaton()
        automaton.addTransition("s", "i", "s2", ("o1", "o2"))
        outState, outputs = automaton.outputForInput("s", "i")
        outputs.append("evil")
        self.assertEqual(automaton.outputForInput("s", "i"), ("s2", ["o1", "o2"]))
        (transition,) = automaton.transitions()
        self.assertEqual(transition[3], ("o1", "o2"))

    def test_allTransitionsIsASnapshot(self):
        """
        L{Automaton.allTransitions} returns a frozenset snapshot that later
        registrations do not affect.
        """
        automaton = Automaton()
        automaton.addTransition("s", "i", "s2", ("o",))
        snapshot = automaton.allTransitions()
        automaton.addTransition("s2", "j", "s", ("p",))
        self.assertIsInstance(snapshot, frozenset)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(len(automaton.allTransitions()), 2)


class MethodicalMachineContractTests(TestCase):
    """
    The L{MethodicalMachine} facade preserves its behavior on top of the
    indexed store.
    """

    def test_outputActionFailureStillTransitions(self):
        """
        If an output action raises, the exception propagates unchanged and
        the machine is left in the state it transitioned to.
        """
        mm = MethodicalMachine()

        class Machine:
            @mm.state(initial=True)
            def first(self):
                "initial state"

            @mm.state()
            def second(self):
                "state after the failing output"

            @mm.input()
            def go(self):
                "trigger the failing output"

            @mm.input()
            def check(self):
                "only valid in the second state"

            @mm.output()
            def boom(self):
                raise RuntimeError("output failed")

            @mm.output()
            def report(self):
                return "in-second"

            first.upon(go, enter=second, outputs=[boom])
            second.upon(check, enter=second, outputs=[report])

        machine = Machine()
        with self.assertRaises(RuntimeError) as raised:
            machine.go()
        self.assertEqual(str(raised.exception), "output failed")
        self.assertEqual(machine.check(), ["in-second"])

    def test_duplicateUponRaisesValueError(self):
        """
        Registering the same state/input pair twice through
        L{MethodicalState.upon} keeps the historical L{ValueError}.
        """
        mm = MethodicalMachine()

        class Machine:
            @mm.state(initial=True)
            def start(self):
                "only state"

            @mm.input()
            def go(self):
                "only input"

            start.upon(go, enter=start, outputs=[])
            try:
                start.upon(go, enter=start, outputs=[])
            except ValueError as error:
                duplicateError = error

        self.assertIn("already have transition", str(Machine.duplicateError))


@skipIf(not isGraphvizModuleInstalled(), "Graphviz module is not installed.")
@skipIf(not isTwistedInstalled(), "Twisted is not installed.")
class GraphvizOrderContractTests(TestCase):
    """
    Graphviz output lists transitions in first-registration order,
    deterministically.
    """

    def sampleMachine(self):
        mm = MethodicalMachine()

        class Machine:
            @mm.state(initial=True)
            def zuluState(self):
                "initial state, first-registered"

            @mm.state()
            def alphaState(self):
                "end state, second-registered"

            @mm.input()
            def zuluIn(self):
                "registered second"

            @mm.input()
            def alphaIn(self):
                "registered third"

            @mm.input()
            def mikeIn(self):
                "registered first"

            # Registration order is deliberately neither sorted nor
            # reverse-sorted, so a global sort cannot fake this order.
            zuluState.upon(mikeIn, enter=alphaState, outputs=[])
            zuluState.upon(zuluIn, enter=alphaState, outputs=[])
            zuluState.upon(alphaIn, enter=alphaState, outputs=[])

        return mm

    def test_graphvizTransitionOrderIsRegistrationOrder(self):
        """
        Transition labels appear in the DOT source in registration order.
        """
        gvout = "".join(self.sampleMachine().asDigraph())
        registrationOrder = ["mikeIn", "zuluIn", "alphaIn"]
        self.assertNotEqual(registrationOrder, sorted(registrationOrder))
        self.assertNotEqual(registrationOrder, sorted(registrationOrder, reverse=True))
        positions = [
            gvout.index(">{}<".format(inputName)) for inputName in registrationOrder
        ]
        self.assertEqual(positions, sorted(positions))

    def test_graphvizStateOrderIsRegistrationOrder(self):
        """
        State nodes appear in the DOT source in the order the states were
        first registered, not in sorted order.
        """
        gvout = "".join(self.sampleMachine().asDigraph())
        registrationOrder = ["zuluState", "alphaState"]
        self.assertNotEqual(registrationOrder, sorted(registrationOrder))
        positions = [gvout.index(stateName) for stateName in registrationOrder]
        self.assertEqual(positions, sorted(positions))

    def test_graphvizOutputIsDeterministic(self):
        """
        Building the same machine twice produces byte-identical DOT output.
        """
        self.assertEqual(
            "".join(self.sampleMachine().asDigraph()),
            "".join(self.sampleMachine().asDigraph()),
        )
