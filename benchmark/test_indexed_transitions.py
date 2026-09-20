"""
Benchmarks for Automat's indexed transition storage.

Covers both ends of the density spectrum:

- dense machines: few states, many inputs per state (the (state, input)
  index dominates),
- sparse machines: many states, one input each (the per-state outgoing
  edge index dominates).

Run with: pytest --benchmark-only benchmark/
"""

from automat._core import Automaton, Transitioner


def buildAutomaton(stateCount, inputsPerState):
    automaton = Automaton("state-0")
    for state in range(stateCount):
        for rawInput in range(inputsPerState):
            inputNumber = (rawInput * 7 + 3) % inputsPerState
            automaton.addTransition(
                "state-{}".format(state),
                "input-{}".format(inputNumber),
                "state-{}".format((state + inputNumber + 1) % stateCount),
                ("out-{}-{}".format(state, inputNumber),),
            )
    return automaton


DENSE_STATES, DENSE_INPUTS = 60, 60
SPARSE_STATES, SPARSE_INPUTS = 3600, 1


def test_build_dense(benchmark):
    benchmark(buildAutomaton, DENSE_STATES, DENSE_INPUTS)


def test_lookup_dense(benchmark):
    automaton = buildAutomaton(DENSE_STATES, DENSE_INPUTS)
    transitioner = Transitioner(automaton, automaton.initialState)

    def look():
        for state in range(DENSE_STATES):
            for inputNumber in range(DENSE_INPUTS):
                automaton.outputForInput(
                    "state-{}".format(state), "input-{}".format(inputNumber)
                )
        # And a runtime walk through the machine.
        for inputNumber in range(DENSE_INPUTS):
            transitioner.transition("input-{}".format(inputNumber))

    benchmark(look)


def test_build_sparse(benchmark):
    benchmark(buildAutomaton, SPARSE_STATES, SPARSE_INPUTS)


def test_lookup_sparse(benchmark):
    automaton = buildAutomaton(SPARSE_STATES, SPARSE_INPUTS)

    def look():
        for state in range(SPARSE_STATES):
            automaton.outputForInput("state-{}".format(state), "input-0")
        automaton.transitionsFrom("state-{}".format(SPARSE_STATES // 2))

    benchmark(look)
