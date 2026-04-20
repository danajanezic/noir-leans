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


def show_splash() -> None:
    console.print()
    lines = [
        ("", 0),
        ("N  O  I  R  L  E  A  N  S", 0.07),
        ("", 0),
        ("1  9  3  5", 0.09),
        ("", 0),
        ("The Depression is on.", 0.04),
        ("Everyone is broke.", 0.04),
        ("Someone is always dead.", 0.04),
        ("", 0),
    ]
    for text, delay in lines:
        if not text:
            console.print()
            continue
        for char in text:
            sys.stdout.write(char)
            sys.stdout.flush()
            time.sleep(delay)
        console.print()
    time.sleep(0.4)
    console.print(Rule(style="yellow dim"))
    console.print()


def typewrite(text: str, delay: float = 0.025) -> None:
    width = max(shutil.get_terminal_size().columns - 2, 40)
    wrapped = textwrap.fill(text, width=width)
    for char in wrapped:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")


def show_narrator(text: str) -> None:
    console.print()
    console.print(f"[dim italic]{escape(text)}[/dim italic]")
    console.print()


def show_conversation_header(name: str) -> None:
    console.print(Rule(f"[bold cyan]talking to {escape(name)}[/bold cyan]", style="cyan"))
    console.print(f"[dim]done / bye / leave to end · /go /talk /examine /look still work here[/dim]\n")


def show_conversation_footer(name: str) -> None:
    console.print(Rule(style="dim"))


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


def show_travel_animation() -> None:
    car = "🚗"
    dot = "·"
    width = max(shutil.get_terminal_size().columns - 6, 20)
    sys.stdout.write("\n")
    for i in range(width + 2):
        car_pos = max(width - i, 0)
        spaces = " " * car_pos
        trail = dot * min(i, width)
        line = (spaces + car + trail)[:width + 4]
        sys.stdout.write(f"\r{line}")
        sys.stdout.flush()
        time.sleep(0.028)
    sys.stdout.write("\r" + " " * (width + 6) + "\r")
    sys.stdout.flush()
    sys.stdout.write("\n")


def fmt_game_time(game_time: int) -> str:
    tod = game_time % 1440
    h, m = divmod(tod, 60)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {period}"


def show_wait_result(new_time: int, npc_movements: list[tuple[str, str]]) -> None:
    time_str = fmt_game_time(new_time)
    lines = [f"[dim]Time passes. It is now [bold]{time_str}[/bold].[/dim]"]
    for name, loc in npc_movements:
        lines.append(f"[dim]  · {name} has moved to {loc}.[/dim]")
    console.print("\n" + "\n".join(lines))


def show_location(name: str, description: str, npcs_present: list[str],
                  game_time: int | None = None) -> None:
    npc_text = ""
    if npcs_present:
        npc_text = f"\n\n[dim]Present: {', '.join(npcs_present)}[/dim]"
    time_text = f"  [dim]{fmt_game_time(game_time)}[/dim]" if game_time is not None else ""
    console.print(Panel(
        f"[italic]{description}[/italic]{npc_text}",
        title=f"[bold yellow]{name}[/bold yellow]{time_text}",
        border_style="yellow",
        box=box.DOUBLE_EDGE,
    ))
    if npcs_present:
        hint = f"[dim]examine <thing>  ·  talk to {npcs_present[0]}  ·  talk to partner[/dim]"
    else:
        hint = "[dim]examine <thing>  ·  talk to partner[/dim]"
    console.print(hint)


def show_dialogue(speaker: str, text: str, delay: float = 0.02) -> None:
    console.print(f"\n[bold cyan]{speaker}:[/bold cyan]")
    console.print(Markdown(text))
    console.print()


def show_player_input_prompt() -> str:
    return console.input("\n[bold white]>[/bold white] ")


def show_evidence_collected(description: str) -> None:
    console.print(Panel(
        f"[green]{description}[/green]",
        title="[bold green]Evidence Collected[/bold green]",
        border_style="green",
    ))


def show_arrest_confirmation(npc_name: str) -> None:
    console.print(Panel(
        f"[bold red]{npc_name} has been arrested.[/bold red]\n"
        "[dim]Whether this is correct remains to be seen.[/dim]",
        border_style="red",
        title="[red]ARREST[/red]",
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
    console.print(Panel(body, title="[bold]Courthouse[/bold]", border_style="blue"))


def show_player_status(states: list) -> None:
    if not states:
        console.print(Panel("[dim]No active conditions.[/dim]",
                            title="[bold]Detective Status[/bold]", border_style="dim"))
        return
    intensity_labels = {1: "mild", 2: "moderate", 3: "severe"}
    lines = [
        f"[yellow]·[/yellow] {s['state']} [dim]({intensity_labels.get(s['intensity'], s['intensity'])})[/dim]"
        for s in states
    ]
    console.print(Panel("\n".join(lines), title="[bold]Detective Status[/bold]",
                        border_style="yellow"))


def show_locations(fixed: list, case_locs: list, case_title: str | None = None) -> None:
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold yellow")
    t.add_column("Location", style="white")
    t.add_column("Case", style="dim")
    for loc in fixed:
        t.add_row(loc["name"], "—")
    for loc in case_locs:
        t.add_row(loc["name"], case_title or "current case")
    console.print(Panel(t, title="[bold yellow]Known Locations[/bold yellow]",
                        border_style="yellow"))
    console.print("[dim]Ask your partner about any of them.[/dim]\n")


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
        status_color = {"active": "green", "in_trial": "yellow", "closed": "dim"}.get(c["status"], "dim")
        t.add_row(marker, c["title"], f"[{status_color}]{c['status']}[/{status_color}]")
    console.print(Panel(t, title="[bold red]Case Files[/bold red]", border_style="red"))
    console.print("[dim]/cases activate <title> — switch active case[/dim]\n")


def show_help() -> None:
    console.print(Panel(
        "[bold]Movement & Time:[/bold]\n"
        "  /go [location] · /visit [location]\n"
        "  /wait — wait 1 hour\n"
        "  /wait 2 hours · /wait 30 minutes · /wait until midnight\n"
        "  /time — show current time\n\n"
        "[bold]Interaction:[/bold]\n"
        "  /talk [character] · /talk to [character]\n"
        "  /talk partner — talk to your partner\n\n"
        "[bold]Investigation:[/bold]\n"
        "  /look · /look around — survey the area\n"
        "  /examine [object] · /look at [object]\n"
        "  /collect [item] · /pick up [item]\n"
        "  /arrest [suspect]\n\n"
        "[bold]Case:[/bold]\n"
        "  /go da — submit your case or drop it for a new one\n"
        "  /go courthouse — check trial status\n\n"
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
        "  /romance — relationship status\n\n"
        "[bold]Other:[/bold]\n"
        "  /help — show this\n"
        "  done / bye / leave — end a conversation\n"
        "  quit or exit — quit the game",
        title="[bold yellow]Detective's Handbook[/bold yellow]",
        border_style="yellow",
    ))
