# Changelog

## Unreleased

### Automat: indexed transition lookup with preserved output order

#### Implementation choices

- `Automaton._transitions` is now a `dict` keyed by `(inState, inputSymbol)`
  instead of a `set` of transition tuples. Registration (`addTransition`) and
  runtime lookup (`outputForInput`) are O(1) dictionary operations; the
  previous linear scans made machine construction O(n²) in the number of
  transitions and every runtime transition O(n).
- A secondary index, `Automaton._outgoingTransitions`, maps each state to the
  `(inState, inputSymbol)` keys of its outgoing edges, in first-registration
  order. It backs the new `Automaton.transitionsFrom(state)` accessor.
- Python dicts preserve insertion order, so **first-registration order is the
  canonical iteration order**. No global sort is applied anywhere: sorting
  would only *mask* ordering bugs by replacing the meaningful order
  (registration) with an arbitrary one (lexicographic).
- New read-only accessors:
  - `Automaton.transitions()` — all transitions as 4-tuples, in
    first-registration order.
  - `Automaton.transitionsFrom(state)` — `(input, outState, outputs)` triples
    for one state's outgoing edges, in first-registration order.
- `allTransitions()` still returns a `frozenset` (its historical type); the
  ordered view lives in `transitions()`.
- `makeDigraph` (`automat._visualize`) now iterates `automaton.transitions()`
  and derives state-node order from first appearance in the registered
  transitions. Previously it iterated `allTransitions()`/`states()`, whose
  `frozenset` iteration order is hash-dependent, so Graphviz output was
  nondeterministic across processes. It is now byte-identical across rebuilds.
- The duplicate-registration `ValueError` message is byte-for-byte unchanged
  and still names the *first* registered target state; the duplicate check
  still runs before output validation, so a duplicate key with invalid
  outputs raises `ValueError`, not `TypeError`.

#### Gaps in the original coverage

- `test_core.py` carried a `FIXME: addTransition for transition that's been
  added before` — duplicate registration and its exact message were untested.
- Nothing pinned iteration order: the `set`-based store made
  `allTransitions()`/Graphviz ordering hash-dependent, so no test could rely
  on it (and none did).
- Output-action failure semantics (the machine has already transitioned when
  an output raises) were untested.
- Result ownership was untested: `outputForInput` returns a fresh `list` each
  call, and `allTransitions()` is a snapshot; callers mutating results must
  not corrupt the automaton.
- The `unhandledTransition` fallback's return shape (outputs stay a `tuple`,
  unlike the `list` returned for known transitions) was only incidentally
  covered.

#### Regression protection for adjacent semantics

`src/automat/_test/test_indexed_transitions.py` locks the contract with a
shared test suite that exercises the indexed `Automaton` and a deliberately
naive list-based `ReferenceAutomaton` side by side, for both dense
(25 states × 16 inputs) and sparse (400 states × 1 input) machines:

- duplicate transition: exact historical message, first-registered target
  named, duplicate check prioritized over output validation;
- invalid outputs leave no partial registration behind;
- terminal states raise `NoTransition` carrying `.state`/`.symbol`;
- self-loops repeat identically; `unhandledTransition` fallback shape
  preserved (tuple outputs, known transitions still win);
- ownership: returned output lists are copies, `allTransitions()` is a
  snapshot;
- `MethodicalMachine`: an output action that raises still leaves the machine
  in its new state, and duplicate `upon` registration keeps the `ValueError`;
- Graphviz: transition and state nodes appear in first-registration order
  and output is byte-identical across rebuilds.

`benchmark/test_indexed_transitions.py` benchmarks build and lookup for both
dense (60×60) and sparse (3600×1) machines
(`pytest --benchmark-only benchmark/`).

#### The most dangerous counterexample for FSM / transition indexing / deterministic order

A machine whose transitions are registered in an order that is **neither
sorted nor reverse-sorted** (the tests interleave input numbering and use
`mike`/`zulu`/`alpha` orderings). Against such data, an implementation that
"achieves determinism" by globally sorting — or one that leaks hash
iteration order, which can coincidentally look sorted for small machines —
produces output that is deterministic-looking but *wrong*: Graphviz edge
order drifts from registration order, and the duplicate-registration error
can name the wrong target state. This is the failure mode most likely to
ship silently, because sorted-order test data cannot detect it.

Regression tests: `OrderingContractTests::test_transitionsAreInRegistrationOrder`
and `GraphvizOrderContractTests::test_graphvizTransitionOrderIsRegistrationOrder`
explicitly assert that the registration order in the fixture differs from
both sorted and reverse-sorted order before asserting on output positions, so
a global-sort implementation fails the test rather than passing by
coincidence; `RegistrationErrorContractTests::test_duplicateTransitionMessage`
pins the first-registered target in the error text.
