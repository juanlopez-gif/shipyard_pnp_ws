"""
Auditoría exhaustiva de una corrida: reutiliza run_report.build_report() para
la comparación ciclo a ciclo real vs. simulación, y añade encima las
comprobaciones de integridad que no cubre esa herramienta: fallos de
hardware, alarmas del dashboard en vivo (cruzadas contra la reconstrucción
offline para descartar ruido de muestreo), orden del optimizador vs. lo
realmente ejecutado, ruta física + destino final de cada pieza (contra
unloading_rules._final_destination, la regla real de producción), y
consistencia de forma entre las tres estaciones de visión.

Uso:
    python3 -m shipyard_pnp.factory.run_audit [RUN_ID] --html OUT.html

Sin RUN_ID usa la corrida más reciente en production_run (igual que
run_report.py). Genera el mismo tipo de informe HTML que run_report.py --html,
mismo patrón de plantilla (run_audit_template.html + JSON inyectado).
"""

from __future__ import annotations

import argparse
import json
import os
import re

import psycopg2.extras

from shipyard_pnp.factory.run_report import _SCHEMA, _connect, build_report
from shipyard_pnp.factory.planner.unloading_rules import _final_destination


def _fetch_optimizer(conn, run_id: str) -> dict | None:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT original_order, best_order, saving_s, saving_pct, applied
            FROM {_SCHEMA}.optimizer_run WHERE run_id = %s
            ORDER BY created_at DESC LIMIT 1""",
        (run_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _fetch_executed_order(conn, run_id: str) -> list[str]:
    """xarm2's real MOVE_PIECE dispatch order, mapped piece_id -> color via
    the `piece` table (color is always populated there; shape isn't, see
    run_audit's own vision-consistency check for shape instead)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT cl.piece_id, p.color
            FROM {_SCHEMA}.command_log cl
            JOIN {_SCHEMA}.piece p ON p.piece_id = cl.piece_id AND p.run_id = cl.run_id
            WHERE cl.run_id = %s AND cl.resource_id = 'xarm2' AND cl.task_name = 'MOVE_PIECE'
            ORDER BY cl.sent_at ASC""",
        (run_id,),
    )
    return [r["color"] for r in cur.fetchall()]


def _fetch_alarms(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT triggered_at, severity, resource_id, description
            FROM {_SCHEMA}.alarm_event WHERE run_id = %s ORDER BY triggered_at ASC""",
        (run_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _fetch_hardware_failures(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT published_at, resource_id, code, result->>'reason' AS reason
            FROM {_SCHEMA}.status_log
            WHERE run_id = %s AND task_state = 'FAILED'
            ORDER BY published_at ASC""",
        (run_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _fetch_vision(conn, run_id: str) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT started_at, vision_system, piece_id, detected_color, detected_shape
            FROM {_SCHEMA}.vision_detection WHERE run_id = %s
            ORDER BY started_at ASC""",
        (run_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def _fetch_queue_depth(conn, run_id: str, location: str) -> list[int]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT depth FROM {_SCHEMA}.queue_depth_sample
            WHERE run_id = %s AND location = %s ORDER BY sampled_at ASC""",
        (run_id, location),
    )
    return [r["depth"] for r in cur.fetchall()]


_ALARM_RE = re.compile(r"se esperaba (\S+) #(\d+)")
# 2026-07-08: an intruder piece (forced SCRAP, never planned) triggers its
# OWN alarms by design -- "MAP GUIDANCE INTRUDER" from factory_supervisor's
# map bookkeeping, and sometimes also a "CYCLE UNEXPECTED ... va X" from the
# dashboard's separate live cycle-tracker. Neither matches _ALARM_RE's
# "se esperaba X #N" shape for the ACTUAL (as opposed to expected) task, so
# they used to fall through as "NOT confirmed noise" and clutter the
# checklist even on a run that worked exactly as designed. These two catch
# the "actual" task name from each phrasing so it can be checked against
# cycle_rows' own intruder rows (authoritative -- see run_report.py's
# is_intruder, driven by piece_id, not by alarm text).
_ALARM_ACTUAL_VA_RE = re.compile(r"va (\S+) #\d+")
_ALARM_ACTUAL_INTRUDER_RE = re.compile(r"ciclo no esperado \((\S+)\)")


def _cross_check_alarms(alarms: list[dict], cycle_rows: list[dict]) -> list[dict]:
    """For each live alarm, look up the SAME entity/task/cycle_number in the
    offline reconstruction (cycle_rows, from build_report -- exact
    cycle_event timestamps, no periodic sampling). If that cycle's real
    status there is "matched" (or it waited for the map and still matched),
    the alarm is sampling noise from the live dashboard's periodic poll
    landing on a cycle boundary, not a genuine order violation. Separately,
    an alarm caused by a deliberately-introduced intruder (forced SCRAP) is
    flagged as confirmed_intruder instead -- it's not noise (the order
    violation is real), but it's also not a defect: it's the system
    correctly reacting to an unplanned physical piece, exactly as designed."""
    by_key = {(r["entity"], r["task"], r["cycle_number"]): r for r in cycle_rows}
    intruder_tasks_by_entity: dict[str, set] = {}
    for r in cycle_rows:
        if r["status"] == "intruder":
            intruder_tasks_by_entity.setdefault(r["entity"], set()).add(r["task"])

    out = []
    for a in alarms:
        confirmed_intruder = "INTRUDER" in a["description"]
        if not confirmed_intruder:
            m_actual = _ALARM_ACTUAL_VA_RE.search(a["description"]) or _ALARM_ACTUAL_INTRUDER_RE.search(a["description"])
            if m_actual and m_actual.group(1) in intruder_tasks_by_entity.get(a["resource_id"], set()):
                confirmed_intruder = True

        # Mutually exclusive with confirmed_noise: an alarm caused by an
        # intruder cutting in front of the EXPECTED task (e.g. "se esperaba
        # BANTAM_TO_C4 #1, va CLASSIFY_C2S2_TO_SCRAP #5") also matches the
        # noise regex below once BANTAM_TO_C4 #1 eventually happens for real
        # later in the run -- that's not sampling noise, it's the intruder
        # explanation, so skip the noise check entirely once intruder is
        # already confirmed to avoid double-counting the same alarm.
        confirmed_noise = False
        if not confirmed_intruder:
            m = _ALARM_RE.search(a["description"])
            if m:
                task, num = m.group(1), int(m.group(2))
                row = by_key.get((a["resource_id"], task, num))
                if row and row["status"] in ("matched", "followed"):
                    confirmed_noise = True

        out.append({**a, "confirmed_noise": confirmed_noise, "confirmed_intruder": confirmed_intruder})
    return out


def _routing_for_piece(piece_id: str, vision_by_piece: dict, transfers: list[dict]) -> dict:
    piece_transfers = [t for t in transfers if t["piece_id"] == piece_id]
    path = " → ".join([piece_transfers[0]["from_loc"]] + [t["to_loc"] for t in piece_transfers]) if piece_transfers else ""
    actual_final = piece_transfers[-1]["to_loc"] if piece_transfers else None

    visions = vision_by_piece.get(piece_id, [])
    # robot1_camera is the vision that actually decided the final route in
    # unloading_rules.py -- authoritative ground truth for expected
    # destination. GREEN/RED/BLUE all pass through it (final unload).
    final_vision = next((v for v in reversed(visions) if v["vision_system"] == "robot1_camera"), None)
    color = final_vision["detected_color"] if final_vision else (visions[0]["detected_color"] if visions else None)
    shape = final_vision["detected_shape"] if final_vision else (visions[0]["detected_shape"] if visions else None)

    # 2026-07-08: an intruder (piece_id prefix "intruder-", see piece_tracker.
    # register_intruder) is ALWAYS forced to robot2_scrap regardless of its
    # detected color (classification_rules.py's is_intruder check) -- it
    # never goes through _final_destination(color, shape) like a real,
    # planned piece would. Checking that here instead of blindly applying
    # _final_destination used to flag every correctly-scrapped intruder as a
    # routing "failure" (e.g. a GREEN intruder landing in robot2_scrap
    # instead of final_green_circle) -- the opposite of what actually
    # happened: it went exactly where it was supposed to.
    is_intruder = piece_id.startswith("intruder-")
    if is_intruder:
        expected_final = "robot2_scrap"
    elif color:
        expected_final, _ = _final_destination(color, shape or "UNKNOWN")
    else:
        expected_final = None

    return {
        "piece_id": piece_id,
        "color": color,
        "shape": shape,
        "path": path,
        "final_loc": actual_final,
        "expected_final_loc": expected_final,
        "is_intruder": is_intruder,
        "ok": bool(expected_final) and actual_final == expected_final,
    }


def _vision_consistency_for_piece(piece_id: str, vision_by_piece: dict) -> dict:
    visions = vision_by_piece.get(piece_id, [])
    by_system = {v["vision_system"]: v["detected_shape"] for v in visions}
    shapes = {s for s in by_system.values() if s}
    color = next((v["detected_color"] for v in visions), None)
    return {
        "piece_id": piece_id,
        "color": color,
        "globalvision": by_system.get("globalvision"),
        "robot2_camera": by_system.get("robot2_camera"),
        "robot1_camera": by_system.get("robot1_camera"),
        "consistent": len(shapes) <= 1,
    }


def build_audit(run_id: str | None) -> dict:
    report = build_report(run_id)  # real vs sim, per cycle -- reused as-is
    run_id = report["run_id"]

    conn = _connect()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"SELECT status, started_at, finished_at FROM {_SCHEMA}.production_run WHERE run_id = %s",
            (run_id,),
        )
        run_row = dict(cur.fetchone())

        optimizer = _fetch_optimizer(conn, run_id)
        executed_order = _fetch_executed_order(conn, run_id)
        alarms_raw = _fetch_alarms(conn, run_id)
        failures = _fetch_hardware_failures(conn, run_id)
        vision_raw = _fetch_vision(conn, run_id)
        stack_depth = _fetch_queue_depth(conn, run_id, "initial_stack")
    finally:
        conn.close()

    alarms = _cross_check_alarms(alarms_raw, report["rows"])
    noise_alarms = sum(1 for a in alarms if a["confirmed_noise"])

    vision_by_piece: dict = {}
    for v in vision_raw:
        vision_by_piece.setdefault(v["piece_id"], []).append(v)

    piece_ids = sorted(vision_by_piece.keys(), key=lambda p: p)
    routing = [_routing_for_piece(p, vision_by_piece, report["transfers"]) for p in piece_ids]
    vision = [_vision_consistency_for_piece(p, vision_by_piece) for p in piece_ids]

    optimizer_out = None
    if optimizer:
        applied_matches_execution = (
            executed_order == optimizer["best_order"]
            if executed_order and optimizer["best_order"] else False
        )
        optimizer_out = {
            "original_order": optimizer["original_order"],
            "best_order": optimizer["best_order"],
            "executed_order": executed_order,
            "saving_s": optimizer["saving_s"],
            "saving_pct": optimizer["saving_pct"],
            "applied_flag": optimizer["applied"],
            "applied_matches_execution": applied_matches_execution,
        }

    stack_depth_monotonic = all(b <= a for a, b in zip(stack_depth, stack_depth[1:]))
    stack_depth_reaches_zero = bool(stack_depth) and stack_depth[-1] == 0

    n_discarded = sum(1 for r in report["rows"] if r["status"] == "discarded")
    # 2026-07-08: intruder cycles (piece_id prefix "intruder-") are, by
    # definition, never in the map/simulation -- they're unplanned physical
    # pieces a human introduced. Counting them in this check's denominator
    # made a run with correctly-handled intruders look like it had order
    # violations, when in fact every REAL, planned cycle matched perfectly.
    non_intruder_rows = [r for r in report["rows"] if r["status"] != "intruder"]
    n_intruder_rows = len(report["rows"]) - len(non_intruder_rows)
    n_matched_or_followed = sum(1 for r in non_intruder_rows if r["status"] in ("matched", "followed"))
    routing_ok = sum(1 for r in routing if r["ok"])
    vision_ok = sum(1 for v in vision if v["consistent"])

    checklist = [
        {
            "level": "pass" if n_discarded == 0 else "fail",
            "title": f"{len(report['rows'])}/{len(report['rows'])} cycle_event, {n_discarded} descartados",
            "detail": "Ningún discarded_reason poblado." if n_discarded == 0
                      else f"Descartados: {', '.join(r['task']+' '+str(r['piece_id']) for r in report['rows'] if r['status']=='discarded')}",
        },
        {
            "level": "pass" if not failures else "fail",
            "title": f"{len(failures)} fallos de hardware" if failures else "0 fallos de hardware",
            "detail": "status_log sin task_state=FAILED." if not failures
                      else "; ".join(f"{f['resource_id']}: {f['reason']}" for f in failures),
        },
        {
            "level": "pass" if n_matched_or_followed == len(non_intruder_rows) else "fail",
            "title": f"Orden real vs. simulación: {n_matched_or_followed}/{len(non_intruder_rows)} coinciden"
                     + (f" ({n_intruder_rows} intrusas excluidas, no planeadas)" if n_intruder_rows else ""),
            "detail": "Reconstrucción offline de build_report() -- timestamps exactos de cycle_event, sin muestreo periódico. "
                      "Los ciclos de piezas intrusas (piece_id 'intruder-*') se excluyen: nunca están en el mapa/simulación por definición.",
        },
        {
            "level": "pass" if (stack_depth_monotonic and stack_depth_reaches_zero) else "fail",
            "title": "queue_depth_sample(initial_stack) monotónico y llega a 0",
            "detail": f"Secuencia: {' → '.join(str(d) for d in stack_depth)}" if stack_depth else "Sin muestras.",
        },
        {
            "level": "pass" if routing_ok == len(routing) else "fail",
            "title": f"{routing_ok}/{len(routing)} piezas con destino final correcto"
                     + (f" (incluye {sum(1 for r in routing if r['is_intruder'])} intrusas, esperado = robot2_scrap)"
                        if any(r["is_intruder"] for r in routing) else ""),
            "detail": "piece_transfer vs. unloading_rules._final_destination(color, shape) de la visión final "
                      "(o robot2_scrap para piezas intrusas -- classification_rules.py fuerza SCRAP sin consultar la ruta por color).",
        },
        {
            "level": "pass" if vision_ok == len(vision) else "fail",
            "title": f"{vision_ok}/{len(vision)} piezas con forma consistente en las 3 estaciones",
            "detail": "globalvision (feed) vs. robot2_camera (C2S2) vs. robot1_camera (C3/C4).",
        },
    ]
    if optimizer_out and not optimizer_out["applied_flag"] and optimizer_out["applied_matches_execution"]:
        checklist.append({
            "level": "info",
            "title": "optimizer_run.applied = false pese a haberse aplicado",
            "detail": "El orden ejecutado (command_log) coincide con best_order, pero la columna de bookkeeping no se marcó -- revisar el flujo que la actualiza.",
        })
    intruder_alarms = sum(1 for a in alarms if a["confirmed_intruder"])
    unexplained_alarms = len(alarms) - noise_alarms - intruder_alarms
    if alarms and unexplained_alarms == 0:
        parts = []
        if noise_alarms:
            parts.append(f"{noise_alarms} ruido de muestreo")
        if intruder_alarms:
            parts.append(f"{intruder_alarms} causadas por piezas intrusas (esperado)")
        checklist.append({
            "level": "info",
            "title": f"{len(alarms)} alarmas -- todas explicadas ({', '.join(parts)})",
            "detail": "Ruido: ciclo que build_report() marca matched/followed pese a la alarma -- falso positivo del "
                      "muestreo periódico del dashboard en vivo. Intrusas: MAP GUIDANCE INTRUDER / CYCLE UNEXPECTED "
                      "disparadas por una pieza no planeada forzada a SCRAP -- la alarma es real pero es el "
                      "comportamiento correcto, no un defecto.",
        })
    elif alarms:
        checklist.append({
            "level": "fail",
            "title": f"{len(alarms)} alarmas, {unexplained_alarms} sin explicar (ni ruido ni intrusa confirmada)",
            "detail": "Revisar manualmente -- no todas tienen un ciclo matched/followed ni una intrusa equivalente en la reconstrucción offline.",
        })

    return {
        "run_id": run_id,
        "status": run_row["status"],
        "started_at": str(run_row["started_at"]),
        "finished_at": str(run_row["finished_at"]) if run_row["finished_at"] else None,
        "real_total_s": report["real_total_s"],
        "sim_total_s": report["sim_total_s"],
        "cycles": report["rows"],
        "optimizer": optimizer_out,
        "alarms": alarms,
        "failures": failures,
        "routing": routing,
        "vision": vision,
        "stack_depth": stack_depth,
        "checklist": checklist,
    }


def render_html(audit: dict) -> str:
    template_path = os.path.join(os.path.dirname(__file__), "run_audit_template.html")
    with open(template_path, "r") as f:
        template = f.read()
    title = f"Auditoría — {audit['run_id']}"
    payload = json.dumps(audit, default=str)
    payload = payload.replace("</script>", "<\\/script>")
    return template.replace("__TITLE__", title).replace("__AUDIT_JSON__", payload)


def _print_summary(audit: dict) -> None:
    print(f"Corrida: {audit['run_id']}  ({audit['status']})")
    print(f"Duración real: {audit['real_total_s']}s   simulada: {audit['sim_total_s']}s")
    print()
    for c in audit["checklist"]:
        mark = {"pass": "✓", "fail": "✗", "info": "i"}[c["level"]]
        print(f"[{mark}] {c['title']}")
        print(f"      {c['detail']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id", nargs="?", default=None)
    ap.add_argument("--html", default=None, help="ruta donde escribir el informe HTML")
    ap.add_argument("--json", default=None, help="ruta donde escribir el JSON crudo")
    args = ap.parse_args()

    audit = build_audit(args.run_id)
    _print_summary(audit)

    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w") as f:
            json.dump(audit, f, indent=2, default=str)
        print(f"\nJSON escrito en {args.json}")

    if args.html:
        os.makedirs(os.path.dirname(args.html) or ".", exist_ok=True)
        with open(args.html, "w") as f:
            f.write(render_html(audit))
        print(f"HTML escrito en {os.path.abspath(args.html)}")


if __name__ == "__main__":
    main()
