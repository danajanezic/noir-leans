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


def test_flirt_explicit():
    for phrase in ["flirt with Vera", "wink at the bartender", "charm the witness"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.FLIRT, f"Failed for: {phrase}"


def test_flirt_compliment():
    for phrase in ["you're beautiful", "you look lovely", "you're fascinating", "you're incredible"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.FLIRT, f"Failed for: {phrase}"


def test_flirt_romantic_question():
    for phrase in ["are you married", "do you have someone", "are you seeing anyone"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.FLIRT, f"Failed for: {phrase}"


def test_flirt_buy_drink():
    for phrase in ["buy her a drink", "buy him a drink", "buy them a drink", "let me buy you a drink"]:
        cmd = parse_command(phrase)
        assert cmd.intent == Intent.FLIRT, f"Failed for: {phrase}"


def test_unknown_intent():
    cmd = parse_command("do the macarena")
    assert cmd.intent == Intent.UNKNOWN
    assert cmd.raw == "do the macarena"
