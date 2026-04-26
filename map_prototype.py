#!/usr/bin/env python3
"""Prototype: Noirleans neighborhood map rendered with Rich."""

from rich.console import Console
from rich.text import Text

console = Console()

W, H = 94, 31

canvas       = [[' ']   * W for _ in range(H)]
styles       = [[None]  * W for _ in range(H)]
box_interior = [[False] * W for _ in range(H)]

FACTION_COLORS = {
    'P': 'bold blue',       # NOPD
    'R': 'bold red',        # Rossi Crime Family
    'C': 'bold yellow',     # Castellano Crime Family
    'I': 'bold green',      # ILA Local 231 (white longshoremen)
    'L': 'bold magenta',    # Colored Longshoremen's Association
    'S': 'bold cyan',       # Shorties (Long machine political faction)
    'T': 'bold white',      # Tallboys (old establishment opposition)
    'A': 'yellow',          # Archdiocese of New Orleans
}


def put(r, c, ch, style=None):
    if 0 <= r < H and 0 <= c < W:
        canvas[r][c] = ch
        if style is not None:
            styles[r][c] = style


def hline(r, c1, c2, ch='─', style='white'):
    for c in range(c1, c2 + 1):
        put(r, c, ch, style)


def vline(c, r1, r2, ch='│', style='white'):
    for r in range(r1, r2 + 1):
        put(r, c, ch, style)


def box(r, c, h, w, style='white', double=False):
    if double:
        tl, tr, bl, br, h_ch, v_ch = '╔', '╗', '╚', '╝', '═', '║'
    else:
        tl, tr, bl, br, h_ch, v_ch = '┌', '┐', '└', '┘', '─', '│'
    put(r, c,         tl, style); put(r, c + w - 1,         tr, style)
    put(r + h - 1, c, bl, style); put(r + h - 1, c + w - 1, br, style)
    hline(r,         c + 1, c + w - 2, h_ch, style)
    hline(r + h - 1, c + 1, c + w - 2, h_ch, style)
    vline(c,         r + 1, r + h - 2, v_ch, style)
    vline(c + w - 1, r + 1, r + h - 2, v_ch, style)


def txt(r, c, s, style=None):
    for i, ch in enumerate(s):
        put(r, c + i, ch, style)


def center_in(r, c, w, s, style=None):
    pad = max(0, (w - len(s)) // 2)
    txt(r, c + pad, s[:w], style)


BW, BH = 16, 5  # neighborhood box width / height


def neighborhood(r, c, name, factions, danger_level, here=False):
    box(r, c, BH, BW, style='bold white' if here else 'dim white', double=here)
    for ri in range(r + 1, r + BH - 1):
        for ci in range(c + 1, c + BW - 1):
            box_interior[ri][ci] = True

    # Name row
    center_in(r + 1, c + 1, BW - 2, name, 'bold white')

    # Faction codes — centered in the box interior, stepping by 2
    factions_width = max(0, len(factions) * 2 - 1)
    fc = c + 1 + (BW - 2 - factions_width) // 2
    for code in factions:
        put(r + 2, fc, code, FACTION_COLORS.get(code, 'white'))
        fc += 2

    # Danger bar on its own row (r+3)
    if danger_level <= 2:
        bar_ch, bar_style = '░', 'green'
    elif danger_level <= 3:
        bar_ch, bar_style = '▒', 'yellow'
    else:
        bar_ch, bar_style = '▓', 'bold red'

    bar_start = c + 1 + (BW - 2 - 5) // 2
    for i in range(5):
        if i < danger_level:
            put(r + 3, bar_start + i, bar_ch, bar_style)
        else:
            put(r + 3, bar_start + i, '·', 'dim white')


# ── Outer frame ───────────────────────────────────────────────────────────────

hline(0,     0, W - 1, '═', 'bold white')
hline(H - 1, 0, W - 1, '═', 'bold white')
put(0,     0,     '╔', 'bold white'); put(0,     W - 1, '╗', 'bold white')
put(H - 1, 0,     '╚', 'bold white'); put(H - 1, W - 1, '╝', 'bold white')
for r in range(1, H - 1):
    put(r, 0,     '║', 'bold white')
    put(r, W - 1, '║', 'bold white')

title = "  N O I R L E A N S  ·  1 9 3 5  "
txt(0, (W - len(title)) // 2, title, 'bold yellow')

# ── Water ─────────────────────────────────────────────────────────────────────

inner = W - 2  # 92

# Lake Pontchartrain — straight line across the top
lake_label = " Lake Pontchartrain "
waves = (inner - len(lake_label)) // 2
lake_line = "≋" * waves + lake_label + "≋" * (inner - waves - len(lake_label))
txt(1, 1, lake_line[:inner], 'bold cyan')

# Mississippi River — curved path approximating the real crescent.
# The crescent means the river reaches its northernmost point (lowest row number)
# at the French Quarter, and curves south (higher row) at Uptown and Lower 9th.
# Control points are (col, top-bank-row).
RIVER_CTRL = [
    ( 1, 21),  # entering from upper-left (upriver / northwest)
    (15, 22),  # Uptown — river curves south, away from the city
    (30, 21),  # Garden / CBD — transitioning toward the crescent peak
    (45, 20),  # French Quarter — crescent peak (min row = 20, just below R4 boxes)
    (58, 21),  # Marigny — transitioning back south
    (74, 22),  # Bywater / Lower 9th — river curves south again
    (93, 21),  # exiting to the lower-right (downriver / southeast)
]

def river_row_at(col):
    for i in range(len(RIVER_CTRL) - 1):
        c1, r1 = RIVER_CTRL[i]
        c2, r2 = RIVER_CTRL[i + 1]
        if c1 <= col <= c2:
            t = (col - c1) / (c2 - c1)
            return round(r1 + t * (r2 - r1))
    return RIVER_CTRL[-1][1]

# Flood-fill from a fixed top row down to the computed local bottom.
# Rows 26-28 are solid at every column (no gaps).
# At the extremes (Uptown, Lower 9th) the river grows 1-2 rows deeper,
# showing the crescent: narrowest band (3 rows) at the French Quarter,
# widest (5 rows) at Uptown and Lower 9th where the river curves south.
GLOBAL_TOP = 20
for col in range(1, W - 1):
    r = river_row_at(col)
    for rr in range(GLOBAL_TOP, r + 3):
        put(rr, col, '≋', 'bold cyan')

# River label — centred in the solid band
river_label = " Mississippi River "
lc = (W - len(river_label)) // 2
txt(GLOBAL_TOP + 1, lc, river_label, 'bold cyan')

# ── Neighborhoods (r, c, name, factions, danger 1-5, here?) ──────────────────
#
# Column anchors (left edge of each box):
#   A=2   B=20   C=38   D=56   E=72
#
# Geographic logic (west→east along the river):
#   A: Uptown / Garden District (far upriver)
#   B: Irish Channel / CBD (center-left)
#   C: French Quarter / Tremé above (the river bend)
#   D: Marigny / 7th Ward above (downriver)
#   E: Bywater / Lower 9th (far downriver)
#
# Mid-City is inland/north, sits above the CBD (col B)
# Tremé is directly north of the French Quarter (col C)
# 7th Ward is northeast of the French Quarter, above Marigny (col D)
# Algiers is directly across the river from the French Quarter (col C)

A, B, C, D, E = 2, 20, 38, 56, 74  # 2-char gap between each box (BW=16)
R1, R2, R3, R4 = 3, 3, 9, 15

neighborhood(R2, B, "MID-CITY",    ["P", "S"],         2)
neighborhood(R2, C, "TREME",       ["P", "L"],         3)
neighborhood(R2, D, "7TH WARD",    ["P", "L"],         3)

neighborhood(R3, A, "GARDEN DIST", ["P", "T"],         1)
neighborhood(R3, B, "CBD",         ["P", "R", "S"],    2)
neighborhood(R3, C, "FRENCH QTR",  ["P", "R", "A"],    2, here=True)
neighborhood(R3, D, "MARIGNY",     ["C"],              3)

neighborhood(R4, A, "UPTOWN",      ["P", "T"],         2)
neighborhood(R4, B, "IRISH CH.",   ["I", "P"],         4)
neighborhood(R4, D, "BYWATER",     ["I", "L"],         3)
neighborhood(R4, E, "LOWER 9TH",   ["L", "P"],         5)

neighborhood(25, C, "ALGIERS",     ["P", "I"],         4)

# ── Render ────────────────────────────────────────────────────────────────────

LAND_BG = 'on rgb(28,12,2)'    # darkened brown — land between neighborhoods
BOX_BG  = 'on black'           # inside neighborhood boxes

result = Text()
for r in range(H):
    for c in range(W):
        ch = canvas[r][c]
        st = styles[r][c]
        if 1 <= r < H - 1 and 1 <= c < W - 1 and ch != '≋':
            bg = BOX_BG if box_interior[r][c] else LAND_BG
            st = f'{st} {bg}' if st else bg
        result.append(ch, style=st)
    result.append('\n')

console.print(result, end='')
console.print()
console.print(
    "  [bold blue]P[/] NOPD  "
    "[bold red]R[/] Rossi  "
    "[bold yellow]C[/] Castellano  "
    "[bold green]I[/] ILA 231  "
    "[bold magenta]L[/] Col. Longshoremen  "
    "[bold cyan]S[/] Shorties  "
    "[bold white]T[/] Tallboys  "
    "[yellow]A[/] Archdiocese"
)
console.print("  Danger: [green]░[/] low  [yellow]▒[/] medium  [bold red]▓[/] high")
