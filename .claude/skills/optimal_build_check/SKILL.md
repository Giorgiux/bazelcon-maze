---
name: optimal_build_check
description: >-
  Measures how fast a Bazel build is versus how fast it could be, then explains
  the gap. Runs a fixed 5-build experiment (a --jobs sweep plus a no-op rebuild),
  collects profiles and the execution log, answers the five build-performance
  questions, and proposes concrete speedups or confirms the build is near optimal.
  Use when someone asks how fast their build should/could be, why a build is slow,
  whether more cores would help, or whether work is being redone. Local builds by
  default; extensible to remote execution by passing --config flags.
---

# optimal_build_check

A self-contained build-performance diagnosis. It runs the experiment, does the
math, and answers five questions, each with the command to reproduce it by hand.

## When to use

- "How fast should / could this build be?"
- "Why is my build slow?" / "Would more cores (or remote execution) help?"
- "Am I redoing work that never changed?"
- Any request to optimize or audit a Bazel build's speed.

## How to run it

1. **Confirm the target and warn about cost.** Default is `//...`. Tell the user
   this runs **5 builds** and calls `bazel clean` between the timed ones, which
   wipes build outputs (safe, just not instant). Ask before pointing it at a huge
   repo; suggest `--quick` (3 builds) there.

2. **Collect.** From the repo root:

   ```
   bash .claude/skills/optimal_build_check/scripts/collect.sh [TARGET] [--quick] [-- EXTRA_BAZEL_FLAGS]
   ```

   For remote execution, pass the configs after `--`, e.g.
   `-- --config=remote --config=remote_debian12_x64`. The script prints the run
   directory on its last line.

3. **Analyze.**

   ```
   python3 .claude/skills/optimal_build_check/scripts/analyze.py <run_dir>
   ```

   This writes `<run_dir>/report.json` and prints a summary.

## How to present the result

Read `report.json` and give the user, in this order:

1. **The three numbers**: wall, critical path (the floor), total work.
2. **How far from optimal**: the headroom factor (`wall / critical path`, "you are
   Nx above your floor"), the reachable-now target (approach the critical path with
   cores up to the sweep knee), and the deeper engineering floor (the critical path
   minus the on-path actions you could shorten).
3. **The five answers** (from `report.json.answers`), each as a verdict:
   - Q1 using the cores you have (`cores_idle`)
   - Q2 would more cores help (`more_cores_help`, `sweep_knee_jobs`)
   - Q3 execution vs overhead (`execution_share`)
   - Q4 nodes holding up everything, two axes: `heaviest_on_path` (dominates
     critical-path TIME, usually a heavy leaf -> split / shard / shrink) and
     `highest_fanout` (dominates INVALIDATION / blast radius, a high-rdeps node ->
     split, extract a thin stable API). These are often different targets; name
     both. If the top fan-out node is also non-hermetic (see Q5), call out the
     cascade: it both gates everything and re-runs on every build.
   - Q5 redoing unchanged work (`hermetic`, `noop_reexecuted_actions`)
4. **Ranked proposals**, cheapest first, following `reference/decision-tree.md`:
   parallelism (free, then paid) before engineering (lower the floor) before the
   caching guardrail. If the build is already at the floor, the no-op is clean, and
   cores are well used, **say it is near optimal** and stop.

## Let the user verify any answer

Every question in `report.json` carries a `verify` list: the exact commands to
reproduce that answer without the skill. When the user doubts a result or wants to
see it live, run or print those commands. This is the point of the skill: it shows
its work.

## Extending to remote execution

Pass remote configs after `--`. The execution-vs-overhead split (Q3) becomes the
interesting part remotely, since queue, upload, download, and fetch times (near
zero locally) show up in the execution log's SpawnMetrics.

## Notes

- Headline wall and critical path come from Bazel's own `Elapsed time / Critical
  Path` line, per sweep point. Critical path is cleanest at `--jobs=1` (no
  contention), which is why that run is the reference.
- `available_parallelism = total work / critical path` is the average; the
  `--jobs` sweep knee is the empirical confirmation of how many cores help.
- The profile parse (slowest actions, on-critical-path, peak concurrency) is
  best-effort across Bazel versions; the headline numbers do not depend on it.
