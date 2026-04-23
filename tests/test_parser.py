from noir.parser import parse_command, Intent


def test_go_to_intent():
    cmd = parse_command("go to the rusty anchor")
    assert cmd.intent == Intent.GO
    assert "rusty anchor" in cmd.target.lower()


def test_go_variations():
    for phrase in ["head to the diner", "visit the precinct", "walk to the pier"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.GO


def test_talk_to_intent():
    cmd = parse_command("talk to Dolores")
    assert cmd.intent == Intent.TALK
    assert "Dolores" in cmd.target


def test_talk_variations():
    for phrase in ["speak with Vera", "ask Reginald about the flamingo", "chat with the bartender"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.TALK


def test_talk_to_partner():
    cmd = parse_command("talk to my partner")
    assert cmd.intent == Intent.TALK_PARTNER


def test_arrest_intent():
    cmd = parse_command("arrest Dolores Mink")
    assert cmd.intent == Intent.ARREST
    assert "Dolores" in cmd.target


def test_collect_evidence_intent():
    cmd = parse_command("pick up the flamingo feather")
    assert cmd.intent == Intent.COLLECT
    for phrase in ["take the receipt", "grab the note", "collect the glove"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.COLLECT


def test_examine_intent():
    cmd = parse_command("examine the desk")
    assert cmd.intent == Intent.EXAMINE
    for phrase in ["look at the painting", "inspect the window", "check the safe"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.EXAMINE


def test_go_to_da_intent():
    cmd = parse_command("go to the DA")
    assert cmd.intent == Intent.GO_DA


def test_go_to_courthouse_intent():
    cmd = parse_command("visit the courthouse")
    assert cmd.intent == Intent.GO_COURTHOUSE


def test_look_around_intent():
    for phrase in ["look around", "where am I", "what do I see"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.LOOK


def test_help_intent():
    cmd = parse_command("help")
    assert cmd.intent == Intent.HELP



def test_unknown_intent():
    cmd = parse_command("do the macarena")
    assert cmd.intent == Intent.UNKNOWN
    assert cmd.raw == "do the macarena"


def test_lets_go_variants():
    for phrase in [
        "let's go to the crane residence",
        "let's head to the diner",
        "let's visit the precinct",
        "let us go to the warehouse",
        "let's start at the crime scene",
        "let's make our way to the harbor",
    ]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.GO, f"Failed for: {phrase}"
