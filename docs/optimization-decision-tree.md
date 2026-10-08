# Build Optimization Decision Tree

How fast *can* and *should* your build be? Measure three numbers, work out how far
you are from optimal, then follow the tree. Optimize the build itself first (use the
cores you have, then lower the critical path). Caching comes last: once the build is
fast, make sure you do not pay the cost again, and that an optimization did not quietly
break reproducibility.

Two versions below. **Option A** is the canonical, slide-aligned procedure: every node
is a question, every branch is an answer, every answer points to a path. It is the one
to print and the one an agent follows. **Option B** is the same logic framed around the
"floor and levers" mental model, for the slide where we want a picture, not a checklist.

---

## The three numbers (measure first)

- **Wall time**: elapsed build time, the number you feel.
- **Critical path (CP)**: the longest chain of dependent actions. Measure at `--jobs=1`
  so contention does not inflate it. This is the **floor** of the current graph: no
  number of cores beats it.
- **Total work**: the sum of every action's duration, roughly the `--jobs=1` wall.

---

## How far from optimal (the math behind every branch)

From those three numbers, four derived quantities tell you where you stand. An agent
computes all four and reports them before proposing anything.

| Quantity | Formula | Reads as |
|---|---|---|
| Observed parallelism | total work / wall | "You are effectively using N cores." |
| Headroom factor | wall / CP | "You are this many times above your current floor." |
| Available parallelism | total work / CP | "Cores beyond roughly this count stop helping." |
| Current floor | CP | "Best wall reachable by scheduling alone, no code change." |

Two optimums, not one:

1. **Reachable now (money / parallelism):** with enough cores and no false
   serialization, wall approaches **CP**. The gap you can still close is `wall / CP`.
2. **Reachable with engineering (lower the floor):** CP itself drops once you shorten
   or split the actions sitting on it. This is the real "how fast it *can* be," and it
   is below today's CP.

The headroom factor is a quick estimate; the **`--jobs` sweep** (run `1, 2, 4, 8, ...`
and plot wall) is the proof. Where the curve flattens is the knee: that is how many
cores actually help, and if wall stops falling well above CP you have false
serialization, not a core shortage.

---

## Option A: the canonical, slide-aligned tree

Each decision node is the question shown on its slide. Follow it top to bottom.

```mermaid
flowchart TD
    S(["Measure: wall, critical path (CP at --jobs=1), total work"]) --> Q1{"Q1. Are you using the cores you already have?<br/>peak concurrency vs cores; wall vs CP"}

    Q1 -->|"Cores sit idle: peak less than cores, wall above CP"| A1["Raise --jobs; remove false serialization<br/>(free: spend the cores you own)"]
    Q1 -->|"Cores are saturated"| Q2{"Q2. Would more cores help?<br/>available parallelism = total work / CP, vs cores"}
    A1 --> Q2

    Q2 -->|"Yes: available parallelism above cores and wall still above CP"| A2["Add cores or remote execution,<br/>up to the --jobs sweep knee (money)"]
    Q2 -->|"No: wall already near CP"| Q34{"Q3 and Q4. You are at the floor (wall near CP).<br/>What sits on the critical path?"}
    A2 --> Q34

    Q34 -->|"Long serial chain"| E1["Break false deps (query somepath);<br/>parallelize stages; header / interface jars"]
    Q34 -->|"Fan-out chokepoint on the path"| E2["Split it; extract a thin, stable API"]
    Q34 -->|"One heavy action, real execution"| E3["Split the target; shard if a test;<br/>faster toolchain; shrink inputs"]
    Q34 -->|"Overhead: fetch, queue, upload"| E4["CAS locality; warm / persistent workers;<br/>smaller inputs and images"]

    E1 --> Q5{"Q5. Are you redoing work that never changed?<br/>no-op rebuild; shared-cache reuse"}
    E2 --> Q5
    E3 --> Q5
    E4 --> Q5

    Q5 -->|"Work re-runs with no real change"| C1["Make actions hermetic: no timestamps,<br/>abs paths or env; pin toolchains; sort globs"]
    Q5 -->|"One core lib invalidates everything"| C2["Stabilize high-fan-out nodes;<br/>split volatile from stable API"]
    Q5 -.->|"Guardrail after every fix above"| G["Confirm you got faster without<br/>introducing new cache misses"]

    classDef money fill:#e8f0fe,stroke:#1a73e8,color:#000;
    classDef eng fill:#e6f4ea,stroke:#34a853,color:#000;
    classDef cache fill:#fff4e5,stroke:#f29900,color:#000;
    class A1,A2 money;
    class E1,E2,E3,E4 eng;
    class C1,C2,G cache;
```

Color key: **blue = parallelism (money, "how fast it should be"), green = lower the
floor (engineering, "how fast it can be"), orange = caching (the epilogue).**

### The five questions, as slides

| # | Question on the slide | If the answer is... | Path |
|---|---|---|---|
| Q1 | Are you using the cores you already have? | cores idle | raise `--jobs`, kill false serialization (free) |
| Q2 | Would more cores help? | available parallelism > cores | add cores / remote execution (money) |
| Q3+Q4 | What sits on the critical path? | chain / chokepoint / heavy action / overhead | the matching engineering move |
| Q5 | Are you redoing work that never changed? | re-runs with no change | hermeticity, stabilize high-fan-out |
| all | After each fix, did a no-op rebuild stay clean? | new cache misses | undo the non-determinism you introduced |

---

## Option B: the floor-and-levers framing (creative)

Same logic, told as a picture: there is a floor (CP), you close the gap to it with
money, you lower it with engineering, and caching keeps you from paying twice.

```mermaid
flowchart TD
    S(["Measure: wall, critical path (CP), total work"]) --> Q{"Does your build still have parallelism headroom?"}

    Q -->|"wall time > 2x CP: parallelism headroom"| P{"--jobs sweep:<br/>cores idle or saturated?"}
    Q -->|"wall near CP"| F{"What is on the critical path?"}

    P -->|"Idle (peak below cores)"| PA["Raise --jobs;<br/>kill false serialization"]
    P -->|"Saturated"| PB["Add cores or remote execution<br/>(up to the --jobs sweep knee)"]

    F -->|"Long serial chain"| E1["Break false deps (query somepath);<br/>parallelize stages; header / interface jars"]
    F -->|"Fan-out chokepoint on path"| E2["Split it; extract a thin stable API"]
    F -->|"Heavy single action (execution)"| E3["Split target; shard if a test;<br/>faster toolchain; shrink inputs"]
    F -->|"Overhead (fetch / queue / upload)"| E4["CAS locality; warm / persistent workers;<br/>smaller inputs and images"]

    PA --> DONE(["Build optimized: now keep it fast and reusable"])
    PB --> DONE
    E1 --> DONE
    E2 --> DONE
    E3 --> DONE
    E4 --> DONE

    DONE --> C{"CACHING: do not pay this cost again<br/>(across rebuilds, machines, CI)"}
    C -->|"Work re-runs with no change"| C1["Make actions hermetic:<br/>no timestamps, abs paths or env;<br/>pin toolchains; sort globs"]
    C -->|"One core lib invalidates everything"| C2["Stabilize high-fan-out nodes;<br/>split volatile from stable API"]
    DONE -.->|"Guardrail: did an optimization<br/>introduce non-determinism?"| C

    classDef money fill:#e8f0fe,stroke:#1a73e8,color:#000;
    classDef eng fill:#e6f4ea,stroke:#34a853,color:#000;
    classDef cache fill:#fff4e5,stroke:#f29900,color:#000;
    class PA,PB money;
    class E1,E2,E3,E4 eng;
    class C1,C2 cache;
```

---

## Operationalizing for an agent

The decision tree is a procedure, so an agent can run it. Given a (clean) build, the
agent gathers the inputs, computes the four quantities, states how far the build is
from optimal, and ranks proposals.

**Gather:**
- wall (normal build), CP (`--profile` critical path, confirmed at `--jobs=1`),
  total work (sum of action durations, or the `--jobs=1` wall), core count.
- a `--jobs` sweep (`1, 2, 4, 8, ...`) to locate the knee.
- top on-CP actions (slowest actions that also sit on the critical path), each tagged
  execution vs overhead.
- a no-op rebuild to check cache reuse.

**Compute and state the gap:**
- "Observed parallelism is total work / wall = N cores in use."
- "Headroom factor is wall / CP = X. You are X times above your current floor."
- "Available parallelism is total work / CP = P. Cores beyond about P stop helping;
  the sweep knee confirms it at K cores."
- "Current floor is CP. With cores up to the knee and no false serialization, wall
  reaches about CP: a reachable-now speedup of X times."
- "The top on-CP actions account for Y of CP. Splitting / shortening them lowers the
  floor to about CP minus Y: that is how fast it can be."

**Propose, ranked by cost then impact:**
1. Parallelism (cheap or free): raise `--jobs`, remove false serialization; then add
   cores up to the knee.
2. Lower the floor (engineering): the matching move for each top on-CP action.
3. Caching (epilogue + guardrail): fix any non-determinism found in the no-op rebuild,
   stabilize high-fan-out nodes, and re-verify after every change above.

The output format matches the slides: for each proposal, show the result/status it
addresses, the money column, and the engineering column.

---

## Inner loop vs outer loop (framing, not a branch)

Same tree either way; the loop sets which metric you chase.

- **Inner loop:** a developer's local edit, build, test cycle. Optimize **latency**.
- **Outer loop:** CI and shared builds, often with a high remote-cache hit rate.
  Optimize **throughput and cost**; the caching epilogue matters most here, because a
  warm shared cache is what makes CI pay only for what changed.

A cold build (empty cache) is the rarer third case where the floor and parallelism
analysis dominates everything.
