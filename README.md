```
███╗   ██╗ ██████╗ ██╗██████╗ 
████╗  ██║██╔═══██╗██║██╔══██╗
██╔██╗ ██║██║   ██║██║██████╔╝
██║╚██╗██║██║   ██║██║██╔══██╗
██║ ╚████║╚██████╔╝██║██║  ██║
╚═╝  ╚═══╝ ╚═════╝ ╚═╝╚═╝  ╚═╝
              ────────          
██╗     ███████╗ █████╗ ███╗   ██╗███████╗
██║     ██╔════╝██╔══██╗████╗  ██║██╔════╝
██║     █████╗  ███████║██╔██╗ ██║███████╗
██║     ██╔══╝  ██╔══██║██║╚██╗██║╚════██║
███████╗███████╗██║  ██║██║ ╚████║███████║
╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝

         Noirleans, Louisiana · 1935
```

A terminal-based detective RPG set in Noirleans, Louisiana — 1935. The Depression is on. Everyone is broke. Someone is always dead.

You are a detective navigating a city that doesn't want to be understood. Cases are procedurally generated. The city is alive whether you're watching it or not.

---

## The World

Noirleans is a hundred locations spread across neighborhoods with their own factions, atmospheres, and loyalties. Two rival crime families divide the city. The police are on someone's payroll. The unions are the only integrated institutions in town. The church keeps its own counsel.

NPCs have lives. They keep schedules, move between locations, and remember how you've treated them. The barkeep at Rossi's is different at 2pm than he is at midnight — and if you've leaned on him before, he'll be different still. Some people will only talk to you if you've built trust. Others will shut down the moment they sense pressure. A few will crack if you push hard enough, but pushing has consequences.

Every conversation is live dialogue powered by Claude. NPCs have psychology — guilt, pressure tolerance, secrets they protect, and arcs of revelation. Interrogate a suspect badly and you may spook them. Handle a witness gently and they might volunteer something they hadn't planned to. The city talks, but it doesn't talk easily.

Your partner is always with you. She has her own opinions about the people you meet, the choices you make, and the kind of detective you're becoming. She remembers your history together — not the case facts, but how things felt. The relationship develops over time.

---

## The Cases

Cases are drawn from mystery archetypes — Chandler, Hammett, Christie, Chinatown — and generated fresh each time. You collect evidence, evaluate leads, build a case, and eventually make an arrest. The DA will want something admissible. The judge might not be clean. Justice in Noirleans is a negotiation.

Between cases, factions offer jobs: surveillance, debt collection, skip traces. Taking their money earns their loyalty and their enemies' suspicion.

---

## Running It

Requires Python 3.11+ and the [`claude` CLI](https://claude.ai/code) installed and authenticated.

```bash
pip install -e "."
python main.py
```

Optional extras:
```bash
pip install -e ".[audio]"   # per-NPC voices via Kokoro TTS
pip install -e ".[memory]"  # semantic conversation memory
```

Save data lives at `~/.noir_detective/game.db`. Reset with `python main.py --reset`.

---

## Commands

Natural language gets you most of the way:

```
go to rossi's
talk to the barkeep
examine the envelope
arrest hortense delacroix
```

Slash commands for game systems: `/case`, `/leads`, `/evidence`, `/suspects`, `/map`, `/items`, `/rep`, `/status`, `/wait`, `/help`.

---

## License

GPL v3. See [LICENSE](LICENSE).
