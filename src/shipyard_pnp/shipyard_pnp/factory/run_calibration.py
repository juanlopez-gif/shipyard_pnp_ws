"""
Recalibración de ciclos: agrega real vs. nominal (simulado, ya calibrado en
shipyard_sim.Config) por (entidad, tarea) a través de varias corridas
COMPLETED, igual que results/calibracion_ciclos_20260706.md pero reutilizando
run_report.build_report() en vez de recalcular nada a mano -- el "nominal"
de cada fila sale directo de sim_dur (que ya corre la simulación real con la
config actual), no de una fórmula reescrita aquí.

Uso:
    python3 -m shipyard_pnp.factory.run_calibration [--exclude RUN_ID ...] [--md OUT.md] [--json OUT.json]

Sin --exclude usa todas las corridas con status=COMPLETED en production_run.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics as stats
from datetime import date

import psycopg2.extras

from shipyard_pnp.factory.run_report import _SCHEMA, _connect, build_report

_THRESH_REVISAR = 5.0
_THRESH_DESCALIBRADO = 15.0


def _fetch_completed_runs(conn, exclude: set[str]) -> list[str]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        f"""SELECT run_id FROM {_SCHEMA}.production_run
            WHERE status = 'COMPLETED' ORDER BY started_at ASC"""
    )
    return [r["run_id"] for r in cur.fetchall() if r["run_id"] not in exclude]


def _estado(diff_pct: float | None) -> str:
    if diff_pct is None:
        return "SIN_MODELO"
    a = abs(diff_pct)
    if a > _THRESH_DESCALIBRADO:
        return "DESCALIBRADO"
    if a > _THRESH_REVISAR:
        return "REVISAR"
    return "OK"


def build_calibration(run_ids: list[str]) -> dict:
    buckets: dict[tuple[str, str], dict] = {}
    per_run_errors = []

    for run_id in run_ids:
        try:
            report = build_report(run_id)
        except SystemExit as exc:
            per_run_errors.append(f"{run_id}: {exc}")
            continue
        for row in report["rows"]:
            if row["status"] == "discarded" or row["sim_dur"] is None or row["real_dur"] is None:
                continue
            key = (row["entity"], row["task"])
            b = buckets.setdefault(key, {"reals": [], "sims": []})
            b["reals"].append(row["real_dur"])
            b["sims"].append(row["sim_dur"])

    rows = []
    for (entity, task), b in sorted(buckets.items()):
        reals = b["reals"]
        n = len(reals)
        if n == 0:
            continue
        nominal = round(stats.mean(b["sims"]), 2)
        real_avg = round(stats.mean(reals), 2)
        diff = round(real_avg - nominal, 2)
        diff_pct = round(diff / nominal * 100, 1) if nominal else None
        rows.append({
            "entity": entity,
            "task": task,
            "n": n,
            "real_avg": real_avg,
            "real_min": round(min(reals), 2),
            "real_max": round(max(reals), 2),
            "real_std": round(stats.pstdev(reals), 2) if n > 1 else 0.0,
            "nominal": nominal,
            "diff": diff,
            "diff_pct": diff_pct,
            "estado": _estado(diff_pct),
        })

    return {
        "generated_on": str(date.today()),
        "runs_used": run_ids,
        "run_errors": per_run_errors,
        "rows": rows,
    }


def render_markdown(cal: dict) -> str:
    lines = [
        f"# Calibración de ciclos — comparación real vs modelo — {cal['generated_on']}",
        "",
        f"Corridas usadas ({len(cal['runs_used'])}):",
        "",
    ]
    lines += [f"- `{r}`" for r in cal["runs_used"]]
    if cal["run_errors"]:
        lines += ["", "Corridas excluidas por error al leerlas:"]
        lines += [f"- {e}" for e in cal["run_errors"]]
    lines += [
        "",
        "| Entidad | Tarea | n | Real avg (s) | min | max | std | Nominal (s) | Diff (s) | Diff % | Estado |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in cal["rows"]:
        lines.append(
            f"| {r['entity']} | {r['task']} | {r['n']} | {r['real_avg']} | {r['real_min']} | "
            f"{r['real_max']} | {r['real_std']} | {r['nominal']} | {r['diff']:+} | {r['diff_pct']:+}% | {r['estado']} |"
        )
    lines += [
        "",
        f"**Estado**: OK = <{_THRESH_REVISAR:.0f}% diff · REVISAR = {_THRESH_REVISAR:.0f}-{_THRESH_DESCALIBRADO:.0f}% · "
        f"DESCALIBRADO = >{_THRESH_DESCALIBRADO:.0f}% · SIN_MODELO = tarea sin sim_dur registrado.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exclude", nargs="*", default=[], help="run_id(s) a excluir del análisis")
    ap.add_argument("--md", default=None, help="ruta donde escribir el informe en Markdown")
    ap.add_argument("--json", default=None, help="ruta donde escribir el JSON crudo")
    args = ap.parse_args()

    conn = _connect()
    try:
        run_ids = _fetch_completed_runs(conn, set(args.exclude))
    finally:
        conn.close()

    if not run_ids:
        raise SystemExit("No hay corridas COMPLETED tras aplicar --exclude")

    cal = build_calibration(run_ids)
    md = render_markdown(cal)
    print(md)

    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w") as f:
            json.dump(cal, f, indent=2, default=str)
        print(f"JSON escrito en {os.path.abspath(args.json)}")

    if args.md:
        os.makedirs(os.path.dirname(args.md) or ".", exist_ok=True)
        with open(args.md, "w") as f:
            f.write(md)
        print(f"Markdown escrito en {os.path.abspath(args.md)}")


if __name__ == "__main__":
    main()
