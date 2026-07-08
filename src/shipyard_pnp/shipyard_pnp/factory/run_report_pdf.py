"""
Genera un PDF real (vectorial, con reportlab) del informe de run_report --
sin pasar por el navegador ni por dialogos de impresion, para que el archivo
quede exactamente en la ruta que se indique por --pdf.

El Gantt ocupa una única página horizontal, tan ancha como haga falta para
cubrir toda la corrida sin comprimir ni cortar nada (PDF admite páginas de
tamaño arbitrario). La tabla de detalle va aparte, paginada en A4 normal.
"""

from __future__ import annotations

import math

ENTITY_ORDER = ["xarm2", "xarm1", "laser", "bantam", "robot2", "robot1"]

_STATUS_COLOR = {
    "matched":   (0.79, 0.48, 0.18),
    "followed":  (0.79, 0.48, 0.18),
    "timeout":   (0.75, 0.22, 0.17),
    "discarded": (0.54, 0.58, 0.63),
    "no_sim":    (0.54, 0.58, 0.63),
}
_SIM_COLOR = (0.18, 0.62, 0.56)
_PIECE_COLOR = {
    "BLUE":  (0.23, 0.44, 0.82),
    "RED":   (0.82, 0.28, 0.23),
    "GREEN": (0.29, 0.62, 0.34),
}
_STATUS_LABEL = {
    "matched": "coincidio", "followed": "espero -> coincidio",
    "timeout": "timeout del mapa", "discarded": "descartado", "no_sim": "sin mapa",
}


def render_pdf(report: dict, path: str) -> None:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm

    PAGE_W, PAGE_H = landscape(A4)
    MARGIN = 14 * mm
    LABEL_W = 26 * mm
    LANE_H = 13 * mm

    rows = report["rows"]
    by_entity: dict = {e: [] for e in ENTITY_ORDER}
    for r in rows:
        by_entity.setdefault(r["entity"], []).append(r)

    maxT = max(
        [report.get("real_total_s") or 0, report.get("sim_total_s") or 0]
        + [(r["real_t"] or 0) + (r["real_dur"] or 4) for r in rows]
        + [(r["sim_t"] or 0) + (r["sim_dur"] or 0) for r in rows if r["sim_t"] is not None]
    )

    c = canvas.Canvas(path, pagesize=(PAGE_W, PAGE_H))

    def draw_header(subtitle: str, page_w: float = PAGE_W) -> None:
        c.setFillColorRGB(0.06, 0.08, 0.1)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(MARGIN, PAGE_H - MARGIN + 6, report["run_id"])
        c.setFont("Helvetica", 8.5)
        c.setFillColorRGB(0.33, 0.39, 0.44)
        c.drawString(MARGIN, PAGE_H - MARGIN - 6, subtitle)
        real_s = report.get("real_total_s")
        sim_s = report.get("sim_total_s")
        if real_s is not None:
            diff = real_s - sim_s
            pct = diff / sim_s * 100 if sim_s else 0
            summary = (
                f"t0 real {report['t0'][11:19]}   t fin real {(report['t_fin'] or '?')[11:19]}   "
                f"real {real_s:.1f}s   simulado {sim_s:.1f}s   diff {diff:+.1f}s ({pct:+.1f}%)"
            )
            c.drawString(MARGIN, PAGE_H - MARGIN - 16, summary)
        c.setStrokeColorRGB(0.83, 0.86, 0.88)
        c.line(MARGIN, PAGE_H - MARGIN - 22, page_w - MARGIN, PAGE_H - MARGIN - 22)

    def draw_legend(y: float) -> None:
        x = MARGIN
        c.setFont("Helvetica", 7.5)
        items = [
            (_STATUS_COLOR["matched"], "real"),
            (_SIM_COLOR, "simulado"),
            (_STATUS_COLOR["timeout"], "timeout del mapa"),
            (_STATUS_COLOR["discarded"], "descartado"),
        ]
        for color, label in items:
            c.setFillColorRGB(*color)
            c.rect(x, y, 5 * mm, 2.6 * mm, fill=1, stroke=0)
            c.setFillColorRGB(0.2, 0.24, 0.27)
            c.drawString(x + 6 * mm, y, label)
            x += 6 * mm + c.stringWidth(label, "Helvetica", 7.5) + 8 * mm

    # ── Gantt: one wide page ─────────────────────────────────────────────────
    # PDF pages can be arbitrarily wide (well under the 200in/side spec limit
    # even for a long run), so the whole timeline fits on one page without
    # compressing or cutting anything. Table pages go back to normal A4
    # landscape afterwards.
    PX_PER_S = 2.4
    gantt_page_w = 2 * MARGIN + LABEL_W + max(maxT, 1) * PX_PER_S
    c.setPageSize((gantt_page_w, PAGE_H))

    gantt_top = PAGE_H - MARGIN - 34 * mm
    lanes_h = len(ENTITY_ORDER) * (LANE_H + 3 * mm)

    draw_header(f"Gantt — real vs. mapa (0–{maxT/60:.0f} min, pagina completa)", page_w=gantt_page_w)
    draw_legend(gantt_top + 6 * mm)

    # time axis gridlines every 60s
    t = 0.0
    c.setFont("Helvetica", 6.5)
    while t <= maxT:
        x = MARGIN + LABEL_W + t * PX_PER_S
        c.setStrokeColorRGB(0.88, 0.9, 0.91)
        c.line(x, gantt_top, x, gantt_top - lanes_h)
        c.setFillColorRGB(0.45, 0.5, 0.55)
        c.drawString(x + 1, gantt_top + 1.5 * mm, f"{int(t/60)}m")
        t += 60

    for i, entity in enumerate(ENTITY_ORDER):
        lane_y = gantt_top - (i + 1) * (LANE_H + 3 * mm)
        if i % 2 == 1:
            c.setFillColorRGB(0.93, 0.95, 0.96)
            c.rect(MARGIN, lane_y, gantt_page_w - 2 * MARGIN, LANE_H + 3 * mm, fill=1, stroke=0)
        c.setFillColorRGB(0.06, 0.08, 0.1)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGIN + 2, lane_y + LANE_H / 2, entity)

        for r in by_entity.get(entity, []):
            if r["sim_t"] is not None:
                x0 = MARGIN + LABEL_W + r["sim_t"] * PX_PER_S
                x1 = MARGIN + LABEL_W + (r["sim_t"] + (r["sim_dur"] or 0)) * PX_PER_S
                c.setFillColorRGB(*_SIM_COLOR)
                c.saveState()
                c.setFillAlpha(0.5)
                c.rect(x0, lane_y + LANE_H / 2 + 0.5 * mm, max(x1 - x0, 0.6 * mm), LANE_H / 2 - 1 * mm, fill=1, stroke=0)
                c.restoreState()

            x0 = MARGIN + LABEL_W + r["real_t"] * PX_PER_S
            x1 = MARGIN + LABEL_W + (r["real_t"] + (r["real_dur"] or 3)) * PX_PER_S
            color = _STATUS_COLOR.get(r["status"], (0.6, 0.6, 0.6))
            if r["status"] == "timeout":
                c.setStrokeColorRGB(*color)
                c.setLineWidth(1)
                c.rect(x0, lane_y + 0.5 * mm, max(x1 - x0, 0.6 * mm), LANE_H / 2 - 1 * mm, fill=0, stroke=1)
            else:
                c.setFillColorRGB(*color)
                c.rect(x0, lane_y + 0.5 * mm, max(x1 - x0, 0.6 * mm), LANE_H / 2 - 1 * mm, fill=1, stroke=0)

    c.showPage()
    c.setPageSize((PAGE_W, PAGE_H))

    # ── Generic paginated table renderer, reused by the three table
    # sections below (chronological detail, by-component detail, transfers).
    row_h = 5.2 * mm
    rows_per_page = int((PAGE_H - 2 * MARGIN - 20 * mm) / row_h)

    def draw_table_pages(section_title: str, headers: list, col_x: list, entries: list) -> None:
        """entries: dicts, either {"kind":"row","values":[...],"dot_color":rgb_or_None}
        or {"kind":"header","label":str} for a group separator (e.g. entity/piece name)."""
        def draw_col_headers(y: float) -> None:
            c.setFont("Helvetica-Bold", 7.5)
            c.setFillColorRGB(0.33, 0.39, 0.44)
            for x, h in zip(col_x, headers):
                c.drawString(x, y, h)
            c.setStrokeColorRGB(0.83, 0.86, 0.88)
            c.line(MARGIN, y - 1.5 * mm, PAGE_W - MARGIN, y - 1.5 * mm)

        n_pages = max(1, math.ceil(len(entries) / rows_per_page))
        for page in range(n_pages):
            draw_header(f"{section_title}  [pagina {page+1}/{n_pages}]")
            y = gantt_top - 4 * mm
            draw_col_headers(y)
            y -= row_h
            chunk = entries[page * rows_per_page:(page + 1) * rows_per_page]
            c.setFont("Helvetica", 7.2)
            zebra = 0
            for entry in chunk:
                if entry["kind"] == "header":
                    c.setFillColorRGB(0.90, 0.93, 0.95)
                    c.rect(MARGIN, y - 1 * mm, PAGE_W - 2 * MARGIN, row_h, fill=1, stroke=0)
                    c.setFillColorRGB(0.06, 0.08, 0.1)
                    c.setFont("Helvetica-Bold", 7.4)
                    c.drawString(MARGIN + 2, y, entry["label"])
                    c.setFont("Helvetica", 7.2)
                    zebra = 0
                    y -= row_h
                    continue
                if zebra % 2 == 1:
                    c.setFillColorRGB(0.95, 0.96, 0.97)
                    c.rect(MARGIN, y - 1 * mm, PAGE_W - 2 * MARGIN, row_h, fill=1, stroke=0)
                zebra += 1
                if entry.get("dot_color"):
                    c.setFillColorRGB(*entry["dot_color"])
                    c.circle(col_x[entry.get("dot_col", 1)] - 2 * mm, y + 1.2 * mm, 0.8 * mm, fill=1, stroke=0)
                c.setFillColorRGB(0.06, 0.08, 0.1)
                for x, v in zip(col_x, entry["values"]):
                    c.drawString(x, y, v)
                y -= row_h
            c.showPage()

    # ── Detalle por ciclo (cronologico) ──────────────────────────────────────
    col_x_cycle = [MARGIN, MARGIN + 28*mm, MARGIN + 90*mm, MARGIN + 120*mm, MARGIN + 135*mm,
                   MARGIN + 160*mm, MARGIN + 185*mm, MARGIN + 210*mm]
    headers_cycle = ["Entidad", "Tarea", "Pieza", "#", "t real (s)", "t mapa (s)", "diff (s)", "Estado"]

    def cycle_row(r: dict) -> dict:
        sim_t = f"{r['sim_t']:.1f}" if r["sim_t"] is not None else "-"
        diff = f"{r['diff']:+.1f}" if r["diff"] is not None else "-"
        return {
            "kind": "row",
            "values": [
                r["entity"], r["task"][:26], r["piece_id"] or "", str(r["cycle_number"] or ""),
                f"{r['real_t']:.1f}", sim_t, diff, _STATUS_LABEL.get(r["status"], r["status"]),
            ],
            "dot_color": _PIECE_COLOR.get(r.get("color")),
            "dot_col": 2,
        }

    draw_table_pages("Detalle por ciclo (cronologico)", headers_cycle, col_x_cycle,
                      [cycle_row(r) for r in rows])

    # ── Detalle por componente ───────────────────────────────────────────────
    by_component_entries = []
    for entity in ENTITY_ORDER:
        entity_rows = by_entity.get(entity, [])
        if not entity_rows:
            continue
        by_component_entries.append({"kind": "header", "label": f"{entity}  ({len(entity_rows)} ciclos)"})
        by_component_entries.extend(cycle_row(r) for r in entity_rows)

    draw_table_pages("Detalle por componente", headers_cycle, col_x_cycle, by_component_entries)

    # ── Transferencias de piezas, agrupadas por pieza ────────────────────────
    col_x_transfer = [MARGIN, MARGIN + 30*mm, MARGIN + 55*mm, MARGIN + 130*mm]
    headers_transfer = ["Pieza", "t (s)", "Desde", "Hacia"]

    transfers = report.get("transfers") or []
    by_piece: dict = {}
    for t in transfers:
        by_piece.setdefault(t["piece_id"], []).append(t)

    def _piece_sort_key(piece_id: str):
        digits = "".join(ch for ch in piece_id if ch.isdigit())
        return int(digits) if digits else piece_id

    transfer_entries = []
    for piece_id in sorted(by_piece, key=_piece_sort_key):
        hops = by_piece[piece_id]
        color = None
        for r in rows:
            if r["piece_id"] == piece_id and r.get("color") in _PIECE_COLOR:
                color = r["color"]
                break
        transfer_entries.append({"kind": "header", "label": f"{piece_id}  ({len(hops)} movimientos)"})
        for hop in hops:
            transfer_entries.append({
                "kind": "row",
                "values": ["", f"{hop['t']:.1f}", hop["from_loc"], hop["to_loc"]],
                "dot_color": _PIECE_COLOR.get(color),
                "dot_col": 0,
            })

    if transfer_entries:
        draw_table_pages("Transferencias de piezas", headers_transfer, col_x_transfer, transfer_entries)

    c.save()
