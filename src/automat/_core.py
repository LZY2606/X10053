# -*- test-case-name: automat._test.test_core -*-

"""
A core state-machine abstraction.

Perhaps something that could be replaced with or integrated into machinist.
"""
from __future__ import annotations

import sys
from typing import (
    Callable,
    Generic,
    Iterable,
    Optional,
    Sequence,
    TypeVar,
    Hashable,
)

if sys.version_info >= (3, 10):
    from typing import TypeAlias
else:
    from typing_extensions import TypeAlias

_NO_STATE = "<no state>"
State = TypeVar("State", bound=Hashable)
Input = TypeVar("Input", bound=Hashable)
Output = TypeVar("Output", bound=Hashable)


class NoTransition(Exception, Generic[State, Input]):
    """
    A finite state machine in C{state} has no transition for C{symbol}.

    @ivar state: See C{state} init parameter.

    @ivar symbol: See C{symbol} init parameter.
    """

    def __init__(self, state: State, symbol: Input):
        """
        Construct a L{NoTransition}.

        @param state: the finite state machine's state at the time of the
            illegal transition.

        @param symbol: the input symbol for which no transition exists.
        """
        self.state = state
        self.symbol = symbol
        super(Exception, self).__init__(
            "no transition for {} in {}".format(symbol, state)
        )


class Automaton(Generic[State, Input, Output]):
    """
    A declaration of a finite state machine.

    Note that this is not the machine itself; it is immutable.
    """

    def __init__(self, initial: State | None = None) -> None:
        """
        Initialize the transition indexes and the initial state.

        Transitions are kept in two coupled indexes:

            - C{self._byInput}: C{(in-state, input) -> (out-state, outputs)}
              for O(1) duplicate detection during construction and O(1)
              lookup at runtime, and
            - C{self._outgoing}: C{in-state -> {input -> (out-state,
              outputs)}} for enumeration of a state's outgoing edges.

        Both are ordinary C{dict}s, whose iteration order is the order in
        which keys were first inserted, so enumeration deterministically
        follows registration order without any sorting.  The flat
        C{set}-of-tuples storage used previously enumerated in hash order,
        which made conflict diagnostics and graph output sensitive to hash
        collisions and table growth, and made construction and lookup linear
        in the total number of transitions.
        """
        if initial is None:
            initial = _NO_STATE  # type:ignore[assignment]
        assert initial is not None
        self._initialState: State = initial
        self._byInput: dict[tuple[State, Input], tuple[State, Sequence[Output]]] = {}
        self._outgoing: dict[State, dict[Input, tuple[State, Sequence[Output]]]] = {}
        self._unhandledTransition: Optional[tuple[State, Sequence[Output]]] = None

    @property
    def initialState(self) -> State:
        """
        Return this automaton's initial state.
        """
        return self._initialState

    @initialState.setter
    def initialState(self, state: State) -> None:
        """
        Set this automaton's initial state.  Raises a ValueError if
        this automaton already has an initial state.
        """

        if self._initialState is not _NO_STATE:
            raise ValueError(
                "initial state already set to {}".format(self._initialState)
            )

        self._initialState = state

    def addTransition(
        self,
        inState: State,
        inputSymbol: Input,
        outState: State,
        outputSymbols: tuple[Output, ...],
    ):
        """
        Add the given transition to the outputSymbol. Raise ValueError if
        there is already a transition with the same inState and inputSymbol.
        """
        # Coerce the outputs first: the legacy implementation iterated
        # outputSymbols while scanning for duplicates, so a non-iterable
        # argument raised TypeError before the duplicate ValueError even
        # though the scan itself happened first.  Materializing the tuple
        # up front preserves that error priority and keeps storage immutable.
        storedOutputs: tuple[Output, ...] = tuple(outputSymbols)
        key = (inState, inputSymbol)
        existing = self._byInput.get(key)
        if existing is not None:
            (anOutState, _) = existing
            raise ValueError(
                "already have transition from {} to {} via {}".format(
                    inState, anOutState, inputSymbol
                )
            )
        value = (outState, storedOutputs)
        self._byInput[key] = value
        self._outgoing.setdefault(inState, {})[inputSymbol] = value

    def unhandledTransition(
        self, outState: State, outputSymbols: Sequence[Output]
    ) -> None:
        """
        All unhandled transitions will be handled by transitioning to the given
        error state and error-handling output symbols.
        """
        self._unhandledTransition = (outState, tuple(outputSymbols))

    def allTransitions(self) -> frozenset[tuple[State, Input, State, Sequence[Output]]]:
        """
        All transitions.

        The returned C{frozenset} preserves the historical set-based
        contract.  It cannot express an order; use
        L{transitionsInRegistrationOrder} for deterministic enumeration.
        """
        return frozenset(self._records())

    def _records(
        self,
    ) -> Iterable[tuple[State, Input, State, Sequence[Output]]]:
        """
        Every transition as a 4-tuple, in first-registration order.
        """
        for (inState, inputSymbol), (
            outState,
            outputSymbols,
        ) in self._byInput.items():
            yield (inState, inputSymbol, outState, outputSymbols)

    def transitionsInRegistrationOrder(
        self,
    ) -> tuple[tuple[State, Input, State, Sequence[Output]], ...]:
        """
        All transitions as a tuple of C{(in-state, input, out-state,
        outputs)} records, in the order in which they were first registered.

        Unlike L{allTransitions}, this preserves order for consumers (such as
        graph generation) that need deterministic, registration-ordered
        enumeration rather than set semantics.
        """
        return tuple(self._records())

    def inputAlphabet(self) -> set[Input]:
        """
        The full set of symbols acceptable to this automaton.
        """
        return {inputSymbol for (_, inputSymbol) in self._byInput}

    def outputAlphabet(self) -> set[Output]:
        """
        The full set of symbols which can be produced by this automaton.
        """
        return {
            outputSymbol
            for (_, outputSymbols) in self._byInput.values()
            for outputSymbol in outputSymbols
        }

    def states(self) -> frozenset[State]:
        """
        All valid states; "Q" in the mathematical description of a state
        machine.
        """
        states = set(self._outgoing)
        states.update(outState for (outState, _) in self._byInput.values())
        return frozenset(states)

    def outputsFromState(
        self, inState: State
    ) -> list[tuple[Input, State, Sequence[Output]]]:
        """
        All outgoing edges of C{inState} as C{(input, outState, outputs)}
        triples, in first-registration order.

        This is the state-keyed companion of L{allTransitions}; it returns an
        empty list for states that never originate a transition.
        """
        edges = self._outgoing.get(inState)
        if edges is None:
            return []
        return [
            (inputSymbol, outState, outputSymbols)
            for inputSymbol, (outState, outputSymbols) in edges.items()
        ]

    def outputForInput(
        self, inState: State, inputSymbol: Input
    ) -> tuple[State, Sequence[Output]]:
        """
        A 2-tuple of (outState, outputSymbols) for inputSymbol.
        """
        indexed = self._byInput.get((inState, inputSymbol))
        if indexed is not None:
            (outState, outputSymbols) = indexed
            return (outState, list(outputSymbols))
        if self._unhandledTransition is None:
            raise NoTransition(state=inState, symbol=inputSymbol)
        return self._unhandledTransition


OutputTracer = Callable[[Output], None]
Tracer: TypeAlias = "Callable[[State, Input, State], OutputTracer[Output] | None]"


class Transitioner(Generic[State, Input, Output]):
    """
    The combination of a current state and an L{Automaton}.
    """

    def __init__(self, automaton: Automaton[State, Input, Output], initialState: State):
        self._automaton: Automaton[State, Input, Output] = automaton
        self._state: State = initialState
        self._tracer: Tracer[State, Input, Output] | None = None

    def setTrace(self, tracer: Tracer[State, Input, Output] | None) -> None:
        self._tracer = tracer

    def transition(
        self, inputSymbol: Input
    ) -> tuple[Sequence[Output], OutputTracer[Output] | None]:
        """
        Transition between states, returning any outputs.
        """
        outState, outputSymbols = self._automaton.outputForInput(
            self._state, inputSymbol
        )
        outTracer = None
        if self._tracer:
            outTracer = self._tracer(self._state, inputSymbol, outState)
        self._state = outState
        return (outputSymbols, outTracer)
