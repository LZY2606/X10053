"""
Shared contract for transition lookup.

The contract in this module is executed against two parallel implementations
of L{automat._core.Automaton}'s transition storage:

    - L{IndexedContract}: the current, indexed implementation under test.
    - L{LegacyContract}: the pre-refactor flat-C{set} implementation copied
      into L{automat._test._legacy_core}, which serves as an immutable
      reference oracle.

Every behavior-level test runs against *both* implementations, so that the
indexing refactor cannot silently drift on exception text, error priority,
returned ownership, or alphabet contents.  Order-sensitive assertions live in
the indexed-only test classes: the legacy implementation has no deterministic
enumeration order by design (a C{set} iterates in hash order), which is
exactly the defect the refactor removes.
"""

from __future__ import annotations

from typing import Any
from unittest import TestCase

from .._core import Automaton, NoTransition
from ._legacy_core import LegacyAutomaton, NoTransition as LegacyNoTransition


class Colliding:
    """
    A hashable token whose hash deliberately collides with every other
    L{Colliding}.

    C{set} iteration in CPython is driven by hash slots, so hash collisions
    reorder enumeration; a registration-order-preserving structure must not
    care.  Equality stays identity-based so distinct tokens remain distinct
    keys.
    """

    def __init__(self, name: str, hashValue: int = 0):
        self.name = name
        self.hashValue = hashValue

    def __hash__(self) -> int:
        return self.hashValue

    def __eq__(self, other: object) -> bool:
        return self is other or (
            isinstance(other, Colliding) and other.name == self.name
        )

    def __repr__(self) -> str:
        return "Colliding({!r})".format(self.name)


class _AutomatonContract(TestCase):
    """
    Behavior shared by the indexed automaton and the legacy reference.

    Subclasses set C{automatonClass} and C{noTransitionClass}.  The leading
    underscore keeps pytest from collecting this class on its own.
    """

    automatonClass: Any = Automaton
    noTransitionClass: Any = NoTransition

    def make(self, initial: Any = None) -> Any:
        if initial is None:
            return self.automatonClass()
        return self.automatonClass(initial)

    # -- basic lookup -----------------------------------------------------

    def test_oneTransition_lookup(self) -> None:
        a = self.make()
        a.addTransition("beginning", "begin", "ending", ["end"])
        self.assertEqual(a.outputForInput("beginning", "begin"), ("ending", ["end"]))
        self.assertEqual(a.inputAlphabet(), {"begin"})
        self.assertEqual(a.outputAlphabet(), {"end"})
        self.assertEqual(a.states(), {"beginning", "ending"})

    def test_outputForInput_missing_raises(self) -> None:
        a = self.make()
        with self.assertRaises(self.noTransitionClass) as cm:
            a.outputForInput("no-state", "no-symbol")
        self.assertEqual(str(cm.exception), "no transition for no-symbol in no-state")
        self.assertIs(cm.exception.state, "no-state")
        self.assertIs(cm.exception.symbol, "no-symbol")

    def test_unhandledTransition_fallback(self) -> None:
        a = self.make("start")
        a.addTransition("oops-state", "check", "start", ("checked",))
        a.unhandledTransition("oops-state", ["oops-out"])
        self.assertEqual(
            a.outputForInput("start", "anything"),
            ("oops-state", ("oops-out",)),
        )
        self.assertEqual(
            a.outputForInput("oops-state", "check"), ("start", ["checked"])
        )

    def test_unhandledTransition_doesNotShadowRealTransitions(self) -> None:
        a = self.make("start")
        a.addTransition("start", "go", "end", ("done",))
        a.unhandledTransition("err", ("oops",))
        self.assertEqual(a.outputForInput("start", "go"), ("end", ["done"]))
        self.assertEqual(a.outputForInput("start", "other"), ("err", ("oops",)))

    # -- duplicate registration ------------------------------------------

    def test_duplicate_raises_with_original_text(self) -> None:
        a = self.make()
        a.addTransition("here", "event", "there", ["out"])
        with self.assertRaises(ValueError) as cm:
            a.addTransition("here", "event", "elsewhere", ["other"])
        self.assertEqual(
            str(cm.exception),
            "already have transition from here to there via event",
        )

    def test_duplicate_error_names_first_outState(self) -> None:
        """
        The diagnostic reports the out-state of the *first* registration,
        not the rejected one; this is why the index must remember which
        transition won.
        """
        a = self.make()
        a.addTransition("s", "i", "first", ())
        with self.assertRaises(ValueError) as cm:
            a.addTransition("s", "i", "second", ())
        self.assertIn("to first", str(cm.exception))
        self.assertNotIn("second", str(cm.exception))

    def test_duplicate_different_outState_is_still_duplicate(self) -> None:
        a = self.make()
        a.addTransition("s", "i", "a", ())
        with self.assertRaises(ValueError):
            a.addTransition("s", "i", "b", ())

    def test_sameStateDifferentInput_isNotDuplicate(self) -> None:
        a = self.make()
        a.addTransition("s", "i1", "e", ())
        a.addTransition("s", "i2", "e", ())
        self.assertEqual(a.inputAlphabet(), {"i1", "i2"})

    def test_sameInputDifferentState_isNotDuplicate(self) -> None:
        a = self.make()
        a.addTransition("s1", "i", "e", ())
        a.addTransition("s2", "i", "e", ())
        self.assertEqual(a.states(), {"s1", "s2", "e"})

    def test_duplicate_leaves_first_transition_intact(self) -> None:
        a = self.make()
        a.addTransition("s", "i", "kept", ("kept-out",))
        with self.assertRaises(ValueError):
            a.addTransition("s", "i", "dropped", ("dropped-out",))
        self.assertEqual(a.outputForInput("s", "i"), ("kept", ["kept-out"]))
        self.assertEqual(a.outputAlphabet(), {"kept-out"})
        self.assertEqual(a.allTransitions(), {("s", "i", "kept", ("kept-out",))})

    def test_duplicate_atomically_ignores_outputs(self) -> None:
        """
        Outputs from the rejected re-registration never leak into the output
        alphabet even though they were iterated during validation.
        """
        a = self.make()
        a.addTransition("s", "i", "e", ("o1",))
        with self.assertRaises(ValueError):
            a.addTransition("s", "i", "e2", ("o2", "o3"))
        self.assertEqual(a.outputAlphabet(), {"o1"})

    # -- equality vs identity for keys -----------------------------------

    def test_keys_compare_by_equality_not_identity(self) -> None:
        a = self.make()
        a.addTransition(("s",), "i", "e", ())
        with self.assertRaises(ValueError):
            a.addTransition(("s",), "i", "e2", ())
        self.assertEqual(a.outputForInput(("s",), "i"), ("e", []))

    def test_hash_colliding_states_indexed_separately(self) -> None:
        s1 = Colliding("s1")
        s2 = Colliding("s2")
        a = self.make()
        a.addTransition(s1, "i", "e1", ())
        a.addTransition(s2, "i", "e2", ())
        self.assertEqual(a.outputForInput(s1, "i"), ("e1", []))
        self.assertEqual(a.outputForInput(s2, "i"), ("e2", []))
        self.assertEqual(a.states(), {s1, s2, "e1", "e2"})

    def test_hash_colliding_inputs_indexed_separately(self) -> None:
        i1 = Colliding("i1")
        i2 = Colliding("i2")
        a = self.make()
        a.addTransition("s", i1, "e1", ())
        a.addTransition("s", i2, "e2", ())
        self.assertEqual(a.outputForInput("s", i1), ("e1", []))
        self.assertEqual(a.outputForInput("s", i2), ("e2", []))
        with self.assertRaises(ValueError):
            a.addTransition("s", i1, "e3", ())

    # -- self loops / terminal-like reachability -------------------------

    def test_selfLoop_is_a_normal_transition(self) -> None:
        a = self.make("looping")
        a.addTransition("looping", "tick", "looping", ("beat",))
        outState, outputs = a.outputForInput("looping", "tick")
        self.assertEqual(outState, "looping")
        self.assertEqual(outputs, ["beat"])
        self.assertEqual(a.states(), {"looping"})

    def test_deadEndState_still_a_state(self) -> None:
        a = self.make("start")
        a.addTransition("start", "stop", "terminal", ())
        self.assertIn("terminal", a.states())
        with self.assertRaises(self.noTransitionClass):
            a.outputForInput("terminal", "stop")

    # -- ownership / mutation isolation ----------------------------------

    def test_returned_outputs_are_not_shared_storage(self) -> None:
        stored = ("o1", "o2")
        a = self.make()
        a.addTransition("s", "i", "e", stored)
        _, first = a.outputForInput("s", "i")
        _, second = a.outputForInput("s", "i")
        self.assertEqual(first, ["o1", "o2"])
        self.assertIsNot(first, second)
        first.append("mutated")
        _, third = a.outputForInput("s", "i")
        self.assertEqual(third, ["o1", "o2"])

    def test_outputSequence_is_coerced_to_tuple(self) -> None:
        a = self.make()
        a.addTransition("s", "i", "e", ["o1", "o2"])
        (transition,) = a.allTransitions()
        self.assertIsInstance(transition[3], tuple)

    def test_allTransitions_is_frozenset(self) -> None:
        a = self.make()
        a.addTransition("s", "i", "e", ("o",))
        self.assertIsInstance(a.allTransitions(), frozenset)
        self.assertEqual(a.allTransitions(), {("s", "i", "e", ("o",))})

    # -- error priority ---------------------------------------------------

    def test_duplicateCheck_runs_before_outputStorage_failure(self) -> None:
        """
        A duplicate (state, input) is rejected even when the new output
        sequence contains an unhashable element; collision detection has
        priority over storage errors.
        """
        a = self.make()
        a.addTransition("s", "i", "e", ("o",))
        with self.assertRaises(ValueError):
            a.addTransition("s", "i", "e", (object(),))

    def test_nonIterableOutputs_raises_TypeError_and_changes_nothing(self) -> None:
        a = self.make()
        with self.assertRaises(TypeError):
            a.addTransition("from", "via", "to", 1)
        self.assertFalse(a.inputAlphabet())
        self.assertFalse(a.outputAlphabet())
        self.assertFalse(a.states())
        self.assertFalse(a.allTransitions())

    # -- initial state ----------------------------------------------------

    def test_initialState_can_only_be_set_once(self) -> None:
        a = self.make()
        a.initialState = "a state"
        self.assertEqual(a.initialState, "a state")
        with self.assertRaises(ValueError) as cm:
            a.initialState = "another"
        self.assertEqual(str(cm.exception), "initial state already set to a state")

    def test_default_initialState_is_sentinel(self) -> None:
        a = self.make()
        self.assertEqual(a.initialState, "<no state>")

    # -- alphabets aggregate correctly -----------------------------------

    def test_alphabets_aggregate_across_transitions(self) -> None:
        a = self.make()
        a.addTransition("s1", "i1", "s2", ("o1",))
        a.addTransition("s2", "i2", "s3", ("o1", "o2"))
        a.addTransition("s3", "i3", "s1", ())
        self.assertEqual(a.inputAlphabet(), {"i1", "i2", "i3"})
        self.assertEqual(a.outputAlphabet(), {"o1", "o2"})
        self.assertEqual(a.states(), {"s1", "s2", "s3"})


class IndexedContract(_AutomatonContract, TestCase):
    """
    The shared contract applied to the current indexed L{Automaton}.
    """

    automatonClass = Automaton
    noTransitionClass = NoTransition


class LegacyContract(_AutomatonContract, TestCase):
    """
    The shared contract applied to the legacy flat-set oracle.  If this and
    L{IndexedContract} ever disagree, the refactor has drifted from the
    original behavior.
    """

    automatonClass = LegacyAutomaton
    noTransitionClass = LegacyNoTransition


class _DenseSparseShapeContract:
    """
    The same dense/sparse shapes used by the benchmarks, checked for value
    equality between the indexed automaton and the legacy oracle.  These pin
    the contract on non-trivial machine sizes, not just 1-3 transition toys.
    """

    def _build(self, cls, dense):
        automaton = cls("s0")
        if dense:
            for stateIndex in range(8):
                for inputIndex in range(8):
                    automaton.addTransition(
                        "s{}".format(stateIndex),
                        "i{}".format(inputIndex),
                        "s{}".format((stateIndex + inputIndex + 1) % 8),
                        ("o{}-{}".format(stateIndex, inputIndex),),
                    )
        else:
            for stateIndex in range(300):
                automaton.addTransition(
                    "s{}".format(stateIndex),
                    "i",
                    "s{}".format((stateIndex + 1) % 300),
                    ("o",),
                )
        return automaton

    def _assertShapeMatchesLegacy(self, dense):
        indexed = self._build(Automaton, dense)
        legacy = self._build(LegacyAutomaton, dense)
        self.assertEqual(indexed.allTransitions(), legacy.allTransitions())
        self.assertEqual(indexed.states(), legacy.states())
        self.assertEqual(indexed.inputAlphabet(), legacy.inputAlphabet())
        self.assertEqual(indexed.outputAlphabet(), legacy.outputAlphabet())
        states = sorted(indexed.states())
        inputs = sorted(indexed.inputAlphabet())
        for state in states[:: max(1, len(states) // 12)]:
            for inputSymbol in inputs:
                try:
                    expected = legacy.outputForInput(state, inputSymbol)
                except LegacyNoTransition:
                    with self.assertRaises(NoTransition):
                        indexed.outputForInput(state, inputSymbol)
                else:
                    actual = indexed.outputForInput(state, inputSymbol)
                    self.assertEqual(actual[0], expected[0])
                    self.assertEqual(list(actual[1]), list(expected[1]))

    def test_dense_shape_matches_legacy(self) -> None:
        self._assertShapeMatchesLegacy(dense=True)

    def test_sparse_shape_matches_legacy(self) -> None:
        self._assertShapeMatchesLegacy(dense=False)


class DenseSparseIndexedContract(_DenseSparseShapeContract, TestCase):
    """
    Dense/sparse contract entry point; the assertions compare the indexed
    implementation against the legacy oracle directly.
    """


# ---------------------------------------------------------------------------
# Indexed-only guarantees
#
# Everything below pins behavior that the legacy flat-set implementation
# provably *cannot* provide: deterministic first-registration enumeration and
# O(1)-ish lookup.  These tests are the regression net for the refactor.
# ---------------------------------------------------------------------------


class RegistrationOrderTests(TestCase):
    """
    Transition enumeration follows the order transitions were first
    registered, regardless of hash slots.
    """

    def _registered(self, a):
        return list(a.transitionsInRegistrationOrder())

    def test_allTransitions_is_firstRegistration_order(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        registered = []
        for n in range(50):
            transition = ("s{}".format(n), "i", "e{}".format(n), ("o",))
            a.addTransition(*transition)
            registered.append(transition)
        self.assertEqual(a.transitionsInRegistrationOrder(), tuple(registered))

    def test_order_is_not_global_sort(self) -> None:
        """
        A reverse-registration ordering survives; the implementation must not
        achieve determinism by sorting keys.
        """
        a: Automaton[object, object, object] = Automaton()
        order = []
        for n in range(10, 0, -1):
            transition = ("state-{:02d}".format(n), "input", "end", ())
            a.addTransition(*transition)
            order.append(transition)
        self.assertEqual(a.transitionsInRegistrationOrder(), tuple(order))
        self.assertNotEqual(list(a.allTransitions()), sorted(order))

    def test_order_survives_hash_collisions(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        states = [Colliding("state-{}".format(n)) for n in range(12)]
        inputs = [Colliding("input-{}".format(n)) for n in range(12)]
        registered = []
        for s, i in zip(states, inputs):
            transition = (s, i, "end", ())
            a.addTransition(*transition)
            registered.append(transition)
        # The legacy set order for these same objects is permuted (verified
        # at module design time); registration order must win.
        self.assertEqual(
            [t[0].name for t in self._registered(a)],
            [s.name for s in states],
        )
        self.assertEqual(
            [t[1].name for t in self._registered(a)],
            [i.name for i in inputs],
        )

    def test_order_survives_set_growth(self) -> None:
        """
        Many insertions trigger repeated hash-table growth in a set-backed
        implementation; registration order must remain intact.
        """
        a: Automaton[object, object, object] = Automaton()
        registered = []
        for n in range(2000):
            transition = ("s{}".format(n % 300), n, "e", ())
            a.addTransition(*transition)
            registered.append(transition)
        self.assertEqual(a.transitionsInRegistrationOrder(), tuple(registered))

    def test_duplicate_does_not_reorder_or_renew(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        a.addTransition("s1", "i", "e1", ())
        a.addTransition("s2", "i", "e2", ())
        with self.assertRaises(ValueError):
            a.addTransition("s1", "i", "e3", ())
        self.assertEqual(
            list(a.transitionsInRegistrationOrder()),
            [("s1", "i", "e1", ()), ("s2", "i", "e2", ())],
        )

    def test_outgoing_from_state_is_registration_ordered(self) -> None:
        """
        The state outgoing-edge index enumerates that state's edges in
        first-registration order.
        """
        a: Automaton[object, object, object] = Automaton()
        a.addTransition("s", "z", "e", ())
        a.addTransition("s", "a", "e", ())
        a.addTransition("s", "m", "e", ())
        a.addTransition("other", "x", "e", ())
        outgoing = [(i, o) for (i, o, outs) in a.outputsFromState("s")]
        self.assertEqual(outgoing, [("z", "e"), ("a", "e"), ("m", "e")])
        self.assertEqual(
            [(i, o) for (i, o, outs) in a.outputsFromState("other")],
            [("x", "e")],
        )

    def test_outgoing_from_unknown_state_is_empty(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        a.addTransition("s", "i", "e", ())
        self.assertEqual(list(a.outputsFromState("never-mentioned")), [])


class _CountingEquals:
    """
    A string wrapper counting invocations of C{__eq__}, used to prove lookup
    and duplicate detection do not linearly scan every transition.
    """

    def __init__(self, value: str):
        self.value = value
        self.comparisons = 0

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        self.comparisons += 1
        if isinstance(other, _CountingEquals):
            return self.value == other.value
        return self.value == other

    def __repr__(self) -> str:
        return self.value


class IndexComplexityTests(TestCase):
    """
    Lookup and duplicate detection are indexed rather than linear scans.

    The legacy implementation performs one C{__eq__} comparison per existing
    transition on every C{addTransition}/C{outputForInput}; these tests cap
    comparisons at a small constant so that a regression to a linear scan is
    mechanically detectable without timing-based flakiness.
    """

    SIZE = 500

    def test_duplicateCheck_is_indexed_on_build(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        for n in range(self.SIZE):
            a.addTransition("s{}".format(n), "i", "e", ())
        key = _CountingEquals("s0")
        with self.assertRaises(ValueError):
            a.addTransition(key, "i", "e2", ())
        # A linear scan compares the key against all 500 in-states.
        self.assertLess(key.comparisons, 10)

    def test_outputForInput_is_indexed_at_runtime(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        for n in range(self.SIZE):
            a.addTransition("s{}".format(n), "i", "e{}".format(n), ())
        key = _CountingEquals("s{}".format(self.SIZE - 1))
        outState, outputs = a.outputForInput(key, "i")
        self.assertEqual(outState, "e{}".format(self.SIZE - 1))
        self.assertEqual(outputs, [])
        self.assertLess(key.comparisons, 10)

    def test_missing_input_is_indexed(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        for n in range(self.SIZE):
            a.addTransition("s", "i{}".format(n), "e", ())
        key = _CountingEquals("missing")
        with self.assertRaises(NoTransition):
            a.outputForInput("s", key)
        self.assertLess(key.comparisons, 10)

    def test_outgoing_index_partitions_by_state(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        for n in range(20):
            a.addTransition("a", "i{}".format(n), "x", ())
        for n in range(20):
            a.addTransition("b", "j{}".format(n), "y", ())
        aEdges = list(a.outputsFromState("a"))
        bEdges = list(a.outputsFromState("b"))
        self.assertEqual(len(aEdges), 20)
        self.assertEqual(len(bEdges), 20)
        self.assertTrue(all(out == "x" for (_, out, _) in aEdges))
        self.assertTrue(all(out == "y" for (_, out, _) in bEdges))


class GraphvizOrderTests(TestCase):
    """
    Graph generation consumes transitions in first-registration order; edge
    ordering in the emitted DOT must not depend on hash-table layout.
    """

    def _digraph(self, automaton):
        from .._visualize import makeDigraph

        return makeDigraph(
            automaton,
            stateAsString=lambda token: getattr(token, "name", str(token)),
            inputAsString=lambda token: getattr(token, "name", str(token)),
            outputAsString=lambda token: getattr(token, "name", str(token)),
        )

    def _transitionLabelOrder(self, digraph):
        """
        Return the ordered list of (node id, input label) pairs for the
        synthetic ``tN`` transition nodes, in DOT-body emission order.
        """
        import re

        labeled = re.compile(r"^\s*(t\d+)\s.*?<font[^>]*>([^<]+)</font>", re.S)
        order = []
        for statement in digraph.body:
            match = labeled.match(statement)
            if match is not None:
                order.append((match.group(1), match.group(2)))
        return order

    def test_transition_nodes_numbered_by_registration(self) -> None:
        a: Automaton[object, object, object] = Automaton()
        pairs = [
            ("s9", "i9"),
            ("s1", "i1"),
            ("s7", "i7"),
            ("s3", "i3"),
            ("s5", "i5"),
            ("s0", "i0"),
        ]
        for state, inputToken in pairs:
            a.addTransition(state, inputToken, "end", ())
        order = self._transitionLabelOrder(self._digraph(a))
        self.assertEqual(
            [name for name, _ in order],
            ["t{}".format(n) for n in range(len(pairs))],
        )
        self.assertEqual(
            [label for _, label in order],
            [inputToken for _, inputToken in pairs],
        )

    def test_dot_source_is_byte_stable_across_rebuilds(self) -> None:
        def build():
            a: Automaton[object, object, object] = Automaton()
            a.addTransition("waiting", "submit", "working", ["start"])
            a.addTransition("working", "done", "done", ["finish"])
            a.addTransition("done", "reset", "waiting", [])
            return "".join(self._digraph(a))

        self.assertEqual(build(), build())

    def test_graphviz_order_with_colliding_keys(self) -> None:
        """
        The most dangerous order case: colliding hashes that permute set
        iteration.  DOT emission must still follow registration order.
        """
        states = [Colliding("state-{}".format(n), 0) for n in range(8)]
        inputs = [Colliding("in-{}".format(n), 0) for n in range(8)]
        a: Automaton[object, object, object] = Automaton()
        for state, inputToken in zip(states, inputs):
            a.addTransition(state, inputToken, "end", ())
        order = self._transitionLabelOrder(self._digraph(a))
        self.assertEqual(
            [name for name, _ in order],
            ["t{}".format(n) for n in range(8)],
        )
        self.assertEqual(
            [label for _, label in order],
            [inputToken.name for inputToken in inputs],
        )
