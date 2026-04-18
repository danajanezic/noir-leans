import time
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich import box

console = Console()


def typewrite(text: str, delay: float = 0.025) -> None:
    for char in text:
        console.print(char, end="", highlight=False)
        time.sleep(delay)
    console.print()


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


def show_dialogue(speaker: str, text: str, delay: float = 0.02) -> None:
    console.print(f"\n[bold cyan]{speaker}:[/bold cyan]")
    typewrite(text, delay=delay)
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
        "[bold]Case notes:[/bold]\n"
        "  /romance — relationship status\n\n"
        "[bold]Other:[/bold]\n"
        "  help — show this",
        title="[bold yellow]Detective's Handbook[/bold yellow]",
        border_style="yellow",
    ))
