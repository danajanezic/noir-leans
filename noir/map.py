import sqlite3
from io import StringIO

from rich.console import Console
from rich.text import Text

from noir.persistence.repository import get_all_neighborhoods, get_neighborhood_factions

SLUG_TO_CODE = {
    "nopd":                 "P",
    "rossi":                "R",
    "castellano":           "C",
    "ila_231":              "I",
    "colored_longshoremen": "L",
    "shorties":             "S",
    "tallboys":             "T",
    "archdiocese":          "A",
}

NEIGHBORHOOD_LAYOUT = {
    "mid_city":         (3,  20, "MID-CITY"),
    "treme":            (3,  38, "TREME"),
    "seventh_ward":     (3,  56, "7TH WARD"),
    "garden_district":  (9,   2, "GARDEN DIST"),
    "cbd":              (9,  20, "CBD"),
    "french_quarter":   (9,  38, "FRENCH QTR"),
    "marigny":          (9,  56, "MARIGNY"),
    "uptown":           (15,  2, "UPTOWN"),
    "irish_channel":    (15, 20, "IRISH CH."),
    "bywater":          (15, 56, "BYWATER"),
    "lower_ninth":      (15, 74, "LOWER 9TH"),
    "algiers":          (25, 38, "ALGIERS"),
}

FACTION_COLORS = {
    "P": "bold blue",
    "R": "bold red",
    "C": "bold yellow",
    "I": "bold green",
    "L": "bold magenta",
    "S": "bold cyan",
    "T": "bold white",
    "A": "yellow",
}

LOCATION_MARKER_COLORS = {
    "✦": "bold red",
    "⌂": "white",
    "⚑": "bold yellow",
    "◉": "bold cyan",
    "☎": "bold green",
    "✝": "dim white",
    "⚜": "bold yellow",
}

FACTION_LEGEND = (
    "  [bold blue]P[/] NOPD  "
    "[bold red]R[/] Rossi  "
    "[bold yellow]C[/] Castellano  "
    "[bold green]I[/] ILA 231  "
    "[bold magenta]L[/] Col. Longshoremen  "
    "[bold cyan]S[/] Shorties  "
    "[bold white]T[/] Tallboys  "
    "[yellow]A[/] Archdiocese"
)

MARKER_LEGEND = (
    "  [bold red]✦[/] Crime scene  "
    "[white]⌂[/] Premises  "
    "[bold yellow]⚑[/] Stakeout  "
    "[bold cyan]◉[/] Evidence  "
    "[bold green]☎[/] Contact  "
    "[dim white]✝[/] Church/mortuary  "
    "[bold yellow]⚜[/] Bar/tavern"
)


def render_map(conn: sqlite3.Connection, current_neighborhood_slug: str, markers: dict[str, list[str]]) -> str:
    W, H = 94, 31
    BW, BH = 16, 5

    canvas          = [[" "]   * W for _ in range(H)]
    styles          = [[None]  * W for _ in range(H)]
    box_interior    = [[False] * W for _ in range(H)]
    active_interior = [[False] * W for _ in range(H)]

    def put(r, c, ch, style=None):
        if 0 <= r < H and 0 <= c < W:
            canvas[r][c] = ch
            if style is not None:
                styles[r][c] = style

    def hline(r, c1, c2, ch="─", style="white"):
        for c in range(c1, c2 + 1):
            put(r, c, ch, style)

    def vline(c, r1, r2, ch="│", style="white"):
        for r in range(r1, r2 + 1):
            put(r, c, ch, style)

    def box(r, c, h, w, style="white", double=False, title=None):
        if double:
            tl, tr, bl, br, h_ch, v_ch = "╔", "╗", "╚", "╝", "═", "║"
        else:
            tl, tr, bl, br, h_ch, v_ch = "┌", "┐", "└", "┘", "─", "│"
        put(r, c,         tl, style); put(r, c + w - 1,         tr, style)
        put(r + h - 1, c, bl, style); put(r + h - 1, c + w - 1, br, style)
        hline(r,         c + 1, c + w - 2, h_ch, style)
        hline(r + h - 1, c + 1, c + w - 2, h_ch, style)
        vline(c,         r + 1, r + h - 2, v_ch, style)
        vline(c + w - 1, r + 1, r + h - 2, v_ch, style)
        if title:
            label = f" {title} "[: w - 2]
            pad = max(0, (w - 2 - len(label)) // 2)
            txt(r, c + 1 + pad, label, style)

    def txt(r, c, s, style=None):
        for i, ch in enumerate(s):
            put(r, c + i, ch, style)

    def neighborhood_box(slug, row, col, name, factions, danger_level, here=False, hood_markers=None):
        box(row, col, BH, BW, style="bold white" if here else "dim white", double=here, title=name)
        for ri in range(row + 1, row + BH - 1):
            for ci in range(col + 1, col + BW - 1):
                box_interior[ri][ci] = True
                if here:
                    active_interior[ri][ci] = True

        codes = [SLUG_TO_CODE.get(f, f) for f in factions]
        factions_width = max(0, len(codes) * 2 - 1)
        fc = col + 1 + (BW - 2 - factions_width) // 2
        for code in codes:
            put(row + 1, fc, code, FACTION_COLORS.get(code, "white"))
            fc += 2

        if danger_level <= 2:
            bar_ch, bar_style = "░", "green"
        elif danger_level <= 3:
            bar_ch, bar_style = "▒", "yellow"
        else:
            bar_ch, bar_style = "▓", "bold red"

        bar_start = col + 1 + (BW - 2 - 5) // 2
        for i in range(5):
            if i < danger_level:
                put(row + 2, bar_start + i, bar_ch, bar_style)
            else:
                put(row + 2, bar_start + i, "·", "dim white")

        if hood_markers:
            markers_width = max(0, len(hood_markers) * 2 - 1)
            mc = col + 1 + (BW - 2 - markers_width) // 2
            for sym in hood_markers:
                put(row + 3, mc, sym, LOCATION_MARKER_COLORS.get(sym, "white"))
                mc += 2

    hoods_by_slug = {h["slug"]: h for h in get_all_neighborhoods(conn)}
    factions_by_slug = {slug: get_neighborhood_factions(conn, slug) for slug in NEIGHBORHOOD_LAYOUT}

    hline(0,     0, W - 1, "═", "dim yellow")
    hline(H - 1, 0, W - 1, "═", "dim yellow")
    put(0,     0,     "╔", "dim yellow"); put(0,     W - 1, "╗", "dim yellow")
    put(H - 1, 0,     "╚", "dim yellow"); put(H - 1, W - 1, "╝", "dim yellow")
    for r in range(1, H - 1):
        put(r, 0,     "║", "dim yellow")
        put(r, W - 1, "║", "dim yellow")

    title = "  N O I R L E A N S  ·  1 9 3 5  "
    txt(0, (W - len(title)) // 2, title, "dim yellow")

    inner = W - 2
    lake_label = " Lake Pontchartrain "
    waves = (inner - len(lake_label)) // 2
    lake_line = "≋" * waves + lake_label + "≋" * (inner - waves - len(lake_label))
    txt(1, 1, lake_line[:inner], "cyan")

    RIVER_CTRL = [
        ( 1, 21),
        (15, 22),
        (30, 21),
        (45, 20),
        (58, 21),
        (74, 22),
        (93, 21),
    ]

    def river_row_at(col):
        for i in range(len(RIVER_CTRL) - 1):
            c1, r1 = RIVER_CTRL[i]
            c2, r2 = RIVER_CTRL[i + 1]
            if c1 <= col <= c2:
                t = (col - c1) / (c2 - c1)
                return round(r1 + t * (r2 - r1))
        return RIVER_CTRL[-1][1]

    GLOBAL_TOP = 20
    for col in range(1, W - 1):
        r = river_row_at(col)
        for rr in range(GLOBAL_TOP, r + 3):
            put(rr, col, "≋", "cyan")

    river_label = " Mississippi River "
    lc = (W - len(river_label)) // 2
    txt(GLOBAL_TOP + 1, lc, river_label, "cyan")

    for slug, (row, col, name) in NEIGHBORHOOD_LAYOUT.items():
        hood = hoods_by_slug.get(slug)
        danger = hood["danger"] if hood and hood["danger"] is not None else 1
        factions = factions_by_slug.get(slug, [])
        here = (slug == current_neighborhood_slug)
        hood_markers = markers.get(slug)
        neighborhood_box(slug, row, col, name, factions, danger, here=here, hood_markers=hood_markers)

    LAND_BG = "on rgb(28,12,2)"
    BOX_BG  = "on black"

    def _danger_row(symbol, label, style):
        t = Text()
        t.append("   ")
        t.append(symbol, style=style)
        t.append(f" {label}", style="dim white")
        return t

    _key_items = [
        Text("   Danger:", style="bold white"),
        Text(""),
        _danger_row("░", "low",    "green"),
        Text(""),
        _danger_row("▒", "medium", "yellow"),
        Text(""),
        _danger_row("▓", "high",   "bold red"),
    ]
    _key_start = (H - len(_key_items)) // 2
    DANGER_SIDE = {_key_start + i: t for i, t in enumerate(_key_items)}

    def _dim(st):
        if st is None:
            return None
        return st.replace("bold ", "")

    result = Text()
    for r in range(H):
        row_text = Text()
        run_ch = []
        run_st = None
        for c in range(W):
            ch = canvas[r][c]
            st = styles[r][c]
            if 1 <= r < H - 1 and 1 <= c < W - 1 and ch != "≋":
                bg = BOX_BG if box_interior[r][c] else LAND_BG
                st = f"{st} {bg}" if st else bg
                if box_interior[r][c] and not active_interior[r][c]:
                    st = _dim(st)
            if st == run_st:
                run_ch.append(ch)
            else:
                if run_ch:
                    row_text.append("".join(run_ch), style=run_st)
                run_ch = [ch]
                run_st = st
        if run_ch:
            row_text.append("".join(run_ch), style=run_st)
        if r in DANGER_SIDE:
            row_text.append_text(DANGER_SIDE[r])
        result.append_text(row_text)
        result.append("\n")

    sio = StringIO()
    console = Console(file=sio, highlight=False, force_terminal=True, width=120)
    console.print(result, end="")
    return sio.getvalue()
