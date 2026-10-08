# Decision logic for optimal_build_check

The procedure the skill follows when turning `report.json` into proposals. Rank
proposals cheapest first: use the cores you own, then buy cores, then do
engineering, then protect caching.

## Order of operations

1. **Measure** (collect.sh): wall, critical path (floor, at `--jobs=1`), total
   work, the `--jobs` sweep, slowest actions, execution vs overhead, no-op rebuild.

2. **Are you at the floor?** Compare wall to the critical path.
   - wall still above the critical path -> parallelism headroom (money lever).
   - wall near the critical path -> at the floor, only engineering lowers it.

3. **Parallelism (money, "how fast it should be"):**
   - Cores idle (observed parallelism well below core count, wall above floor)
     -> raise `--jobs`, remove false serialization. Free.
   - Cores saturated but available parallelism (total work / critical path) still
     above core count -> add cores or remote execution, up to the sweep knee.

4. **Lower the floor (engineering, "how fast it can be"):** look at what sits on
   the critical path. "Holding up everything" has two distinct meanings; check both:
   - **By TIME** (the heaviest action on the critical path). Usually a heavy leaf.
     - Long serial chain -> break false deps (`bazel query somepath`), parallelize
       stages, use header / interface jars.
     - One heavy action (real execution) -> split the target, shard if a test, use
       a faster toolchain, shrink inputs.
     - Overhead (fetch / queue / upload) -> CAS locality, warm or persistent
       workers, smaller inputs and images.
   - **By FAN-OUT / blast radius** (the node with the most transitive rdeps). It may
     be cheap to build yet gate everything, so it rarely appears in a slowest-action
     list. Measured with `bazel query 'rdeps(//..., <node>)'`.
     - Fan-out chokepoint -> split it, extract a thin stable API, move volatile parts
       to a leaf. If this node is also non-hermetic (step 5), it both gates and
       re-runs everything: fix that first.

5. **Caching (epilogue + guardrail):**
   - No-op rebuild re-runs work -> non-hermetic input: drop timestamps, absolute
     paths, and env; pin toolchains; sort globs.
   - One core library invalidates everything -> stabilize high-fan-out nodes, split
     volatile from stable API.
   - After every fix above, re-run the no-op: confirm you got faster without
     introducing new cache misses.

## Near-optimal stop condition

If wall is near the critical path, the sweep shows cores are well used (knee at or
below core count with little idle headroom), and the no-op rebuild re-runs nothing,
report that the build is near optimal for the current graph and stop. The only
further gains would come from lowering the critical path itself (engineering),
which may not be worth it.
