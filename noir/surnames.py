import random
from pathlib import Path

_ROOT = Path(__file__).parent.parent

_FILES = {
    "creole": _ROOT / "Creole-surnames.txt",
    "italian": _ROOT / "italian_surnames.txt",
}
_LISTS: dict[str, list[str]] = {}


def _load(key: str) -> list[str]:
    if key not in _LISTS:
        path = _FILES.get(key)
        if path and path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            _LISTS[key] = [
                l.strip() for l in lines
                if l.strip() and l.strip().lower() != "surname"
            ]
        else:
            _LISTS[key] = []
    return _LISTS[key]


def _pool_for_race(race: str) -> str | None:
    r = race.lower()
    if "creole" in r or "cajun" in r:
        return "creole"
    if "italian" in r:
        return "italian"
    return None


def random_surname(race: str) -> str | None:
    key = _pool_for_race(race)
    if key is None:
        return None
    pool = _load(key)
    return random.choice(pool) if pool else None


def _replace_last_name(full_name: str, surname: str) -> str:
    parts = full_name.strip().split()
    if len(parts) < 2:
        return full_name
    parts[-1] = surname
    return " ".join(parts)


_ITALIAN_FACTIONS = {"rossi", "castellano"}


def apply_job_surname_overrides(job_data: dict, faction: str) -> dict:
    """Replace surnames in client_npc_name and target using faction to pick the pool."""
    pool_key = "italian" if faction.lower() in _ITALIAN_FACTIONS else "creole"
    pool = _load(pool_key)
    if not pool:
        return job_data

    used: set[str] = set()

    def _replace(name: str) -> str:
        if not name:
            return name
        surname = random.choice(pool)
        for _ in range(20):
            if surname not in used:
                break
            surname = random.choice(pool)
        used.add(surname)
        return _replace_last_name(name, surname)

    if job_data.get("client_npc_name"):
        job_data["client_npc_name"] = _replace(job_data["client_npc_name"])

    # target may be "First Last, description" or a description phrase
    # Only replace if the pre-comma portion looks like a proper name (1-3 capitalized words)
    target = job_data.get("target", "")
    if target:
        name_part = target.split(",")[0].strip()
        words = name_part.split()
        if 1 <= len(words) <= 3 and all(w[0].isupper() for w in words if w):
            new_name = _replace(name_part)
            job_data["target"] = target.replace(name_part, new_name, 1)

    return job_data


def apply_surname_overrides(case: dict) -> dict:
    """Replace surnames for Creole/Italian suspects after LLM generation."""
    suspects = case.get("suspects", [])
    if not suspects:
        return case

    rename: dict[str, str] = {}
    used: set[str] = set()

    for suspect in suspects:
        old_name = suspect.get("name", "")
        race = suspect.get("race", "")
        if not old_name or not race:
            continue
        key = _pool_for_race(race)
        if key is None:
            continue
        pool = _load(key)
        if not pool:
            continue
        surname = random.choice(pool)
        for _ in range(20):
            if surname not in used:
                break
            surname = random.choice(pool)
        used.add(surname)
        new_name = _replace_last_name(old_name, surname)
        if new_name != old_name:
            rename[old_name] = new_name

    if not rename:
        return case

    for suspect in suspects:
        if suspect.get("name") in rename:
            suspect["name"] = rename[suspect["name"]]
        for rel in suspect.get("relationships", []):
            if rel.get("name") in rename:
                rel["name"] = rename[rel["name"]]

    if case.get("killer_name") in rename:
        case["killer_name"] = rename[case["killer_name"]]

    return case
