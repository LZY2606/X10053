"""
A byte-for-byte copy of the pre-indexing L{Automat} transition storage.

This module exists solely so that the shared transition-lookup contract in
L{automat._test.test_transition_index} can be executed against two parallel
implementations:

    1. the legacy flat-C{set} implementation with linear scans, kept here as
       an immutable reference oracle, and
    2. the current L{automat._core.Automaton}.

Do not "fix" anything in this file.  It is the behavior baseline; changing it
defeats the purpose of the comparison.
"""

from __future__ import annotations

from itertools import chain
from typing import Optional, Sequence

_NO_STATE = "<no state>"


class NoTransition(Exception):
    def __init__(self, state, symbol):
        self.state = state
        self.symbol = symbol
        super(Exception, self).__init__(
            "no transition for {} in {}".format(symbol, state)
        )


class LegacyAutomaton:
    """
    Exact copy of L{automat._core.Automaton}'s storage and lookup code prior
    to the indexing refactor.
    """

    def __init__(self, initial=None):
        if initial is None:
            initial = _NO_STATE
        self._initialState = initial
        self._transitions = set()
        self._unhandledTransition = None

    @property
    def initialState(self):
        return self._initialState

    @initialState.setter
    def initialState(self, state):
        if self._initialState is not _NO_STATE:
            raise ValueError(
                "initial state already set to {}".format(self._initialState)
            )
        self._initialState = state

    def addTransition(self, inState, inputSymbol, outState, outputSymbols):
        for anInState, anInputSymbol, anOutState, _ in self._transitions:
            if anInState == inState and anInputSymbol == inputSymbol:
                raise ValueError(
                    "already have transition from {} to {} via {}".format(
                        inState, anOutState, inputSymbol
                    )
                )
        self._transitions.add((inState, inputSymbol, outState, tuple(outputSymbols)))

    def unhandledTransition(self, outState, outputSymbols):
        self._unhandledTransition = (outState, tuple(outputSymbols))

    def allTransitions(self):
        return frozenset(self._transitions)

    def inputAlphabet(self):
        return {
            inputSymbol
            for (inState, inputSymbol, outState, outputSymbol) in self._transitions
        }

    def outputAlphabet(self):
        return set(
            chain.from_iterable(
                outputSymbols
                for (inState, inputSymbol, outState, outputSymbols) in self._transitions
            )
        )

    def states(self):
        return frozenset(
            chain.from_iterable(
                (inState, outState)
                for (inState, inputSymbol, outState, outputSymbols) in self._transitions
            )
        )

    def outputForInput(self, inState, inputSymbol):
        for anInState, anInputSymbol, outState, outputSymbols in self._transitions:
            if (inState, inputSymbol) == (anInState, anInputSymbol):
                return (outState, list(outputSymbols))
        if self._unhandledTransition is None:
            raise NoTransition(state=inState, symbol=inputSymbol)
        return self._unhandledTransition
