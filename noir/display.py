import sys
import shutil
import textwrap
import threading
import time
from contextlib import contextmanager
from rich.console import Console
from rich.markup import escape
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich import box

console = Console()
_game_inner_width: int = 0


class _PaddedWriter:
    """Wraps a text stream, inserting a left-margin prefix at the start of each line."""

    def __init__(self, wrapped, prefix: str) -> None:
        self._wrapped = wrapped
        self._prefix = prefix
        self._at_sol = True

    def write(self, s: str) -> int:
        if not s:
            return 0
        out = []
        for ch in s:
            if ch == '\r':
                self._at_sol = False
                out.append(ch)
            elif ch == '\n':
                out.append(ch)
                self._at_sol = True
            else:
                if self._at_sol:
                    out.append(self._prefix)
                    self._at_sol = False
                out.append(ch)
        self._wrapped.write(''.join(out))
        return len(s)

    def flush(self) -> None:
        self._wrapped.flush()

    def fileno(self) -> int:
        return self._wrapped.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._wrapped, 'encoding', 'utf-8')

    @property
    def errors(self) -> str:
        return getattr(self._wrapped, 'errors', 'replace')

    def isatty(self) -> bool:
        return hasattr(self._wrapped, 'isatty') and self._wrapped.isatty()

    def mark_new_line(self) -> None:
        self._at_sol = True


def enable_game_padding() -> None:
    global _game_inner_width
    term_width = shutil.get_terminal_size().columns
    left_pad = max(int(term_width * 0.05), 2)
    right_pad = max(int(term_width * 0.05), 2)
    _game_inner_width = max(term_width - left_pad - right_pad, 40)
    padded = _PaddedWriter(sys.stdout, " " * left_pad)
    sys.stdout = padded  # type: ignore[assignment]
    console._file = padded  # type: ignore[attr-defined]
    console._width = _game_inner_width  # type: ignore[attr-defined]


def _pin_console_width() -> int:
    """Re-pin console._width to _game_inner_width and return it.

    prompt_toolkit resets terminal state between prompts; call this before any
    Rich panel or rule to ensure centering uses the padded inner width, not the
    raw terminal width.
    """
    if _game_inner_width:
        console._width = _game_inner_width  # type: ignore[attr-defined]
    return _game_inner_width or 80


def _thunderstorm_title(title_text: str) -> bool:
    try:
        from terminaltexteffects.effects.effect_thunderstorm import Thunderstorm, ThunderstormConfig
        from terminaltexteffects.engine.terminal import TerminalConfig
        import terminaltexteffects as tte
        term = shutil.get_terminal_size()
        pad = "  "
        inner = pad + title_text + pad
        bar = "═" * len(inner)
        box_text = "\n".join([
            "╔" + bar + "╗",
            "║" + inner + "║",
            "╚" + bar + "╝",
        ])
        effect_cfg = ThunderstormConfig(
            lightning_color=tte.Color("B8C5E8"),
            glowing_text_color=tte.Color("CC2200"),
            text_glow_time=6,
            raindrop_symbols=("\\", ".", ","),
            spark_symbols=("*", ".", "'"),
            spark_glow_color=tte.Color("FF4400"),
            spark_glow_time=18,
            storm_time=7,
            final_gradient_stops=(tte.Color("6B0000"), tte.Color("8B0000"), tte.Color("CC2200")),
            final_gradient_steps=(12,),
            final_gradient_frames=3,
            final_gradient_direction=tte.Gradient.Direction.VERTICAL,
        )
        term_cfg = TerminalConfig(
            tab_width=4,
            xterm_colors=False,
            no_color=False,
            terminal_background_color=tte.Color("000000"),
            existing_color_handling="ignore",
            wrap_text=False,
            frame_rate=60,
            canvas_width=term.columns,
            canvas_height=max(term.lines // 2, 16),
            anchor_canvas="c",
            anchor_text="c",
            ignore_terminal_dimensions=False,
            reuse_canvas=False,
            no_eol=False,
            no_restore_cursor=False,
        )
        effect = Thunderstorm(box_text, effect_config=effect_cfg, terminal_config=term_cfg)
        with effect.terminal_output() as terminal:
            for frame in effect:
                terminal.print(frame)
        return True
    except Exception as _tte_err:
        import logging as _log
        _log.getLogger(__name__).warning("thunderstorm title failed: %s", _tte_err, exc_info=True)
        return False


def _fade_screen_to_black(term_width: int, term_height: int) -> None:
    """Overlay the screen with full-block characters fading from dark red to black, then clear."""
    steps = 18
    row_of_blocks = "█" * term_width
    sys.stdout.write("\033[?25l")
    for step in range(steps, -1, -1):
        t = step / steps
        r, g, b = int(140 * t), int(20 * t), 0  # dark red → black
        color = f"\033[38;2;{r};{g};{b}m"
        for row in range(1, term_height + 1):
            sys.stdout.write(f"\033[{row};1H{color}{row_of_blocks}\033[0m")
        sys.stdout.flush()
        time.sleep(0.05)
    sys.stdout.write("\033[2J\033[?25h")
    sys.stdout.flush()


def _fade_in_block(lines: list[tuple[str, tuple | None]], term_width: int, term_height: int) -> None:
    """Fade a block of (text, rgb_tuple) lines in from black at vertical center."""
    n = len(lines)
    center_top = max(1, (term_height - n) // 2)

    steps = 35
    delay = 2.8 / steps  # ~2.8 seconds total fade

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    for step in range(steps + 1):
        t = (step / steps) ** 1.6  # ease: slow start, quicker finish
        for i, (text, rgb) in enumerate(lines):
            row = center_top + i
            sys.stdout.write(f"\033[{row};1H\033[2K")
            if text and rgb:
                tr, tg, tb = rgb
                r, g, b = int(tr * t), int(tg * t), int(tb * t)
                indent = "" if len(text) >= term_width else " " * max((term_width - len(text)) // 2, 0)
                sys.stdout.write(f"{indent}\033[38;2;{r};{g};{b}m{text}\033[0m")
        sys.stdout.flush()
        time.sleep(delay)

    time.sleep(0.6)  # hold at full brightness before continuing
    sys.stdout.write(f"\033[{center_top + n + 1};1H\033[?25h")
    sys.stdout.flush()


def show_splash() -> None:
    term = shutil.get_terminal_size()
    term_width = max(term.columns, 40)
    term_height = max(term.lines, 24)
    sys.stdout.write("\n" * term_height)
    sys.stdout.flush()

    title_text = "N  O  I  R  L  E  A  N  S"

    if _thunderstorm_title(title_text):
        _fade_screen_to_black(term_width, term_height)
        _GOLD = (160, 130, 0)
        _PALE = (210, 210, 210)
        _RULE_LINE = "─" * term_width
        lines = [
            (_RULE_LINE, _GOLD),
            ("", None),
            ("1  9  3  5", _PALE),
            ("", None),
            ("The Depression is on.", _GOLD),
            ("Everyone is broke.", _GOLD),
            ("Someone is always dead.", _GOLD),
            ("", None),
            (_RULE_LINE, _GOLD),
        ]
        _fade_in_block(lines, term_width, term_height)
        console.print()
        return

    # fallback: original typewritten animation
    content_lines = 15
    top_pad = max((term_height - content_lines) // 2, 0)
    sys.stdout.write("\n" * top_pad)
    sys.stdout.flush()

    console.print(Rule(style="yellow dim"))
    console.print()

    def _typewrite_centered(text: str, delay: float, ansi: str = "") -> None:
        indent = " " * max((term_width - len(text)) // 2, 0)
        sys.stdout.write(indent)
        if ansi:
            sys.stdout.write(ansi)
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            time.sleep(delay)
        if ansi:
            sys.stdout.write("\033[0m")
        sys.stdout.write("\n")
        sys.stdout.flush()

    _DIM_YELLOW = "\033[2;33m"
    lines = [
        ("", 0, "", 0),
        ("N  O  I  R  L  E  A  N  S", 0.07, "", 0),
        ("", 0, "", 0),
        ("1  9  3  5", 0.04, "", 0),
        ("", 0, "", 0),
        ("The Depression is on.", 0.04, _DIM_YELLOW, 0.65),
        ("Everyone is broke.", 0.04, _DIM_YELLOW, 0.65),
        ("Someone is always dead.", 0.04, _DIM_YELLOW, 0),
        ("", 0, "", 0),
    ]
    for text, delay, ansi, pause in lines:
        if not text:
            console.print()
            continue
        if text == "N  O  I  R  L  E  A  N  S":
            pad = "  "
            inner = pad + text + pad
            bar = "═" * len(inner)
            top = "╔" + bar + "╗"
            mid = "║" + inner + "║"
            bot = "╚" + bar + "╝"
            for line in (top, mid, bot):
                _typewrite_centered(line, 0.04, "\033[1;38;2;139;0;0m")
            continue
        _typewrite_centered(text, delay, ansi)
        if pause:
            time.sleep(pause)
    time.sleep(0.4)
    console.print(Rule(style="yellow dim"))
    console.print()


def typewrite(text: str, delay: float = 0.025) -> None:
    width = _game_inner_width if _game_inner_width else max(shutil.get_terminal_size().columns - 2, 40)
    wrapped = textwrap.fill(text, width=width)
    for char in wrapped:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")


def show_narrator(text: str) -> None:
    import noir.audio as audio
    audio.speak(text, audio.NARRATOR_VOICE)
    console.print()
    console.print(f"[dim italic]{escape(text)}[/dim italic]")
    console.print()


def show_conversation_header(name: str) -> None:
    raw = sys.stdout._wrapped if isinstance(sys.stdout, _PaddedWriter) else sys.stdout
    width = shutil.get_terminal_size().columns
    rule = "\u2500" * width
    label = f" talking to {name} "
    pad = max((width - len(label)) // 2, 0)
    line = "\033[36m" + "\u2500" * pad + label + "\u2500" * (width - pad - len(label)) + "\033[0m"
    raw.write("\n" + line + "\n")
    raw.flush()


def show_conversation_footer(name: str) -> None:
    raw = sys.stdout._wrapped if isinstance(sys.stdout, _PaddedWriter) else sys.stdout
    width = shutil.get_terminal_size().columns
    raw.write("\033[36m" + "\u2500" * width + "\033[0m\n")
    raw.flush()


_REL_STAGE_ICON = {
    "cold": "❄",
    "curious": "·",
    "warm": "~",
    "smitten": "♥",
    "devoted": "♥♥",
    "professional": "·",
    "tension": "~",
    "complicated": "≈",
    "committed": "♥♥",
}


def npc_input_prompt(npc_name: str, role: str, rel_stage: str | None) -> str:
    """Prompt for a single line of input during NPC conversation."""
    from prompt_toolkit.shortcuts import PromptSession
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.styles import Style
    from prompt_toolkit.output import create_output

    raw = sys.stdout._wrapped if isinstance(sys.stdout, _PaddedWriter) else sys.stdout
    width = shutil.get_terminal_size().columns

    pt_style = Style.from_dict({
        "bottom-toolbar": "noreverse fg:ansibrightblack bg:default",
        "tb-rule": "noreverse fg:ansicyan dim bg:default",
        "tb-rel": "noreverse fg:ansicyan bg:default",
    })

    hint = "done · bye to end  \u00b7  /go /talk /examine /look /collect /arrest still work"

    def bottom_toolbar():
        rel_part = ""
        if rel_stage:
            icon = _REL_STAGE_ICON.get(rel_stage, "·")
            rel_part = f"  {icon} {rel_stage}"
        rule = "\u2500" * width
        return FormattedText([
            ("class:tb-rule", rule + "\n"),
            ("class:bottom-toolbar", hint),
            ("class:tb-rel", rel_part),
        ])

    def rprompt():
        if rel_stage:
            icon = _REL_STAGE_ICON.get(rel_stage, "·")
            return FormattedText([("class:tb-rel", f"{icon} {rel_stage}  ")])
        return FormattedText([("class:bottom-toolbar", f"{role}  ")])

    import math
    hint_text = "done · bye to end  \u00b7  /go /talk /examine /look /collect /arrest still work"
    hint_rows = max(1, math.ceil(len(hint_text) / width))

    pt_output = create_output(stdout=raw)
    try:
        session = PromptSession(
            bottom_toolbar=bottom_toolbar,
            rprompt=rprompt,
            style=pt_style,
            output=pt_output,
            multiline=False,
        )
        result = session.prompt(f"{npc_name} > ")
    except (EOFError, KeyboardInterrupt):
        raise
    finally:
        # Erase the toolbar rows (rule + hint) and the prompt line itself.
        prompt_len = len(npc_name) + 3 + len(result or "")
        prompt_rows = max(1, math.ceil(prompt_len / width))
        for _ in range(1 + hint_rows + prompt_rows):
            raw.write("\033[1A\033[2K")
        raw.flush()
        if isinstance(sys.stdout, _PaddedWriter):
            sys.stdout.mark_new_line()
    return result


def _car_loop(stop: threading.Event) -> None:
    car = "🚗"
    dot = "·"
    width = max(shutil.get_terminal_size().columns - 6, 20)
    sys.stdout.write("\n")
    while not stop.is_set():
        for i in range(width + 2):
            if stop.is_set():
                break
            car_pos = max(width - i, 0)
            spaces = " " * car_pos
            trail = dot * min(i, width)
            line = (spaces + car + trail)[:width + 4]
            sys.stdout.write(f"\r{line}")
            sys.stdout.flush()
            time.sleep(0.028)
    sys.stdout.write("\r" + " " * (width + 6) + "\r\n")
    sys.stdout.flush()


@contextmanager
def travel_status():
    stop = threading.Event()
    t = threading.Thread(target=_car_loop, args=(stop,), daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()


def show_location_rule() -> None:
    raw_out = sys.stdout._wrapped if isinstance(sys.stdout, _PaddedWriter) else sys.stdout
    width = shutil.get_terminal_size().columns
    tmp = Console(file=raw_out, width=width, force_terminal=True, highlight=False)
    tmp.print()
    tmp.print(Rule(style="dim yellow"))
    tmp.print()
    if isinstance(sys.stdout, _PaddedWriter):
        sys.stdout.mark_new_line()


def show_travel_animation() -> None:
    import random
    car = "🚗"
    dot = "·"
    rain_chars = ["\\", ".", ",", "'"]
    rain_rows = 3
    rain_density = 0.12
    rain_color = "\033[2;34m"  # dim blue
    reset = "\033[0m"
    width = max(shutil.get_terminal_size().columns - 6, 20)

    # Bypass _PaddedWriter so ANSI cursor escapes aren't mangled
    raw = getattr(sys.stdout, '_wrapped', sys.stdout)

    # Reserve space and hide cursor via raw stream
    sys.stdout.write("\n" * (rain_rows + 2))
    sys.stdout.flush()
    raw.write("\033[?25l")
    raw.flush()

    for i in range(width + 2):
        raw.write(f"\033[{rain_rows + 1}A")
        for _ in range(rain_rows):
            cols = []
            for _c in range(width + 4):
                if random.random() < rain_density:
                    cols.append(f"{rain_color}{random.choice(rain_chars)}{reset}")
                else:
                    cols.append(" ")
            raw.write("\r\033[2K" + "".join(cols) + "\n")
        car_pos = max(width - i, 0)
        spaces = " " * car_pos
        trail = dot * min(i, width)
        line = (spaces + car + trail)[:width + 4]
        raw.write(f"\r\033[2K{line}\n")
        raw.flush()
        time.sleep(0.028)

    # Clear the animation block and restore cursor
    raw.write(f"\033[{rain_rows + 1}A")
    for _ in range(rain_rows + 1):
        raw.write("\r\033[2K\n")
    raw.write("\r\033[2K\033[?25h")
    raw.flush()

    # Re-sync _PaddedWriter: cursor is now at start of a new line
    if hasattr(sys.stdout, 'mark_new_line'):
        sys.stdout.mark_new_line()


def fmt_game_time(game_time: int) -> str:
    tod = game_time % 1440
    h, m = divmod(tod, 60)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {period}"


def show_wait_result(new_time: int) -> None:
    time_str = fmt_game_time(new_time)
    console.print(f"\n[dim]Time passes. It is now [bold]{time_str}[/bold].[/dim]")


def show_location(name: str, description: str, npcs_present: list[str],
                  game_time: int | None = None,
                  orgs: list[str] | None = None) -> None:
    import noir.audio as audio
    audio.speak(name, audio.NARRATOR_VOICE)
    audio.set_location(name)
    npc_text = f"\n\n[dim]Present: {', '.join(npcs_present)}[/dim]" if npcs_present else ""
    org_text = f"\n[dim]Controlled by: {', '.join(orgs)}[/dim]" if orgs else ""
    time_text = f"  [dim]{fmt_game_time(game_time)}[/dim]" if game_time is not None else ""
    console.print(Panel(
        f"[italic]{description}[/italic]{npc_text}{org_text}",
        title=f"[bold yellow]{escape(name)}[/bold yellow]{time_text}",
        border_style="yellow",
        box=box.DOUBLE_EDGE,
    ))


def show_dialogue(speaker: str, text: str, delay: float = 0.02) -> None:
    import noir.audio as audio
    audio.speak(text, audio.voice_for(speaker))
    console.print(f"\n[bold cyan]{escape(speaker)}:[/bold cyan]")
    console.print(Markdown(text))
    console.print()


def show_player_turn(text: str) -> None:
    console.print(f"\n[bold red]Player:[/bold red]")
    console.print(Markdown(text))
    console.print()


def show_partner_aside(speaker: str, text: str) -> None:
    import noir.audio as audio
    audio.speak(text, audio.voice_for(speaker))
    console.print(f"\n[dim cyan]{escape(speaker)}:[/dim cyan] [italic]{escape(text)}[/italic]")


_PROMPT_HINT_PLAIN = (
    "/go <place>  \u00b7  /talk <name>  \u00b7  /look  \u00b7  /evidence"
    "  \u00b7  /leads  \u00b7  /suspects  \u00b7  /status  \u00b7  /me  \u00b7  /items  \u00b7  /help"
)


def show_player_input_prompt() -> str:
    from prompt_toolkit.shortcuts import PromptSession
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.styles import Style
    from prompt_toolkit.output import create_output

    raw = sys.stdout._wrapped if isinstance(sys.stdout, _PaddedWriter) else sys.stdout
    width = shutil.get_terminal_size().columns
    rule = "\u2500" * width

    # Print top rule directly (bypasses _PaddedWriter indent)
    raw.write("\n\033[2;33m" + rule + "\033[0m\n")
    raw.flush()

    # Route prompt_toolkit output to the raw stream so cursor escape codes
    # are not offset by _PaddedWriter's left-margin prefix.
    pt_output = create_output(stdout=raw)

    pt_style = Style.from_dict({
        # noreverse removes the default inverted-video background on the toolbar
        "bottom-toolbar": "noreverse fg:ansibrightblack bg:default",
        "tb-rule": "noreverse fg:ansiyellow dim bg:default",
    })

    def bottom_toolbar():
        return FormattedText([
            ("class:tb-rule", rule + "\n"),
            ("class:bottom-toolbar", _PROMPT_HINT_PLAIN),
        ])

    try:
        session = PromptSession(
            bottom_toolbar=bottom_toolbar,
            style=pt_style,
            output=pt_output,
            multiline=False,
        )
        result = session.prompt("> ")
    except (EOFError, KeyboardInterrupt):
        raise

    # Erase the toolbar rows (rule + hint) that prompt_toolkit left in the scrollback.
    # \033[1A moves up one line; \033[2K clears it. Repeat for rule line + hint line(s).
    import math
    hint_rows = max(1, math.ceil(len(_PROMPT_HINT_PLAIN) / width))
    for _ in range(1 + hint_rows):
        raw.write("\033[1A\033[2K")
    raw.flush()

    if isinstance(sys.stdout, _PaddedWriter):
        sys.stdout.mark_new_line()

    return result


def show_evidence_collected(description: str) -> None:
    width = _pin_console_width()
    console.print(Panel(
        f"[green]{description}[/green]",
        title="[bold green]Evidence Collected[/bold green]",
        border_style="green",
        width=width,
    ))


def show_arrest_confirmation(npc_name: str) -> None:
    width = _pin_console_width()
    console.print(Panel(
        f"[bold red]{npc_name} has been arrested.[/bold red]\n"
        "[dim]Whether this is correct remains to be seen.[/dim]",
        border_style="red",
        title="[red]ARREST[/red]",
        width=width,
    ))


def show_reputation(reputation: int) -> None:
    if reputation >= 80:
        style = "green"
        label = "Respected"
    elif reputation >= 50:
        style = "yellow"
        label = "Tolerated"
    else:
        style = "red"
        label = "Notorious"
    console.print(f"[{style}]Reputation: {reputation} ({label})[/{style}]")


def show_trial_status(case_title: str, status: str, time_remaining: str | None) -> None:
    if time_remaining:
        body = f"[yellow]{case_title}[/yellow] is before the jury.\nEstimated time remaining: {time_remaining}"
    else:
        body = f"[green]{case_title}[/green] — verdict reached."
    width = _pin_console_width()
    console.print(Panel(body, title="[bold]Courthouse[/bold]", border_style="blue", width=width))


def show_player_status(states: list) -> None:
    width = _pin_console_width()
    if not states:
        console.print(Panel("[dim]No active conditions.[/dim]",
                            title="[bold]Detective Status[/bold]", border_style="dim",
                            width=width))
        return
    intensity_labels = {1: "mild", 2: "moderate", 3: "severe"}
    lines = [
        f"[yellow]·[/yellow] {s['state']} [dim]({intensity_labels.get(s['intensity'], s['intensity'])})[/dim]"
        for s in states
    ]
    console.print(Panel("\n".join(lines), title="[bold]Detective Status[/bold]",
                        border_style="yellow", width=width))


def show_locations(fixed: list, case_locs: list, case_title: str | None = None,
                   current_location: str | None = None,
                   crime_scene: str | None = None) -> None:
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold yellow")
    t.add_column("Location", style="white")
    t.add_column("Neighborhood", style="dim")
    t.add_column("Case", style="dim")
    for loc in fixed:
        name = f"{loc['name']} *" if current_location and loc["name"] == current_location else loc["name"]
        hood = loc["neighborhood_name"] if loc["neighborhood_name"] else "—"
        t.add_row(name, hood, "—")
    for loc in case_locs:
        name = f"{loc['name']} *" if current_location and loc["name"] == current_location else loc["name"]
        hood = loc["neighborhood_name"] if loc["neighborhood_name"] else "—"
        tag = "crime scene" if crime_scene and loc["name"].lower() == crime_scene.lower() else (case_title or "current case")
        t.add_row(name, hood, tag)
    console.print(Panel(t, title="[bold yellow]Known Locations[/bold yellow]",
                        border_style="yellow"))
    console.print("[dim]* you are here  ·  Ask your partner about any of them.[/dim]\n")


def show_evidence(evidence: list) -> None:
    if not evidence:
        console.print(Panel("[dim]Nothing collected yet.[/dim]",
                            title="[bold green]Evidence[/bold green]", border_style="green"))
        return
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold green")
    t.add_column("#", style="dim", width=3)
    t.add_column("Item", style="white")
    t.add_column("Location", style="dim")
    for i, e in enumerate(evidence, 1):
        t.add_row(str(i), e["description"], e["location_name"] or "—")
    console.print(Panel(t, title="[bold green]Collected Evidence[/bold green]", border_style="green"))


def show_leads(clues: list[str], evidence: list) -> None:
    lines = []
    for c in clues:
        lines.append(f"[cyan]·[/cyan] {c}")
    for e in evidence:
        lines.append(f"[green]·[/green] [italic]{e['description']}[/italic] [dim](collected)[/dim]")
    body = "\n".join(lines) if lines else "[dim]Nothing solid yet.[/dim]"
    console.print(Panel(body, title="[bold cyan]Active Leads[/bold cyan]", border_style="cyan"))


def show_suspects(npcs: list, player_suspects: list,
                  evidence_by_npc: dict[int, list] | None = None) -> None:
    lines = []
    for n in npcs:
        lines.append(f"[red]·[/red] {n['name']} [dim]({n['role']})[/dim]")
        if evidence_by_npc:
            for ev in evidence_by_npc.get(n["id"], []):
                lines.append(f"    [dim]→ {ev['description']}[/dim]")
    for s in player_suspects:
        note = f" — {s['note']}" if s["note"] else ""
        lines.append(f"[yellow]·[/yellow] {s['name']} [dim](noted by you{note})[/dim]")
    body = "\n".join(lines) if lines else "[dim]No suspects yet.[/dim]"
    console.print(Panel(body, title="[bold red]Suspects[/bold red]", border_style="red"))


def show_relationships(partner_name: str | None, partner_stage: str | None,
                       npc_relationships: list[dict]) -> None:
    lines = []
    if partner_name and partner_stage:
        lines.append(f"[magenta]♥ {escape(partner_name)} (partner — {escape(partner_stage)})[/magenta]")
    for rel in npc_relationships:
        stage = rel["stage"]
        color = {"cold": "dim", "curious": "white", "warm": "yellow",
                 "smitten": "magenta", "devoted": "red"}.get(stage, "white")
        lines.append(f"[{color}]· {escape(rel['name'])} ({escape(rel['role'])}) — {stage}[/{color}]")
    body = "\n".join(lines) if lines else "[dim]No significant relationships yet.[/dim]"
    console.print(Panel(body, title="[bold magenta]Relationships[/bold magenta]",
                        border_style="magenta"))


def show_dossier(name: str, facts: list[str]) -> None:
    if not facts:
        console.print(Panel(f"[dim]Nothing on record for {name}.[/dim]",
                            title=f"[bold yellow]{name}[/bold yellow]", border_style="yellow"))
        return
    lines = [f"[yellow]·[/yellow] {f}" for f in facts]
    console.print(Panel("\n".join(lines),
                        title=f"[bold yellow]{name}[/bold yellow]", border_style="yellow"))


def show_dossier_all(entries: dict[str, list[str]]) -> None:
    if not entries:
        console.print(Panel("[dim]Nothing in the dossier yet.[/dim]",
                            title="[bold yellow]Dossier[/bold yellow]", border_style="yellow"))
        return
    lines = []
    for name, facts in entries.items():
        lines.append(f"[bold]{name}[/bold]")
        for f in facts:
            lines.append(f"  [yellow]·[/yellow] {f}")
    console.print(Panel("\n".join(lines),
                        title="[bold yellow]Dossier[/bold yellow]", border_style="yellow"))


def _render_alignment_grid(lc: int, ge: int) -> str:
    W, H = 21, 9  # odd dimensions
    cx, cy = W // 2, H // 2
    px = cx + round(lc / 100 * cx)
    py = cy - round(ge / 100 * cy)  # inverted: positive ge = up = lower row index
    px = max(0, min(W - 1, px))
    py = max(0, min(H - 1, py))

    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            if x == px and y == py:
                row.append('◆')
            elif y == cy and x == cx:
                row.append('+')
            elif y == cy:
                row.append('─')
            elif x == cx:
                row.append('│')
            else:
                row.append(' ')
        rows.append(''.join(row))

    # Inject axis labels into middle row
    mid = list(rows[cy])
    chaos = 'chaos'
    lawful = 'lawful'
    for i, ch in enumerate(chaos):
        mid[i] = ch
    for i, ch in enumerate(lawful):
        mid[W - len(lawful) + i] = ch
    rows[cy] = ''.join(mid)

    header = ' ' * cx + 'good'
    footer = ' ' * cx + 'evil'
    return '\n'.join([header] + rows + [footer])


def show_player_profile(player: dict, orgs: list[dict], partner_name: str | None,
                        partner_stage: str | None, npc_relationships: list[dict],
                        player_skills: dict | None = None,
                        player_specializations: list[dict] | None = None,
                        partner_skills: dict | None = None,
                        partner_specializations: list[dict] | None = None) -> None:
    lines = []

    # Identity
    race = player.get("race") or "unspecified"
    gender = player.get("gender") or "unspecified"
    lines.append(f"[bold white]{escape(race.title())} / {escape(gender.title())}[/bold white]")

    # Alignment
    lc = player.get("law_chaos", 0)
    ge = player.get("good_evil", 0)
    lc_label = "Lawful" if lc >= 5 else "Chaotic" if lc <= -5 else "Neutral"
    ge_label = "Good" if ge >= 5 else "Evil" if ge <= -5 else "Neutral"
    lines.append(f"Alignment: {lc_label} {ge_label}")
    lines.append(_render_alignment_grid(lc, ge))
    lines.append("")

    # Case stats
    rep = player.get("reputation", 100)
    rep_label = "Respected" if rep >= 80 else "Tolerated" if rep >= 50 else "Notorious"
    cash = player.get("cash", 0)
    lines.append(f"[cyan]Reputation:[/cyan] {rep} ({rep_label})   "
                 f"[cyan]Cash:[/cyan] ${cash}   "
                 f"[cyan]Cases solved:[/cyan] {player.get('cases_solved', 0)}   "
                 f"[cyan]Wrong arrests:[/cyan] {player.get('wrong_arrests', 0)}   "
                 f"[cyan]DA trust:[/cyan] {player.get('da_trust', 100)}")

    # Organizations
    if orgs:
        lines.append("")
        lines.append("[bold yellow]Organizations[/bold yellow]")
        for o in orgs:
            payroll_note = f"  [dim](payroll ${o['payroll']}/day)[/dim]" if o.get("payroll") else ""
            lines.append(f"  [yellow]·[/yellow] {escape(o['org_name'])} — {escape(o['role'] or 'member')}{payroll_note}")

    # Romantic relationships
    has_romance = partner_name or npc_relationships
    if has_romance:
        lines.append("")
        lines.append("[bold magenta]Relationships[/bold magenta]")
        if partner_name and partner_stage:
            lines.append(f"  [magenta]♥ {escape(partner_name)} (partner — {escape(partner_stage)})[/magenta]")
        for rel in npc_relationships:
            stage = rel["stage"]
            color = {"cold": "dim", "curious": "white", "warm": "yellow",
                     "smitten": "magenta", "devoted": "red"}.get(stage, "white")
            lines.append(f"  [{color}]· {escape(rel['name'])} ({escape(rel['role'])}) — {stage}[/{color}]")

    # Skills section
    has_skills = player_skills or partner_skills
    if has_skills:
        lines.append("")
        lines.append("[bold green]Skills[/bold green]")

        def _render_owner_skills(label, skills, specs):
            if not skills:
                return
            lines.append(f"  [green]{escape(label)}[/green]")
            for root, data in sorted(skills.items()):
                level = data.get("level", 1)
                root_specs = [s for s in (specs or []) if s["root"] == root]
                lines.append(f"    {escape(root.title())} — level {level}")
                for s in root_specs:
                    lines.append(f"      [italic]· {escape(s['name'])}:[/italic] {escape(s['description'])}")

        _render_owner_skills("Detective", player_skills, player_specializations)
        _render_owner_skills(partner_name or "Partner", partner_skills, partner_specializations)

    console.print(Panel("\n".join(lines), title="[bold white]Detective File[/bold white]",
                        border_style="white"))


def show_cases(cases: list, active_case_id: int | None) -> None:
    if not cases:
        console.print(Panel("[dim]No cases on file.[/dim]",
                            title="[bold red]Case Files[/bold red]", border_style="red"))
        return
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold red")
    t.add_column("", width=2)
    t.add_column("Title", style="white")
    t.add_column("Status", style="dim")
    for c in cases:
        marker = "[bold yellow]★[/bold yellow]" if c["id"] == active_case_id else " "
        status_label = {"on_hold": "on hold"}.get(c["status"], c["status"])
        status_color = {"active": "green", "in_trial": "yellow", "closed": "dim", "on_hold": "dim"}.get(c["status"], "dim")
        t.add_row(marker, c["title"], f"[{status_color}]{status_label}[/{status_color}]")
    console.print(Panel(t, title="[bold red]Case Files[/bold red]", border_style="red"))
    console.print("[dim]/cases activate <title> — switch active case[/dim]\n")


def show_items(items: dict[str, int], item_defs: list) -> None:
    """Display the player's current inventory."""
    owned = [(d, items.get(d["slug"], 0)) for d in item_defs if items.get(d["slug"], 0) > 0]
    if not owned:
        console.print(Panel(
            "[dim]Nothing on you.[/dim]",
            title="[bold white]What You're Carrying[/bold white]",
            border_style="white",
        ))
        return
    lines = []
    for item_def, qty in owned:
        if item_def["consumable"]:
            qty_str = str(qty)
        else:
            qty_str = "✓"
        lines.append(
            f"  [white]{item_def['name']:<22}[/white]"
            f"[yellow]{qty_str:<5}[/yellow]"
            f"[dim]{item_def['description']}[/dim]"
        )
    console.print(Panel(
        "\n".join(lines),
        title="[bold white]What You're Carrying[/bold white]",
        border_style="white",
    ))


def show_help() -> None:
    from io import StringIO
    from rich.console import Console as _Console

    # Render help to a string first
    buf = StringIO()
    tmp = _Console(file=buf, width=shutil.get_terminal_size().columns - 4,
                   force_terminal=True, highlight=False)
    tmp.print(Panel(
        "[bold]Movement & Time:[/bold]\n"
        "  /go [location] · /visit [location]\n"
        "  /wait — wait 1 hour\n"
        "  /wait 2 hours · /wait 30 minutes · /wait until midnight\n"
        "  /wait for [name] — wait here until that person arrives\n"
        "  /time — show current time\n\n"
        "[bold]Interaction:[/bold]\n"
        "  /talk [character] · /talk to [character]\n"
        "  /talk partner — talk to your partner\n\n"
        "[bold]Investigation:[/bold]\n"
        "  /location — describe current location\n"
        "  /look · /look around — survey the area\n"
        "  /examine [object] · /look at [object]\n"
        "  /collect [item] · /pick up [item]\n"
        "  /arrest [suspect]\n"
        "  /detain [suspect] — bring in for interrogation at The Precinct\n"
        "  /release [suspect] — release from holding\n"
        "  /holding — list suspects currently detained\n\n"
        "[bold]Case:[/bold]\n"
        "  /go da — go to the DA's Office\n"
        "  /submit — submit case for trial (from anywhere)\n"
        "  /drop — drop current case\n"
        "  /court — check trial status (from anywhere)\n\n"
        "[bold]Detective status:[/bold]\n"
        "  /status — view active conditions\n"
        "  /status add <state> — add a condition (drunk, sleepy, etc.)\n"
        "  /status clear <state> — remove a condition\n\n"
        "[bold]Case notes:[/bold]\n"
        "  /locations — known locations\n"
        "  /leads — active leads for current case\n"
        "  /evidence — collected evidence\n"
        "  /suspects — suspect list (with linked evidence)\n"
        "  /suspects remove <name> — remove from your suspect list\n"
        "  /link <#> <name> — link evidence item to a suspect\n"
        "  /cases — all cases (★ = active)\n"
        "  /cases activate <title> — switch to a different case\n"
        "  /dossier — everything learned about all persons\n"
        "  /dossier <name> — what you know about a specific person\n"
        "  /who <name> — check if someone is in the case file\n"
        "  /add <name> as suspect — add someone to your list\n"
        "  /drink — have a drink (at a bar or near one)\n"
        "  /rep — your street reputation and faction standings\n"
        "  /items — what you're carrying\n"
        "  /use [item] [action] — use an item\n"
        "  /job or /case — current active case or job\n"
        "  /jobs — all cases and active jobs\n"
        "  /classifieds — browse the job board\n"
        "  /classifieds --pending — job offers from NPCs\n"
        "  /done — mark an active job complete\n"
        "  /romance — relationship status\n"
        "  /me — your detective profile\n\n"
        "[bold]Other:[/bold]\n"
        "  /help — show this\n"
        "  done / bye / leave — end a conversation\n"
        "  quit or exit — quit the game",
        title="[bold yellow]Detective's Handbook[/bold yellow]",
        border_style="yellow",
    ))
    rendered = buf.getvalue()

    import tty
    import termios

    raw = sys.stdout._wrapped if isinstance(sys.stdout, _PaddedWriter) else sys.stdout
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    # Enter alternate screen, clear it, render help, wait for keypress, restore.
    raw.write("\033[?1049h\033[H\033[2J")
    raw.write(rendered)
    raw.write("\n\033[2m  press any key to continue\033[0m\n")
    raw.flush()
    try:
        tty.setraw(fd)
        sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        raw.write("\033[2J\033[H")   # blank the alt screen before saving to scrollback
        raw.write("\033[?1049l")
        raw.flush()
        if isinstance(sys.stdout, _PaddedWriter):
            sys.stdout.mark_new_line()
