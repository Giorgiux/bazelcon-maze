#!/usr/bin/env python3
"""optimal_build_check: analyze phase.

Reads a run directory produced by collect.sh and turns it into report.json plus
a human-readable summary. All headline numbers come from Bazel's own output
(wall and critical path per sweep point); the profile and execution log add the
slowest-action, on-critical-path, and execution-vs-overhead detail.

The script computes the four derived quantities (observed parallelism, headroom
factor, available parallelism, current floor), answers the five questions, and
attaches the exact command to reproduce each answer by hand.
"""
import sys
import os
import re
import json
import gzip


def read_json_maybe_gz(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def load_meta(run_dir):
    with open(os.path.join(run_dir, "meta.json")) as f:
        return json.load(f)


def load_sweep(run_dir):
    rows = []
    path = os.path.join(run_dir, "sweep.csv")
    with open(path) as f:
        next(f, None)  # header
        for line in f:
            line = line.strip()
            if not line:
                continue
            jobs, wall, cp = line.split(",")
            rows.append({
                "jobs": int(jobs),
                "wall": None if wall == "NA" else float(wall),
                "cp": None if cp == "NA" else float(cp),
            })
    rows.sort(key=lambda r: r["jobs"])
    return rows


def dur_to_s(v):
    """SpawnMetrics durations are proto3 JSON: strings like '1.234s' or dicts."""
    if v is None:
        return 0.0
    if isinstance(v, str):
        m = re.match(r"([0-9.]+)s?", v)
        return float(m.group(1)) if m else 0.0
    if isinstance(v, dict):
        return float(v.get("seconds", 0)) + float(v.get("nanos", 0)) / 1e9
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def parse_exec_log(path):
    """The json execution log is a stream of concatenated JSON objects."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = f.read()
    dec = json.JSONDecoder()
    i, n, out = 0, len(data), []
    while i < n:
        while i < n and data[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        try:
            obj, end = dec.raw_decode(data, i)
        except ValueError:
            break
        out.append(obj)
        i = end
    return out


def bare_action_name(name):
    """Critical-path events name actions as "action '<desc>'" while
    action-processing events use the bare "<desc>". Normalize to the bare form
    so the two can be compared."""
    m = re.match(r"^action '(.*)'$", name)
    return m.group(1) if m else name


def parse_profile(path):
    """Returns (critical_path_names, actions, peak_concurrency)."""
    crit_names, actions, peak = set(), [], 0
    if not os.path.exists(path):
        return crit_names, actions, peak
    try:
        data = read_json_maybe_gz(path)
    except Exception:
        return crit_names, actions, peak
    events = data.get("traceEvents", [])
    tid_name = {}
    for e in events:
        if e.get("ph") == "M" and e.get("name") == "thread_name":
            tid_name[(e.get("pid"), e.get("tid"))] = e.get("args", {}).get("name", "")
    skip_cats = {"build phase marker", "general information", "thread_name"}
    for e in events:
        ph = e.get("ph")
        tname = tid_name.get((e.get("pid"), e.get("tid")), "")
        if ph == "X":
            name = e.get("name", "")
            dur = e.get("dur", 0) / 1e6  # microseconds -> seconds
            if tname == "Critical Path":
                crit_names.add(bare_action_name(name))
            else:
                cat = e.get("cat", "")
                if cat not in skip_cats and dur > 0:
                    actions.append({"name": name, "dur": dur, "cat": cat})
        elif ph == "C":
            nm = e.get("name", "").lower()
            if "action" in nm:
                vals = e.get("args", {})
                tot = sum(float(x) for x in vals.values() if isinstance(x, (int, float)))
                peak = max(peak, tot)
    return crit_names, actions, peak


def noop_reexec_count(run_dir):
    explain = os.path.join(run_dir, "explain.txt")
    noop = os.path.join(run_dir, "noop.log")
    count, reasons = 0, []
    if os.path.exists(explain):
        with open(explain, errors="ignore") as f:
            for line in f:
                if line.startswith("Executing action"):
                    count += 1
                    if len(reasons) < 5:
                        reasons.append(line.strip())
    processes_line = ""
    if os.path.exists(noop):
        with open(noop, errors="ignore") as f:
            for line in f:
                if re.search(r"\bprocess(es)?:", line):
                    processes_line = line.strip()
    return count, reasons, processes_line


def load_graph(run_dir):
    """Returns (rule_targets, forward_adjacency) where forward[A] = deps of A."""
    rules = set()
    rp = os.path.join(run_dir, "rules.txt")
    if os.path.exists(rp):
        with open(rp, errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("//"):
                    rules.add(line)
    fwd = {}
    gp = os.path.join(run_dir, "graph.dot")
    edge = re.compile(r'"([^"]+)"\s*->\s*"([^"]+)"')
    if os.path.exists(gp):
        with open(gp, errors="ignore") as f:
            for line in f:
                m = edge.search(line)
                if m:
                    fwd.setdefault(m.group(1), set()).add(m.group(2))
    return rules, fwd


def compute_fanout(rules, fwd):
    """Fan-out of X = number of rule targets that transitively depend on X."""
    rev = {}
    for a, bs in fwd.items():
        for b in bs:
            rev.setdefault(b, set()).add(a)
    out = []
    for x in rules:
        seen, stack = set(), [x]
        while stack:
            n = stack.pop()
            for p in rev.get(n, ()):  # p depends on n
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        out.append({"label": x, "fanout": sum(1 for s in seen if s in rules)})
    out.sort(key=lambda d: d["fanout"], reverse=True)
    return out


def pick(rows, jobs):
    for r in rows:
        if r["jobs"] == jobs:
            return r
    return None


def find_knee(rows):
    """First jobs value where going higher buys less than 10% more speed."""
    usable = [r for r in rows if r["wall"]]
    for i in range(1, len(usable)):
        prev, cur = usable[i - 1], usable[i]
        if prev["wall"] <= 0:
            continue
        improvement = (prev["wall"] - cur["wall"]) / prev["wall"]
        if improvement < 0.10:
            return prev["jobs"]
    return usable[-1]["jobs"] if usable else None


def fmt(x, suffix=""):
    return "NA" if x is None else f"{x:.2f}{suffix}"


def main():
    if len(sys.argv) < 2:
        print("usage: analyze.py <run_dir>", file=sys.stderr)
        sys.exit(1)
    run_dir = sys.argv[1]

    meta = load_meta(run_dir)
    ncores = meta["ncores"]
    target = meta["target"]
    rows = load_sweep(run_dir)

    r1 = pick(rows, 1)
    rN = pick(rows, ncores) or max(rows, key=lambda r: r["jobs"])

    total_work = r1["wall"] if r1 else None       # jobs=1 wall ~= total work
    cp = r1["cp"] if r1 else None                  # cleanest critical path
    wall = rN["wall"] if rN else None              # real wall at core count

    observed_par = (total_work / wall) if (total_work and wall) else None
    headroom = (wall / cp) if (wall and cp) else None
    available_par = (total_work / cp) if (total_work and cp) else None
    knee = find_knee(rows)

    crit_names, actions, peak = parse_profile(
        os.path.join(run_dir, f"profile_jobs_{ncores}.json.gz"))
    if not actions:
        crit_names, actions, peak = parse_profile(
            os.path.join(run_dir, "profile_jobs_1.json.gz"))
    actions.sort(key=lambda a: a["dur"], reverse=True)
    top_actions = []
    for a in actions[:10]:
        top_actions.append({
            "name": a["name"],
            "dur_s": round(a["dur"], 3),
            "on_critical_path": bare_action_name(a["name"]) in crit_names,
        })

    spawns = parse_exec_log(os.path.join(run_dir, "exec_jobs_1.json"))
    exec_s = overhead_s = 0.0
    top_spawns = []
    for s in spawns:
        m = s.get("metrics", {})
        ex = dur_to_s(m.get("executionWallTime"))
        tot = dur_to_s(m.get("totalTime"))
        exec_s += ex
        overhead_s += max(0.0, tot - ex)
        top_spawns.append({
            "label": s.get("targetLabel") or s.get("progressMessage", ""),
            "mnemonic": s.get("mnemonic", ""),
            "exec_s": round(ex, 3),
            "overhead_s": round(max(0.0, tot - ex), 3),
        })
    top_spawns.sort(key=lambda x: x["exec_s"] + x["overhead_s"], reverse=True)
    top_spawns = top_spawns[:10]
    exec_share = (exec_s / (exec_s + overhead_s)) if (exec_s + overhead_s) > 0 else None

    noop_count, noop_reasons, noop_processes = noop_reexec_count(run_dir)

    rules, fwd = load_graph(run_dir)
    fanout = compute_fanout(rules, fwd) if rules else []
    top_fanout = [d for d in fanout if d["fanout"] > 0][:10]

    # Verify-it-yourself commands, with real values substituted.
    jl = meta["jobs_list"]
    verify = {
        "Q1": [
            f"bazel clean && bazel build {target} --jobs=1",
            f"bazel clean && bazel build {target} --jobs={ncores}",
            "# compare the two 'Elapsed time' values",
        ],
        "Q2": [
            "for j in " + " ".join(str(j) for j in jl) +
            f"; do bazel clean; bazel build {target} --jobs=$j; done",
            "# watch where 'Elapsed time' stops dropping (the knee)",
        ],
        "Q3": [
            f"bazel build {target} --execution_log_json_file=exec.json",
            "# per spawn, compare metrics.executionWallTime vs metrics.totalTime",
        ],
        "Q4": [
            f"bazel build {target} --profile=p.json.gz   # open at https://ui.perfetto.dev, see Critical Path (time axis)",
            "bazel query 'somepath(<target>, <suspected-dep>)'",
            "bazel query 'rdeps(" + target + ", <node>)' | wc -l   # fan-out / blast radius of a node",
        ],
        "Q5": [
            f"bazel build {target}            # warm the cache",
            f"bazel build {target} --explain=explain.txt --verbose_explanations",
            "# a clean no-op rebuilds nothing; explain.txt lists any reasons",
        ],
    }

    # Answers: measured facts; the agent phrases the verdict.
    answers = {
        "Q1_using_cores": {
            "question": "Are you using the cores you already have?",
            "observed_parallelism": round(observed_par, 2) if observed_par else None,
            "cores": ncores,
            "peak_concurrency": round(peak, 1) if peak else None,
            "cores_idle": bool(observed_par and observed_par < 0.75 * ncores and headroom and headroom > 1.3),
            "verify": verify["Q1"],
        },
        "Q2_more_cores": {
            "question": "Would more cores help?",
            "available_parallelism": round(available_par, 2) if available_par else None,
            "cores": ncores,
            "sweep_knee_jobs": knee,
            "more_cores_help": bool(available_par and available_par > ncores * 1.1 and headroom and headroom > 1.3),
            "verify": verify["Q2"],
        },
        "Q3_exec_vs_overhead": {
            "question": "Is the slowest work real execution or overhead?",
            "execution_share": round(exec_share, 3) if exec_share is not None else None,
            "execution_s": round(exec_s, 2),
            "overhead_s": round(overhead_s, 2),
            "top_spawns": top_spawns,
            "verify": verify["Q3"],
        },
        "Q4_critical_path": {
            "question": "Are there nodes holding up everything?",
            "heaviest_on_path": top_actions,
            "on_path_count": sum(1 for a in top_actions if a["on_critical_path"]),
            "highest_fanout": top_fanout,
            "highest_fanout_label": top_fanout[0]["label"] if top_fanout else None,
            "highest_fanout_count": top_fanout[0]["fanout"] if top_fanout else None,
            "verify": verify["Q4"],
        },
        "Q5_redo_unchanged": {
            "question": "Are you redoing work that never changed?",
            "noop_reexecuted_actions": noop_count,
            "noop_processes_line": noop_processes,
            "sample_reasons": noop_reasons,
            "hermetic": noop_count == 0,
            "verify": verify["Q5"],
        },
    }

    report = {
        "target": target,
        "cores": ncores,
        "numbers": {
            "wall_s": wall,
            "critical_path_s": cp,
            "total_work_s": total_work,
        },
        "derived": {
            "observed_parallelism": round(observed_par, 2) if observed_par else None,
            "headroom_factor": round(headroom, 2) if headroom else None,
            "available_parallelism": round(available_par, 2) if available_par else None,
            "sweep_knee_jobs": knee,
        },
        "sweep": rows,
        "answers": answers,
        "run_dir": run_dir,
    }

    out_path = os.path.join(run_dir, "report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    # Human summary.
    print(f"\noptimal_build_check report for {target} ({ncores} cores)\n")
    print("The three numbers")
    print(f"  wall          {fmt(wall, 's')}")
    print(f"  critical path {fmt(cp, 's')}   (floor; measured at --jobs=1)")
    print(f"  total work    {fmt(total_work, 's')}   (--jobs=1 wall)\n")
    print("How far from optimal")
    print(f"  observed parallelism  {fmt(observed_par)}  (cores effectively used)")
    print(f"  headroom factor       {fmt(headroom)}x (wall / critical path)")
    print(f"  available parallelism {fmt(available_par)}  (cores that still help)")
    print(f"  --jobs sweep knee     {knee} jobs\n")
    print("Sweep")
    for r in rows:
        print(f"  jobs={r['jobs']:<4} wall={fmt(r['wall'], 's'):<10} cp={fmt(r['cp'], 's')}")
    print("\nQ4a Heaviest actions by TIME (on critical path marked *)")
    for a in top_actions[:5]:
        mark = "*" if a["on_critical_path"] else " "
        print(f"  {mark} {a['dur_s']:>7.3f}s  {a['name'][:70]}")
    print("\nQ4b Highest FAN-OUT by blast radius (targets that rebuild when this changes)")
    if top_fanout:
        for d in top_fanout[:5]:
            print(f"    {d['fanout']:>4} deps  {d['label']}")
    else:
        print("    (no graph data; rerun collect.sh to populate graph.dot)")
    print(f"\nExecution vs overhead: exec={fmt(exec_s, 's')} overhead={fmt(overhead_s, 's')}"
          f" (exec share {fmt(exec_share)})")
    print(f"No-op rebuild re-executed actions: {noop_count}"
          f"  {'(hermetic)' if noop_count == 0 else '(NOT hermetic)'}")
    print(f"\nFull report: {out_path}\n")


if __name__ == "__main__":
    main()
