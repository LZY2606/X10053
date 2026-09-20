# Changelog

## Unreleased

### Indexed transition lookup with stable output order

`Automaton` previously stored every declared transition as a record in one
flat `set` of `(in-state, input, out-state, outputs)` tuples.  Both
construction-time duplicate detection (`addTransition`) and runtime lookup
(`outputForInput`) linearly scanned that set, so building a machine with *N*
transitions was O(N²) and every dispatched input was O(N).  Set enumeration
also follows hash-table layout rather than registration order, so the
synthetic `t0, t1, ...` nodes emitted by `makeDigraph` were silently reordered
whenever keys collided or the table grew.

#### Implementation choices

- Two coupled indexes replace the flat set (`src/automat/_core.py`):
  - `_byInput`: `(in-state, input) -> (out-state, outputs)`, giving O(1)
    duplicate detection on build and O(1) dispatch at runtime.
  - `_outgoing`: `in-state -> {input -> (out-state, outputs)}`, the
    state-keyed outgoing-edge index, exposed read-only via the new
    `Automaton.outputsFromState(state)` helper.
- Both indexes are plain `dict`s, so key iteration is exactly first-insertion
    order.  Order is therefore **determined by registration order**, not by
    sorting; nothing sorts states, inputs, or transitions.  A rejected
    duplicate never inserts or re-keys anything.
- `allTransitions()` still returns a `frozenset` with identical membership
    semantics.  Ordered enumeration is offered separately as
    `transitionsInRegistrationOrder()` (a tuple), which `_visualize.makeDigraph`
    now consumes, so Graphviz `tN` numbering follows declaration order.
- Exception text is byte-identical: duplicates still raise
    `ValueError("already have transition from {in} to {first out} via {input}")`
    (reporting the *first* registration's destination), missing inputs still
    raise `NoTransition("no transition for {input} in {state}")`, and the
    initial-state setter text is unchanged.
- Error priority is preserved: `tuple(outputSymbols)` is materialized before
    the duplicate check, mirroring the old code's incidental iteration, so a
    non-iterable output argument raises `TypeError` before a duplicate
    `ValueError`, and a failed registration mutates no index or alphabet.
- Returned ownership is preserved: `outputForInput` returns a fresh `list`
    of outputs per call; stored outputs are immutable tuples.  The
    unhandled-transition fallback path and its return value are untouched.

#### Tests and contract

- `src/automat/_test/_legacy_core.py` vendors the pre-refactor flat-set
    implementation as an immutable reference oracle.
- `src/automat/_test/test_transition_index.py` runs one shared behavioral
    contract against **both** implementations (`IndexedContract` /
    `LegacyContract`): lookup, alphabets, duplicate text and first-destination
    reporting, equality-vs-identity of keys, hash-colliding keys, self-loops,
    terminal/dead-end states, output ownership, failure atomicity, and error
    priority.  Dense and sparse machine shapes are checked for value equality
    against the oracle as well.
- Indexed-only regressions pin the new guarantees: first-registration
    enumeration (including a deliberately reverse-ordered case proving no
    global sorting is hiding differences), survival of 2000-insert table
    growth and fully-colliding hashes, the outgoing-edge partition, and
    `__eq__`-counting complexity caps that mechanically fail if
    `addTransition`/`outputForInput` ever regress to linear scans (no timing,
    no sleeps).  Graphviz tests assert `tN` numbering equals declaration
    order, including with colliding keys, and byte-stable DOT across rebuilds.
- `src/automat/_test/test_adjacent_semantics.py` guards neighboring
    semantics the refactor could disturb: output-action exceptions propagate
    *after* the state has moved and suppress later outputs in the same
    transition; terminal states keep their diagnostic context; self-loops
    survive in the outgoing index; and the methodical-layer duplicate error
    keeps naming the first destination.
- `benchmark/test_dense_sparse.py` benchmarks dense (50 states x 50 inputs)
    and sparse (2500 single-edge states) machines for both implementations;
    on the development machine build is roughly 50-65x faster and lookup
    roughly 140-200x faster than the linear scan.

#### Coverage gaps the new tests close

- No test previously asserted *which* destination the duplicate error
    reported, that duplicate registration was atomic (outputs from the
    rejected call leaking into the alphabet), or that the returned output
    list is private per-call storage.
- Enumeration order and Graphviz node numbering were untested; the flat set's
    hash-order output was effectively accepted by accident.
- Self-loops and terminal states had no core-level coverage of index
    membership (`states()`, outgoing edges).
- Output-action failure had no test proving the transition commits before
    outputs run and that later outputs are skipped after a raise.

#### Finite-state machine / transition index / deterministic order:
#### most dangerous counter-example and its regression test

The most dangerous case is **many transition keys whose hashes collide or
whose table is forced through repeated resizing**.  With the old set storage
this simultaneously (a) hid quadratic build cost on "normal-looking" dense
machines, and (b) permuted enumeration order — the duplicate diagnostic could
name the wrong destination in pathological layouts, and Graphviz `tN` nodes
were laid out in hash order, so two machines declared in the same order could
render differently across processes/insertion patterns.  A "fix" that simply
sorted everything would make output stable but would no longer reflect
declaration order, and a single dict without the state outgoing partition
would still require a scan for per-state tools.

The direct regressions are:
- `RegistrationOrderTests.test_order_survives_hash_collisions` and
    `GraphvizOrderTests.test_graphviz_order_with_colliding_keys`
    (fully-colliding keys must enumerate and render in registration order);
- `RegistrationOrderTests.test_order_survives_set_growth` (2000 inserts,
    no reordering);
- `RegistrationOrderTests.test_order_is_not_global_sort` (reverse
    registration survives, ruling out sorting as the source of stability);
- `IndexComplexityTests.test_duplicateCheck_is_indexed_on_build` and
    `test_outputForInput_is_indexed_at_runtime` (equality-comparison caps
    that fail on any linear scan);
- `RegistrationOrderTests.test_duplicate_does_not_reorder_or_renew` and
    the shared `test_duplicate_error_names_first_outState`
    (first-registration ownership of diagnostics and ordering).
