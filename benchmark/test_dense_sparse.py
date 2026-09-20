"""
Dense vs. sparse transition lookup benchmarks.

These exercise the two index shapes that matter for transition lookup:

- dense: many states, each with many outgoing inputs (stresses the
  per-(state, input) index and duplicate detection during construction), and
- sparse: many states with a single outgoing edge each (stresses the
  runtime lookup path across many distinct state keys).

The legacy flat-set implementation (importable as L{LegacyAutomaton} from the
test package) is benchmarked alongside the current implementation so the
indexing win is visible in the benchmark output rather than assumed.
"""

from __future__ import annotations

from automat._core import Automaton
from automat._test._legacy_core import LegacyAutomaton

DENSE_STATES = 50
DENSE_INPUTS = 50
SPARSE_STATES = 2500


def _build(cls, dense):
    automaton = cls("s0")
    if dense:
        for stateIndex in range(DENSE_STATES):
            inState = "s{}".format(stateIndex)
            for inputIndex in range(DENSE_INPUTS):
                automaton.addTransition(
                    inState,
                    "i{}".format(inputIndex),
                    "s{}".format((stateIndex + inputIndex + 1) % DENSE_STATES),
                    ("o{}-{}".format(stateIndex, inputIndex),),
                )
    else:
        for stateIndex in range(SPARSE_STATES):
            inState = "s{}".format(stateIndex)
            automaton.addTransition(
                inState,
                "i",
                "s{}".format((stateIndex + 1) % SPARSE_STATES),
                ("o",),
            )
    return automaton


def _lookupLoop(automaton, dense, rounds):
    if dense:
        for n in range(rounds):
            state = "s{}".format(n % DENSE_STATES)
            inputSymbol = "i{}".format(n % DENSE_INPUTS)
            automaton.outputForInput(state, inputSymbol)
    else:
        for n in range(rounds):
            automaton.outputForInput("s{}".format(n % SPARSE_STATES), "i")


# -- construction -----------------------------------------------------------


def test_build_dense_indexed(benchmark):
    benchmark(_build, Automaton, True)


def test_build_dense_legacy(benchmark):
    benchmark(_build, LegacyAutomaton, True)


def test_build_sparse_indexed(benchmark):
    benchmark(_build, Automaton, False)


def test_build_sparse_legacy(benchmark):
    benchmark(_build, LegacyAutomaton, False)


# -- runtime lookup ---------------------------------------------------------


def test_lookup_dense_indexed(benchmark):
    automaton = _build(Automaton, True)
    benchmark(_lookupLoop, automaton, True, 2000)


def test_lookup_dense_legacy(benchmark):
    automaton = _build(LegacyAutomaton, True)
    benchmark(_lookupLoop, automaton, True, 2000)


def test_lookup_sparse_indexed(benchmark):
    automaton = _build(Automaton, False)
    benchmark(_lookupLoop, automaton, False, 2000)


def test_lookup_sparse_legacy(benchmark):
    automaton = _build(LegacyAutomaton, False)
    benchmark(_lookupLoop, automaton, False, 2000)
