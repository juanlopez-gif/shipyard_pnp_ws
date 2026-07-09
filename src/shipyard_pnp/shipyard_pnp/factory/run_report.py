"""
Comparación completa realidad vs simulación para una corrida, por componente.

Para cada cycle_event real de la corrida, busca su ciclo equivalente en el
mapa (misma entidad, misma tarea, mismo cycle_number) y calcula:
  - instante real y simulado (ambos relativos al t0 correcto, ver CLAUDE.md)
  - diferencia en segundos
  - si hubo que esperar al mapa (map_outcome/map_wait_s en metadata) o si
    coincidió directamente sin espera, o si no tiene equivalente en el mapa

Uso:
    python3 -m shipyard_pnp.factory.run_report [RUN_ID] [--out DIR]

Sin RUN_ID usa la corrida más reciente en production_run.

Criterios de t0/t_fin real y de duración total simulada: ver CLAUDE.md en la
raíz del repo — NO usar production_run.started_at/finished_at como ancla, y
usar el máximo sin filtrar de state_changes (no compute_expected_schedule)
para la duración total simulada.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

from shipyard_pnp.factory.expected_schedule import compute_expected_schedule

_SCHEMA = "shipyard_pnp_ws"
_CONN_DEFAULTS = dict(
    host     = os.environ.get("PGHOST",     "100.115.213.16"),
    port     = int(os.environ.get("PGPORT", "5432")),
    user     = os.environ.get("PGUSER",     "twin_mes_db"),
    password = os.environ.get("PGPASSWORD", "postgres"),
    dbname   = os.environ.get("PGDATABASE", "twin_mes_db"),
)


def _connect():
    return psycopg2.connect(**_CONN_DEFAULTS)


def _counter_key(entity: str, task: str) -> str:
    # robot2's real cycle starts out generic ("CLASSIFY_C2S2") and is only
    # renamed once vision confirms the route -- the cycle_number counter is
    # shared across all four CLASSIFY_C2S2_TO_* variants. Match that here so
    # sim/real cycle_number line up (same special-case as expected_schedule.py).
    if entity == "robot2" and task.startswith("CLASSIFY_C2S2_TO_"):
        return "CLASSIFY_C2S2"
    return task


def _fetch_run(conn, run_id: str | None) -> dict:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if run_id:
        cur.execute(
            f"SELECT * FROM {_SCHEMA}.production_run WHERE run_id = %s", (run_id,)
        )
    else:
        cur.execute(
            f"SELECT * FROM {_SCHEMA}.production_run ORDER BY started_at DESC LIMIT 1"
        )
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"No se encontró la corrida '{run_id}'" if run_id else "No hay corridas en production_run")
    return dict(row)


def _fetch_real_cycles(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT entity, task_name, piece_id, color, cycle_number, started_at,
                   total_duration_s, is_discarded, discarded_reason, metadata, phases
            FROM {_SCHEMA}.cycle_event
            WHERE run_id = %s
            ORDER BY started_at ASC""",
        (run_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _fetch_piece_transfers(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT piece_id, from_loc, to_loc, ts
            FROM {_SCHEMA}.piece_transfer
            WHERE run_id = %s
            ORDER BY piece_id ASC, ts ASC""",
        (run_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def build_sim_schedule(order: list[str]) -> tuple[dict, float]:
    """compute_expected_schedule()'s per-cycle grouping -- since it now
    keeps piece=None events (the IDLE that closes out a RETURN_HOME) instead
    of dropping them, t_start+dur for every cycle already reflects the true
    end, including the last cycle of the last entity to finish. The true
    total makespan is just the max over all of them."""
    schedule = compute_expected_schedule(order)
    sim_total_true = max(
        (c["t_start"] + c["dur"] for cycles in schedule.values() for c in cycles),
        default=0.0,
    )
    return schedule, sim_total_true


def _returning_home_end(phases) -> float | None:
    if not phases:
        return None
    for p in phases:
        if p.get("phase") == "RETURNING_HOME":
            return p.get("end")
    return None


def build_report(run_id: str | None) -> dict:
    conn = _connect()
    try:
        run_row = _fetch_run(conn, run_id)
        run_id = run_row["run_id"]
        order = run_row["optimized_order"]
        real_cycles = _fetch_real_cycles(conn, run_id)
        piece_transfers = _fetch_piece_transfers(conn, run_id)
    finally:
        conn.close()

    if not real_cycles:
        raise SystemExit(f"La corrida '{run_id}' no tiene cycle_event registrados")

    xarm2_cycles = [c for c in real_cycles if c["entity"] == "xarm2"]
    if not xarm2_cycles:
        raise SystemExit("La corrida no tiene ciclos de xarm2 -- no se puede fijar t0 real")
    t0 = min(c["started_at"] for c in xarm2_cycles)

    robot1_cycles = [c for c in real_cycles if c["entity"] == "robot1"]
    t_fin = None
    if robot1_cycles:
        last_robot1 = max(robot1_cycles, key=lambda c: c["started_at"])
        home_end = _returning_home_end(last_robot1["phases"])
        if home_end is not None:
            t_fin = datetime.fromtimestamp(home_end, tz=timezone.utc).astimezone(t0.tzinfo)
        else:
            t_fin = last_robot1["started_at"]
            if last_robot1["total_duration_s"]:
                from datetime import timedelta
                t_fin = t_fin + timedelta(seconds=last_robot1["total_duration_s"])
    real_total_s = (t_fin - t0).total_seconds() if t_fin else None

    sched, sim_total_true = build_sim_schedule(order)
    sim_lookup = {}
    for entity, cycles in sched.items():
        for c in cycles:
            key = (entity, _counter_key(entity, c["task"]), c["cycle_number"])
            sim_lookup[key] = c

    rows = []
    for c in real_cycles:
        real_elapsed = (c["started_at"] - t0).total_seconds()
        key = (c["entity"], _counter_key(c["entity"], c["task_name"]), c["cycle_number"])
        sim = sim_lookup.get(key)
        meta = c["metadata"] or {}
        # 2026-07-08: piece_id is the ONLY reliable signal here -- map_outcome
        # is missing entirely whenever the map ran out of pending entries by
        # the time an intruder showed up (_map_resolve_dispatch returns early
        # if _map_next() is None), which used to make a LATE intruder look
        # identical to "no_sim" (a normal, harmless cycle the map never
        # modeled) instead of what it actually is -- an unplanned piece
        # forced to scrap. And when map_outcome WAS present ("intruder"), it
        # fell through the generic "elif" below into the timeout branch,
        # printing the literal string "esperó Nones" (map_wait_s is never
        # set for the intruder outcome). Checking is_intruder first, before
        # any map-derived branch, fixes both at once and never depends on
        # map timing.
        is_intruder = bool(c["piece_id"]) and c["piece_id"].startswith("intruder-")

        if c["is_discarded"]:
            status = "discarded"
            status_label = f"DESCARTADO ({c['discarded_reason'] or 's/d'})"
        elif is_intruder:
            status = "intruder"
            expected_label = meta.get("map_expected")
            status_label = (
                f"INTRUSA -- pieza no planeada, forzada a SCRAP "
                f"(el mapa seguía esperando {expected_label}, sigue pendiente)"
                if expected_label else
                "INTRUSA -- pieza no planeada, forzada a SCRAP"
            )
        elif "map_outcome" in meta:
            status = meta["map_outcome"]  # "followed" | "timeout"
            wait_s = meta.get("map_wait_s")
            if status == "followed":
                status_label = f"esperó {wait_s}s al mapa -> coincidió"
            else:
                status_label = f"esperó {wait_s}s, el mapa no llegó a tiempo -> se hizo lo físico"
        elif sim is not None:
            status = "matched"
            status_label = "coincidió sin espera"
        else:
            status = "no_sim"
            status_label = "sin equivalente en el mapa"

        rows.append({
            "entity":        c["entity"],
            "task":          c["task_name"],
            "piece_id":      c["piece_id"],
            "color":         c["color"],
            "cycle_number":  c["cycle_number"],
            "real_t":        round(real_elapsed, 1),
            "real_dur":      c["total_duration_s"],
            "sim_t":         sim["t_start"] if sim else None,
            "sim_dur":       sim["dur"] if sim else None,
            "diff":          round(real_elapsed - sim["t_start"], 1) if sim else None,
            "status":        status,
            "status_label":  status_label,
        })

    transfers = [
        {
            "piece_id": t["piece_id"],
            "from_loc": t["from_loc"],
            "to_loc":   t["to_loc"],
            "t":        round((t["ts"] - t0).total_seconds(), 1),
        }
        for t in piece_transfers
    ]

    return {
        "run_id":        run_id,
        "order":         order,
        "t0":            t0.isoformat(),
        "t_fin":         t_fin.isoformat() if t_fin else None,
        "real_total_s":  round(real_total_s, 1) if real_total_s else None,
        "sim_total_s":   round(sim_total_true, 1),
        "rows":          rows,
        "transfers":     transfers,
    }


def _print_table(report: dict) -> None:
    print(f"Corrida: {report['run_id']}")
    print(f"t0 real: {report['t0']}   t_fin real: {report['t_fin']}")
    if report["real_total_s"] and report["sim_total_s"]:
        diff = report["real_total_s"] - report["sim_total_s"]
        pct = diff / report["sim_total_s"] * 100
        print(
            f"Duración real: {report['real_total_s']:.1f}s   "
            f"simulada: {report['sim_total_s']:.1f}s   "
            f"diff: {diff:+.1f}s ({pct:+.1f}%)"
        )
    print()
    hdr = f"{'entity':8} {'task':24} {'piece':10} {'#':>3} {'real_t':>8} {'sim_t':>8} {'diff':>7}  status"
    print(hdr)
    print("-" * len(hdr))
    for r in report["rows"]:
        sim_t = f"{r['sim_t']:.1f}" if r["sim_t"] is not None else "N/A"
        diff = f"{r['diff']:+.1f}" if r["diff"] is not None else "N/A"
        print(
            f"{r['entity']:8} {r['task']:24} {(r['piece_id'] or ''):10} "
            f"{r['cycle_number']!s:>3} {r['real_t']:>8.1f} {sim_t:>8} {diff:>7}  {r['status_label']}"
        )


def render_html(report: dict) -> str:
    template_path = os.path.join(os.path.dirname(__file__), "run_report_template.html")
    with open(template_path, "r") as f:
        template = f.read()
    title = f"{report['run_id']} — real vs. mapa"
    payload = json.dumps(report, default=str)
    # JSON can legally contain "</script>" inside a string value; escape it so
    # the browser doesn't parse it as the end of the embedding <script> tag.
    payload = payload.replace("</script>", "<\\/script>")
    html = template.replace("__TITLE__", title).replace("__REPORT_JSON__", payload)
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id", nargs="?", default=None)
    ap.add_argument("--out", default=None, help="directorio donde escribir el JSON (por defecto no escribe archivo)")
    ap.add_argument("--html", default=None, help="ruta donde escribir el informe HTML (Gantt + tabla)")
    ap.add_argument("--pdf", default=None, help="ruta donde escribir el informe en PDF (Gantt + tabla, paginado)")
    args = ap.parse_args()

    report = build_report(args.run_id)
    _print_table(report)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f"run_report_{report['run_id']}.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nJSON escrito en {path}")

    if args.html:
        os.makedirs(os.path.dirname(args.html) or ".", exist_ok=True)
        with open(args.html, "w") as f:
            f.write(render_html(report))
        print(f"HTML escrito en {args.html}")

    if args.pdf:
        from shipyard_pnp.factory.run_report_pdf import render_pdf
        os.makedirs(os.path.dirname(args.pdf) or ".", exist_ok=True)
        render_pdf(report, args.pdf)
        print(f"PDF escrito en {os.path.abspath(args.pdf)}")


if __name__ == "__main__":
    main()
