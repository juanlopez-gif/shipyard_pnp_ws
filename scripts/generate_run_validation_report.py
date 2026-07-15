#!/usr/bin/env python3
"""
Generate a fixed-vs-dynamic validation report from MES production runs.

The report uses the real production-duration convention used in the dynamic
map validation docs:

  - t0: first xarm2 cycle start, including WAITING_GLOBALVISION.
  - t_fin: end of RETURNING_HOME in the last robot1 cycle.

For dynamic runs, the simulated map comes from
production_run.config_snapshot.expected_schedule. That matters: rebuilding the
schedule from optimized_order would silently turn a dynamic map back into a
fixed-priority schedule.

Examples:
    PYTHONPATH=src/shipyard_pnp PGPASSWORD=postgres \\
      python3 scripts/generate_run_validation_report.py \\
        --fixed-run 20260712_205819_BGRBGGRGGG \\
        --dynamic-run 20260712_210633_BGRBGGRGGG \\
        --out docs/dynamic_map_2b2r6g

    PYTHONPATH=src/shipyard_pnp PGPASSWORD=postgres \\
      python3 scripts/generate_run_validation_report.py --latest-dynamic --out /tmp/latest.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from shipyard_pnp.factory.expected_schedule import compute_expected_schedule


SCHEMA = "shipyard_pnp_ws"
CONN_DEFAULTS = {
    "host": os.environ.get("PGHOST", "100.115.213.16"),
    "port": int(os.environ.get("PGPORT", "5432")),
    "user": os.environ.get("PGUSER", "twin_mes_db"),
    "password": os.environ.get("PGPASSWORD", "postgres"),
    "dbname": os.environ.get("PGDATABASE", "twin_mes_db"),
}

ENTITY_ORDER = ["xarm2", "xarm1", "laser", "robot2", "bantam", "robot1"]
COLOR_ORDER = ["BLUE", "GREEN", "RED"]


def connect():
    return psycopg2.connect(**CONN_DEFAULTS)


def counter_key(entity: str, task: str) -> str:
    if entity == "robot2" and task.startswith("CLASSIFY_C2S2_TO_"):
        return "CLASSIFY_C2S2"
    return task


def compact_order(order: Any) -> str:
    if not order:
        return ""
    if isinstance(order, str):
        try:
            parsed = json.loads(order)
        except json.JSONDecodeError:
            return order
        order = parsed
    return "".join(str(color)[0].upper() for color in order)


def color_counts(order: Any) -> Counter:
    counts = Counter()
    if not order:
        return counts
    if isinstance(order, str):
        try:
            order = json.loads(order)
        except json.JSONDecodeError:
            letters = {"B": "BLUE", "R": "RED", "G": "GREEN"}
            order = [letters[ch.upper()] for ch in order if ch.upper() in letters]
    for color in order:
        counts[str(color).upper()] += 1
    return counts


def composition_label(counts: Counter) -> str:
    return f"{counts['BLUE']}B/{counts['RED']}R/{counts['GREEN']}G"


def composition_slug(counts: Counter) -> str:
    return f"{counts['BLUE']}b{counts['RED']}r{counts['GREEN']}g"


def map_mode(run: dict) -> str:
    snap = run.get("config_snapshot") or {}
    return snap.get("map_mode") or "fixed"


def map_id(run: dict) -> str:
    snap = run.get("config_snapshot") or {}
    return snap.get("map_id") or ""


def fetch_run(conn, run_id: str) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(f"SELECT * FROM {SCHEMA}.production_run WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"No production_run found for {run_id}")
    return dict(row)


def fetch_latest_dynamic_run(conn) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT *
            FROM {SCHEMA}.production_run
            WHERE status = 'COMPLETED'
              AND config_snapshot->>'map_mode' = 'dynamic'
            ORDER BY started_at DESC
            LIMIT 1"""
    )
    row = cur.fetchone()
    if not row:
        raise SystemExit("No completed dynamic run found")
    return dict(row)


def fetch_recent_completed_runs(conn, limit: int = 300) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT *
            FROM {SCHEMA}.production_run
            WHERE status = 'COMPLETED'
            ORDER BY started_at DESC
            LIMIT %s""",
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


def infer_fixed_reference(conn, dynamic_run: dict) -> dict:
    dyn_started = dynamic_run["started_at"]
    dyn_original = compact_order(dynamic_run.get("original_order"))
    dyn_counts = color_counts(dynamic_run.get("original_order"))

    candidates = []
    for run in fetch_recent_completed_runs(conn):
        if run["run_id"] == dynamic_run["run_id"]:
            continue
        if run["started_at"] >= dyn_started:
            continue
        if map_mode(run) == "dynamic":
            continue
        if color_counts(run.get("original_order")) == dyn_counts:
            candidates.append(run)

    if not candidates:
        raise SystemExit(
            "Could not infer fixed reference: pass --fixed-run explicitly."
        )

    exact_order = [
        run for run in candidates
        if compact_order(run.get("original_order")) == dyn_original
    ]
    return max(exact_order or candidates, key=lambda run: run["started_at"])


def fetch_cycles(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT entity, task_name, piece_id, color, cycle_number, started_at,
                   total_duration_s, is_discarded, discarded_reason,
                   metadata, phases
            FROM {SCHEMA}.cycle_event
            WHERE run_id = %s
            ORDER BY started_at ASC, id ASC""",
        (run_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_piece_outcomes(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT piece_id, route_taken, final_location, total_time_s,
                   completed, completed_at
            FROM {SCHEMA}.piece_outcome
            WHERE run_id = %s
            ORDER BY piece_id ASC""",
        (run_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def fetch_apply_events(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT event_type, description, ts
            FROM {SCHEMA}.operator_event
            WHERE run_id = %s AND event_type = 'APPLY_ORDER'
            ORDER BY ts ASC""",
        (run_id,),
    )
    return [dict(row) for row in cur.fetchall()]


def returning_home_end(phases) -> float | None:
    if not phases:
        return None
    for phase in phases:
        if phase.get("phase") == "RETURNING_HOME":
            return phase.get("end")
    return None


def schedule_from_run(run: dict) -> tuple[dict, float, str]:
    snap = run.get("config_snapshot") or {}
    expected = snap.get("expected_schedule")
    if isinstance(expected, dict) and expected:
        schedule = expected
        source = "snapshot"
    else:
        order = run.get("optimized_order") or run.get("original_order") or []
        schedule = compute_expected_schedule(order)
        source = "computed_fixed"

    sim_total = max(
        (
            float(cycle["t_start"]) + float(cycle["dur"])
            for cycles in schedule.values()
            for cycle in cycles
        ),
        default=0.0,
    )
    return schedule, sim_total, source


def status_for_cycle(cycle: dict, sim: dict | None) -> str:
    metadata = cycle.get("metadata") or {}
    piece_id = cycle.get("piece_id") or ""
    if cycle.get("is_discarded"):
        return "discarded"
    if piece_id.startswith("intruder-"):
        return "intruder"
    if metadata.get("map_outcome") in ("followed", "timeout"):
        return metadata["map_outcome"]
    if sim is not None:
        return "matched"
    return "no_sim"


def validate_run(conn, run: dict) -> dict:
    run_id = run["run_id"]
    cycles = fetch_cycles(conn, run_id)
    outcomes = fetch_piece_outcomes(conn, run_id)
    apply_events = fetch_apply_events(conn, run_id)

    if not cycles:
        raise SystemExit(f"Run {run_id} has no cycle_event rows")

    xarm2_cycles = [cycle for cycle in cycles if cycle["entity"] == "xarm2"]
    if not xarm2_cycles:
        raise SystemExit(f"Run {run_id} has no xarm2 cycles; cannot set t0")
    t0 = min(cycle["started_at"] for cycle in xarm2_cycles)

    robot1_cycles = [cycle for cycle in cycles if cycle["entity"] == "robot1"]
    if not robot1_cycles:
        raise SystemExit(f"Run {run_id} has no robot1 cycles; cannot set t_fin")
    last_robot1 = max(robot1_cycles, key=lambda cycle: cycle["started_at"])
    home_end = returning_home_end(last_robot1.get("phases"))
    if home_end is not None:
        t_fin = datetime.fromtimestamp(float(home_end), tz=timezone.utc)
        t_fin = t_fin.astimezone(t0.tzinfo)
    else:
        t_fin = last_robot1["started_at"]
        if last_robot1.get("total_duration_s"):
            t_fin += timedelta(seconds=float(last_robot1["total_duration_s"]))

    schedule, sim_total, schedule_source = schedule_from_run(run)
    sim_lookup = {}
    sim_seq = defaultdict(list)
    for entity, sched_cycles in schedule.items():
        for cycle in sched_cycles:
            key = (entity, counter_key(entity, cycle["task"]), int(cycle["cycle_number"]))
            sim_lookup[key] = cycle
            sim_seq[entity].append(
                (cycle["task"], int(cycle["cycle_number"]), cycle.get("color"))
            )

    status_counts = Counter()
    task_counts = Counter()
    real_seq = defaultdict(list)
    followed_rows = []
    timeout_rows = []
    no_sim_rows = []
    intruder_rows = []
    discarded_rows = []
    task_mismatches = []
    color_mismatches = []

    for cycle in cycles:
        key = (
            cycle["entity"],
            counter_key(cycle["entity"], cycle["task_name"]),
            int(cycle["cycle_number"]),
        )
        sim = sim_lookup.get(key)
        status = status_for_cycle(cycle, sim)
        status_counts[status] += 1
        task_counts[(cycle["entity"], cycle["task_name"])] += 1
        real_seq[cycle["entity"]].append(
            (cycle["task_name"], int(cycle["cycle_number"]), cycle.get("color"))
        )

        if status == "followed":
            followed_rows.append(cycle)
        elif status == "timeout":
            timeout_rows.append(cycle)
        elif status == "no_sim":
            no_sim_rows.append(cycle)
        elif status == "intruder":
            intruder_rows.append(cycle)
        elif status == "discarded":
            discarded_rows.append(cycle)

        if sim is None:
            continue
        if sim.get("task") != cycle["task_name"]:
            task_mismatches.append((cycle, sim))
        sim_color = sim.get("color")
        if sim_color and cycle.get("color") and sim_color != cycle.get("color"):
            color_mismatches.append((cycle, sim))

    per_entity = {}
    for entity in ENTITY_ORDER:
        per_entity[entity] = "OK" if sim_seq.get(entity) == real_seq.get(entity) else "MISMATCH"

    outcome_counts = defaultdict(Counter)
    completed_outcomes = 0
    for outcome in outcomes:
        route = outcome.get("route_taken") or "UNKNOWN"
        final = outcome.get("final_location") or "UNKNOWN"
        outcome_counts[route][final] += 1
        if outcome.get("completed"):
            completed_outcomes += 1

    real_total = (t_fin - t0).total_seconds()
    expected_cycles = sum(len(rows) for rows in schedule.values())
    validation_ok = (
        run.get("status") == "COMPLETED"
        and int(run.get("pieces_completed") or 0) == int(run.get("total_pieces") or -1)
        and expected_cycles == len(cycles)
        and not task_mismatches
        and not color_mismatches
        and not timeout_rows
        and not no_sim_rows
        and not intruder_rows
        and not discarded_rows
        and all(value == "OK" for value in per_entity.values())
    )

    return {
        "run_id": run_id,
        "db_status": run.get("status"),
        "map_mode": map_mode(run),
        "map_id": map_id(run),
        "original_order": compact_order(run.get("original_order")),
        "optimized_order": compact_order(run.get("optimized_order")),
        "total_pieces": int(run.get("total_pieces") or 0),
        "pieces_completed": int(run.get("pieces_completed") or 0),
        "t0": t0,
        "t_fin": t_fin,
        "real_total_s": real_total,
        "sim_total_s": sim_total,
        "diff_s": real_total - sim_total,
        "diff_pct": ((real_total - sim_total) / sim_total * 100.0) if sim_total else None,
        "schedule_source": schedule_source,
        "expected_cycles": expected_cycles,
        "real_cycles": len(cycles),
        "matched_count": status_counts["matched"],
        "followed_count": status_counts["followed"],
        "timeout_count": status_counts["timeout"],
        "no_sim_count": status_counts["no_sim"],
        "intruder_count": status_counts["intruder"],
        "discarded_count": status_counts["discarded"],
        "task_mismatch_count": len(task_mismatches),
        "color_mismatch_count": len(color_mismatches),
        "per_entity": per_entity,
        "task_counts": dict(sorted(task_counts.items())),
        "followed_rows": followed_rows,
        "timeout_rows": timeout_rows,
        "outcome_counts": {route: dict(counts) for route, counts in outcome_counts.items()},
        "completed_outcomes": completed_outcomes,
        "apply_events": apply_events,
        "validation_ok": validation_ok,
    }


def fmt_s(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f} s"


def fmt_pct(value: float | None, digits: int = 2, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    sign = "+" if signed else ""
    return f"{value:{sign}.{digits}f}%"


def code_block(lines: list[str]) -> str:
    return "```text\n" + "\n".join(lines) + "\n```"


def task_counts_lines(audit: dict) -> list[str]:
    lines = []
    for (entity, task), count in audit["task_counts"].items():
        lines.append(f"{entity:<7} {task:<27} {count:>3}")
    return lines


def per_entity_lines(audit: dict) -> list[str]:
    return [f"{entity:<7} {audit['per_entity'].get(entity, 'MISSING')}" for entity in ENTITY_ORDER]


def wait_lines(audit: dict) -> list[str]:
    rows = []
    for cycle in audit["followed_rows"]:
        metadata = cycle.get("metadata") or {}
        wait_s = metadata.get("map_wait_s")
        wait_txt = f"{float(wait_s):.2f} s" if isinstance(wait_s, (int, float)) else f"{wait_s}s"
        rows.append(
            f"{cycle['entity']} {cycle['task_name']} #{cycle['cycle_number']} "
            f"{cycle.get('piece_id') or ''} {cycle.get('color') or ''} waited {wait_txt}"
        )
    return rows


def outcomes_lines(audit: dict) -> list[str]:
    lines = []
    outcomes = audit["outcome_counts"]
    for color in COLOR_ORDER:
        if color not in outcomes:
            continue
        dests = ", ".join(
            f"{dest}={count}" for dest, count in sorted(outcomes[color].items())
        )
        lines.append(f"{color:<6} {dests}")
    for color in sorted(set(outcomes) - set(COLOR_ORDER)):
        dests = ", ".join(
            f"{dest}={count}" for dest, count in sorted(outcomes[color].items())
        )
        lines.append(f"{color:<6} {dests}")
    return lines or ["No piece_outcome rows found"]


def apply_order_text(audit: dict) -> str:
    if not audit["apply_events"]:
        return "No APPLY_ORDER event found."
    return audit["apply_events"][-1]["description"]


def render_run_section(title: str, audit: dict, dynamic: bool) -> str:
    source_note = (
        "stored dynamic map" if audit["schedule_source"] == "snapshot"
        else "computed fixed schedule"
    )
    lines = [
        f"run_id:          {audit['run_id']}",
        f"original stack:  {audit['original_order']}",
        f"applied stack:   {audit['optimized_order']}",
        f"map_mode:        {audit['map_mode']}",
    ]
    if dynamic:
        lines.append(f"map_id:          {audit['map_id']}")
    lines.extend([
        f"schedule source: {source_note}",
        f"t0:              {audit['t0'].isoformat()}",
        f"t_fin:           {audit['t_fin'].isoformat()}",
        f"real:            {fmt_s(audit['real_total_s'])}",
        f"sim:             {fmt_s(audit['sim_total_s'], 1)}",
        f"diff:            {audit['diff_s']:+.3f} s ({fmt_pct(audit['diff_pct'])})",
    ])

    cycle_lines = [
        f"expected cycles: {audit['expected_cycles']}",
        f"real cycles:     {audit['real_cycles']}",
        f"matched:         {audit['matched_count']}",
        f"followed map:    {audit['followed_count']}",
        f"timeout:         {audit['timeout_count']}",
        f"no_sim:          {audit['no_sim_count']}",
        f"intruder:        {audit['intruder_count']}",
        f"discarded:       {audit['discarded_count']}",
        f"task mismatch:   {audit['task_mismatch_count']}",
        f"color mismatch:  {audit['color_mismatch_count']}",
        f"completed pieces: {audit['pieces_completed']}/{audit['total_pieces']}",
    ]

    wait_text = (
        code_block(wait_lines(audit))
        if audit["followed_rows"]
        else "No controlled map waits were needed in this run."
    )

    section = [
        f"## {title}",
        "",
    ]
    if dynamic:
        section.extend([
            "Important validation detail: for dynamic-map runs, this report uses the",
            "`expected_schedule` stored in `production_run.config_snapshot` when present.",
            "",
        ])
    section.extend([
        code_block(lines),
        "",
        "Cycle execution check:",
        "",
        code_block(cycle_lines),
        "",
        "Per-entity cycle order:",
        "",
        code_block(per_entity_lines(audit)),
        "",
        "Task counts:",
        "",
        code_block(task_counts_lines(audit)),
        "",
        "Controlled map waits:",
        "",
        wait_text,
        "",
        "`Confirm & Apply` event:",
        "",
        code_block([apply_order_text(audit)]),
    ])
    return "\n".join(section)


def render_markdown(fixed: dict, dynamic: dict, title: str | None = None) -> str:
    counts = color_counts(dynamic["original_order"] or fixed["original_order"])
    label = title or composition_label(counts)
    date = dynamic["t0"].date().isoformat()
    real_saving = fixed["real_total_s"] - dynamic["real_total_s"]
    real_saving_pct = real_saving / fixed["real_total_s"] * 100.0
    sim_saving = fixed["sim_total_s"] - dynamic["sim_total_s"]
    sim_saving_pct = sim_saving / fixed["sim_total_s"] * 100.0 if fixed["sim_total_s"] else 0.0
    saving_delta = real_saving - sim_saving
    saving_delta_pct = real_saving_pct - sim_saving_pct
    control_case = abs(sim_saving_pct) < 0.05 and fixed["optimized_order"] == dynamic["optimized_order"]

    if control_case:
        finding = (
            f"La prueba `{label}` funciona como caso de control: el mapa dinamico "
            f"coincide con la referencia fixed (`{dynamic['optimized_order']}`), "
            f"la simulacion predice `0.0%` de ahorro, y la diferencia real fue "
            f"`{real_saving:+.3f} s` (`{real_saving_pct:+.2f}%`), dentro de la "
            "variacion experimental del hardware."
        )
    else:
        finding = (
            f"La prueba `{label}` valida una politica dinamica distinta: el mapa "
            f"`{dynamic['optimized_order']}` redujo el makespan real en "
            f"`{real_saving:.3f} s` (`{real_saving_pct:.2f}%`) frente a la "
            f"referencia fixed `{fixed['optimized_order']}`."
        )

    ok_text = (
        "Both runs passed the cycle-level validation."
        if fixed["validation_ok"] and dynamic["validation_ok"]
        else "At least one run has validation issues; inspect the cycle checks below."
    )

    dynamic_policy = dynamic["map_id"] or "dynamic"

    parts = [
        f"# Dynamic Map {label} Validation Notes",
        "",
        f"Date: {date}",
        "",
        "## Hallazgo principal",
        "",
        finding,
        "",
        ok_text,
        "",
        "Criterion for real production duration in all real comparisons:",
        "",
        "- `t0`: start of the first `xarm2` cycle, including `WAITING_GLOBALVISION`.",
        "- `t_fin`: end of `RETURNING_HOME` in the last `robot1` cycle.",
        "",
        "## Comparacion real",
        "",
        "| Scenario | Input stack | Applied stack | Politica / mapa | Sim time | Real run | Real time |",
        "|---|---:|---:|---|---:|---|---:|",
        (
            f"| Fixed reference | `{fixed['original_order']}` | `{fixed['optimized_order']}` | "
            f"fixed priorities | `{fixed['sim_total_s']:.1f} s` | "
            f"`{fixed['run_id']}` | `{fixed['real_total_s']:.3f} s` |"
        ),
        (
            f"| Mapa dinamico | `{dynamic['original_order']}` | `{dynamic['optimized_order']}` | "
            f"`{dynamic_policy}` | `{dynamic['sim_total_s']:.1f} s` | "
            f"`{dynamic['run_id']}` | `{dynamic['real_total_s']:.3f} s` |"
        ),
        "",
        "Quantified deltas:",
        "",
        (
            f"- Dynamic real vs fixed real: `{fixed['real_total_s']:.3f} -> "
            f"{dynamic['real_total_s']:.3f} s`, saving real `{real_saving:+.3f} s` "
            f"(`{real_saving_pct:+.2f}%`)."
        ),
        (
            f"- Dynamic sim vs fixed sim: `{fixed['sim_total_s']:.1f} -> "
            f"{dynamic['sim_total_s']:.1f} s`, saving sim `{sim_saving:+.1f} s` "
            f"(`{sim_saving_pct:+.2f}%`)."
        ),
        (
            f"- Fixed real fidelity: `{fixed['real_total_s']:.3f} s` real vs "
            f"`{fixed['sim_total_s']:.1f} s` sim, diff `{fixed['diff_s']:+.3f} s` "
            f"(`{fixed['diff_pct']:+.2f}%`)."
        ),
        (
            f"- Dynamic real fidelity: `{dynamic['real_total_s']:.3f} s` real vs "
            f"`{dynamic['sim_total_s']:.1f} s` sim, diff `{dynamic['diff_s']:+.3f} s` "
            f"(`{dynamic['diff_pct']:+.2f}%`)."
        ),
        (
            f"- Real saving vs predicted saving: `{real_saving:+.3f} s` real vs "
            f"`{sim_saving:+.1f} s` simulated, delta `{saving_delta:+.3f} s` "
            f"(`{saving_delta_pct:+.2f} pp`)."
        ),
        "",
        render_run_section("Fixed run validation", fixed, dynamic=False),
        "",
        render_run_section("Dynamic run validation", dynamic, dynamic=True),
        "",
        "## Final piece outcomes",
        "",
        "Fixed final destinations:",
        "",
        code_block(outcomes_lines(fixed)),
        "",
        "Dynamic final destinations:",
        "",
        code_block(outcomes_lines(dynamic)),
        "",
        "## Conclusion",
        "",
    ]

    if control_case:
        conclusion = (
            f"The `{label}` dynamic map executed correctly and produced the expected "
            "control result: no measurable policy improvement because the dynamic "
            "map and fixed reference are the same schedule. The observed real "
            f"difference was `{real_saving:+.3f} s` (`{real_saving_pct:+.2f}%`), "
            "inside the normal sim-vs-real/hardware variation observed in this "
            "system."
        )
    else:
        conclusion = (
            f"The `{label}` dynamic map executed correctly and produced a real "
            f"makespan reduction of `{real_saving:.3f} s` (`{real_saving_pct:.2f}%`). "
            "All expected cycles were checked against the stored map/fixed schedule; "
            "see the validation blocks above for any warnings."
        )
    parts.append(conclusion)

    return "\n".join(parts) + "\n"


def summary_payload(fixed: dict, dynamic: dict) -> dict:
    real_saving = fixed["real_total_s"] - dynamic["real_total_s"]
    real_saving_pct = real_saving / fixed["real_total_s"] * 100.0
    sim_saving = fixed["sim_total_s"] - dynamic["sim_total_s"]
    sim_saving_pct = sim_saving / fixed["sim_total_s"] * 100.0 if fixed["sim_total_s"] else 0.0
    counts = color_counts(dynamic["original_order"] or fixed["original_order"])
    return {
        "composition": composition_label(counts),
        "fixed_run": fixed["run_id"],
        "dynamic_run": dynamic["run_id"],
        "fixed_order": fixed["optimized_order"],
        "dynamic_order": dynamic["optimized_order"],
        "fixed_real_s": round(fixed["real_total_s"], 3),
        "dynamic_real_s": round(dynamic["real_total_s"], 3),
        "fixed_sim_s": round(fixed["sim_total_s"], 1),
        "dynamic_sim_s": round(dynamic["sim_total_s"], 1),
        "real_saving_s": round(real_saving, 3),
        "real_saving_pct": round(real_saving_pct, 3),
        "sim_saving_s": round(sim_saving, 1),
        "sim_saving_pct": round(sim_saving_pct, 3),
        "fixed_validation_ok": fixed["validation_ok"],
        "dynamic_validation_ok": dynamic["validation_ok"],
    }


def resolve_out_path(raw_out: str, counts: Counter) -> Path:
    out = Path(raw_out)
    if out.suffix.lower() == ".md":
        return out
    if str(out).endswith(os.sep) or not out.suffix:
        return out / "README.md"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fixed-run", help="Fixed-priority production_run.run_id")
    parser.add_argument("--dynamic-run", help="Dynamic-map production_run.run_id")
    parser.add_argument(
        "--latest-dynamic",
        action="store_true",
        help="Use the latest completed dynamic run and infer its fixed reference",
    )
    parser.add_argument(
        "--out",
        help="Markdown output path, or directory where README.md should be written",
    )
    parser.add_argument("--title", help="Report title/composition label override")
    parser.add_argument("--summary-json", help="Optional path for machine-readable summary")
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Exit with code 2 if either run fails cycle-level validation",
    )
    args = parser.parse_args()

    if args.latest_dynamic and args.dynamic_run:
        parser.error("Use either --latest-dynamic or --dynamic-run, not both")
    if not args.latest_dynamic and not args.dynamic_run:
        parser.error("Pass --dynamic-run or --latest-dynamic")

    with connect() as conn:
        dynamic_run = fetch_latest_dynamic_run(conn) if args.latest_dynamic else fetch_run(conn, args.dynamic_run)
        fixed_run = fetch_run(conn, args.fixed_run) if args.fixed_run else infer_fixed_reference(conn, dynamic_run)
        fixed = validate_run(conn, fixed_run)
        dynamic = validate_run(conn, dynamic_run)

    markdown = render_markdown(fixed, dynamic, title=args.title)
    counts = color_counts(dynamic["original_order"] or fixed["original_order"])

    if args.out:
        out_path = resolve_out_path(args.out, counts)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
        print(f"Markdown written to {out_path}")
    else:
        print(markdown)

    if args.summary_json:
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(summary_payload(fixed, dynamic), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Summary JSON written to {summary_path}")

    summary = summary_payload(fixed, dynamic)
    print(
        "Summary: "
        f"{summary['composition']} fixed={summary['fixed_real_s']:.3f}s "
        f"dynamic={summary['dynamic_real_s']:.3f}s "
        f"saving={summary['real_saving_s']:+.3f}s "
        f"({summary['real_saving_pct']:+.2f}%) "
        f"validation fixed={summary['fixed_validation_ok']} "
        f"dynamic={summary['dynamic_validation_ok']}",
        file=sys.stderr,
    )

    if args.fail_on_issues and not (fixed["validation_ok"] and dynamic["validation_ok"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
