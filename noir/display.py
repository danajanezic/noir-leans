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
    console.print(Rule(f"[dim]talking to {name}[/dim]", style="dim"))
    console.print(f"[dim]done / bye / exit to leave[/dim]\n")


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


def show_location(name: str, description: str, npcs_present: list[str]) -> None:
    npc_text = ""
    if npcs_present:
        npc_text = f"\n\n[dim]Present: {', '.join(npcs_present)}[/dim]"
    console.print(Panel(
        f"[italic]{description}[/italic]{npc_text}",
        title=f"[bold yellow]{name}[/bold yellow]",
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


def show_suspects(npcs: list, player_suspects: list) -> None:
    lines = []
    for n in npcs:
        lines.append(f"[red]·[/red] {n['name']} [dim]({n['role']})[/dim]")
    for s in player_suspects:
        note = f" — {s['note']}" if s["note"] else ""
        lines.append(f"[yellow]·[/yellow] {s['name']} [dim](noted by you{note})[/dim]")
    body = "\n".join(lines) if lines else "[dim]No suspects yet.[/dim]"
    console.print(Panel(body, title="[bold red]Suspects[/bold red]", border_style="red"))


def show_help() -> None:
    console.print(Panel(
        "[bold]Movement:[/bold]\n"
        "  go to [location] / visit [location]\n\n"
        "[bold]Interaction:[/bold]\n"
        "  talk to [character] / ask [character] about [topic]\n"
        "  talk to my partner\n\n"
        "[bold]Investigation:[/bold]\n"
        "  examine [object] / look around\n"
        "  pick up [item] / collect [item]\n"
        "  arrest [suspect]\n\n"
        "[bold]Case:[/bold]\n"
        "  go to the DA — submit your case\n"
        "  visit the courthouse — check trial status\n\n"
        "[bold]Detective status:[/bold]\n"
        "  /status — view active conditions\n"
        "  /status add <state> — add a condition (drunk, sleepy, etc.)\n"
        "  /status clear <state> — remove a condition\n\n"
        "[bold]Case notes:[/bold]\n"
        "  /locations — known locations (ask partner about them)\n"
        "  /leads — active leads for current case\n"
        "  /evidence — collected evidence\n"
        "  /suspects — suspect list\n"
        "  /add <name> as suspect — add someone to your list\n\n"
        "[bold]Other:[/bold]\n"
        "  help or /help — show this\n"
        "  done / bye / exit — end a conversation",
        title="[bold yellow]Detective's Handbook[/bold yellow]",
        border_style="yellow",
    ))
