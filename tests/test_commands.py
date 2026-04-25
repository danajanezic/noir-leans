"""Tests for slash command dispatch, exit/quit detection, and suspect management."""
import pytest
from unittest.mock import MagicMock, patch
from noir.game import Game, _is_exit, _is_game_quit, _SLASH_COMMANDS
from noir.persistence.repository import (
    create_player, create_case, create_location, create_npc,
    add_player_suspect, get_player_suspects, remove_player_suspect,
)
from noir.llm.mock import MockLLMBackend


# ---------------------------------------------------------------------------
# _is_exit — ends a conversation, not the game
# ---------------------------------------------------------------------------

class TestIsExit:
    def test_bye_is_exit(self):
        assert _is_exit("bye")

    def test_done_is_exit(self):
        assert _is_exit("done")

    def test_leave_is_exit(self):
        assert _is_exit("leave")

    def test_slash_bye_is_exit(self):
        assert _is_exit("/bye")

    def test_slash_done_is_exit(self):
        assert _is_exit("/done")

    def test_quit_is_exit(self):
        assert _is_exit("quit")

    def test_exit_is_exit(self):
        assert _is_exit("exit")

    def test_known_slash_commands_are_not_exits(self):
        for cmd in _SLASH_COMMANDS:
            assert not _is_exit(cmd), f"{cmd} should not be treated as exit"

    def test_slash_command_with_arg_is_not_exit(self):
        assert not _is_exit("/go The Rusty Anchor")
        assert not _is_exit("/talk Donnelly")
        assert not _is_exit("/examine the desk")
        assert not _is_exit("/suspects remove Vera")
        assert not _is_exit("/dossier Gerald Fitch")
        assert not _is_exit("/who Solomon Tate")

    def test_unknown_slash_is_exit(self):
        assert _is_exit("/frobnicate")

    def test_whitespace_trimmed(self):
        assert _is_exit("  bye  ")
        assert not _is_exit("  /go the precinct  ")


# ---------------------------------------------------------------------------
# _is_game_quit — only explicit quit/exit commands
# ---------------------------------------------------------------------------

class TestIsGameQuit:
    def test_quit_quits(self):
        assert _is_game_quit("quit")

    def test_exit_quits(self):
        assert _is_game_quit("exit")

    def test_slash_quit_quits(self):
        assert _is_game_quit("/quit")

    def test_slash_exit_quits(self):
        assert _is_game_quit("/exit")

    def test_bye_does_not_quit(self):
        assert not _is_game_quit("bye")

    def test_done_does_not_quit(self):
        assert not _is_game_quit("done")

    def test_leave_does_not_quit(self):
        assert not _is_game_quit("leave")

    def test_slash_bye_does_not_quit(self):
        assert not _is_game_quit("/bye")

    def test_go_does_not_quit(self):
        assert not _is_game_quit("/go somewhere")


# ---------------------------------------------------------------------------
# remove_player_suspect
# ---------------------------------------------------------------------------

class TestRemovePlayerSuspect:
    @pytest.fixture
    def case_with_suspects(self, db):
        create_player(db)
        case_id = create_case(db, archetype="Christie", title="Test", case_data={})
        add_player_suspect(db, case_id=case_id, name="René Fontenot", note="seen near the body")
        add_player_suspect(db, case_id=case_id, name="Solomon Tate", note=None)
        return db, case_id

    def test_remove_by_partial_name(self, case_with_suspects):
        db, case_id = case_with_suspects
        removed = remove_player_suspect(db, case_id=case_id, name="Fontenot")
        assert removed is True
        suspects = get_player_suspects(db, case_id)
        assert len(suspects) == 1
        assert suspects[0]["name"] == "Solomon Tate"

    def test_remove_by_full_name(self, case_with_suspects):
        db, case_id = case_with_suspects
        remove_player_suspect(db, case_id=case_id, name="Solomon Tate")
        suspects = get_player_suspects(db, case_id)
        assert len(suspects) == 1
        assert suspects[0]["name"] == "René Fontenot"

    def test_remove_case_insensitive(self, case_with_suspects):
        db, case_id = case_with_suspects
        removed = remove_player_suspect(db, case_id=case_id, name="solomon")
        assert removed is True
        assert len(get_player_suspects(db, case_id)) == 1

    def test_remove_nonexistent_returns_false(self, case_with_suspects):
        db, case_id = case_with_suspects
        removed = remove_player_suspect(db, case_id=case_id, name="Nobody")
        assert removed is False
        assert len(get_player_suspects(db, case_id)) == 2

    def test_remove_does_not_affect_other_cases(self, db):
        create_player(db)
        case_a = create_case(db, archetype="Christie", title="Case A", case_data={})
        case_b = create_case(db, archetype="Christie", title="Case B", case_data={})
        add_player_suspect(db, case_id=case_a, name="Vera Smoot", note=None)
        add_player_suspect(db, case_id=case_b, name="Vera Smoot", note=None)
        remove_player_suspect(db, case_id=case_a, name="Vera")
        assert len(get_player_suspects(db, case_b)) == 1


# ---------------------------------------------------------------------------
# _dispatch_slash — action slash commands route correctly
# ---------------------------------------------------------------------------

@pytest.fixture
def game(db):
    create_player(db)
    g = Game(conn=db, llm=MockLLMBackend())
    return g


@pytest.fixture
def game_with_case(db):
    create_player(db)
    case_id = create_case(db, archetype="Christie", title="The Fitch Affair",
                          case_data={"killer_name": "Dolores Mink"})
    loc_id = create_location(db, name="The Study", description="Books everywhere.", is_fixed=False, case_id=case_id)
    create_npc(db, case_id=case_id, name="Dolores Mink", role="suspect",
               system_prompt="You are Dolores.", current_location_id=loc_id)
    g = Game(conn=db, llm=MockLLMBackend())
    g.active_case_id = case_id
    g.current_location_id = loc_id
    return g


class TestDispatchSlash:
    def test_locations_calls_handler(self, game):
        with patch.object(game, "handle_slash_locations") as mock:
            game._dispatch_slash("/locations")
            mock.assert_called_once()

    def test_leads_calls_handler(self, game):
        with patch.object(game, "handle_slash_leads") as mock:
            game._dispatch_slash("/leads")
            mock.assert_called_once()

    def test_evidence_calls_handler(self, game):
        with patch.object(game, "handle_slash_evidence") as mock:
            game._dispatch_slash("/evidence")
            mock.assert_called_once()

    def test_suspects_calls_handler(self, game):
        with patch.object(game, "handle_slash_suspects") as mock:
            game._dispatch_slash("/suspects")
            mock.assert_called_once()

    def test_suspects_remove_calls_handler(self, game):
        with patch.object(game, "handle_slash_suspects_remove") as mock:
            game._dispatch_slash("/suspects remove Vera")
            mock.assert_called_once_with("/suspects remove Vera")

    def test_look_calls_handler(self, game):
        with patch.object(game, "handle_slash_look") as mock:
            game._dispatch_slash("/look")
            mock.assert_called_once()

    def test_look_around_calls_handler(self, game):
        with patch.object(game, "handle_slash_look") as mock:
            game._dispatch_slash("/look around")
            mock.assert_called_once()

    def test_go_calls_handle_go(self, game):
        with patch.object(game, "handle_go") as mock:
            game._dispatch_slash("/go The Rusty Anchor")
            mock.assert_called_once_with("The Rusty Anchor")

    def test_go_to_strips_prefix(self, game):
        with patch.object(game, "handle_go") as mock:
            game._dispatch_slash("/go to the precinct")
            mock.assert_called_once_with("the precinct")

    def test_visit_calls_handle_go(self, game):
        with patch.object(game, "handle_go") as mock:
            game._dispatch_slash("/visit the diner")
            mock.assert_called_once_with("the diner")

    def test_go_da_routes_to_handle_go(self, game):
        with patch.object(game, "handle_go") as mock:
            game._dispatch_slash("/go da")
            mock.assert_called_once_with("The DA's Office")

    def test_go_courthouse_routes_to_handle_go_courthouse(self, game):
        with patch.object(game, "handle_go_courthouse") as mock:
            game._dispatch_slash("/go courthouse")
            mock.assert_called_once()

    def test_talk_calls_handle_talk(self, game):
        with patch.object(game, "handle_talk") as mock:
            game._dispatch_slash("/talk Donnelly")
            mock.assert_called_once_with("Donnelly")

    def test_talk_to_strips_prefix(self, game):
        with patch.object(game, "handle_talk") as mock:
            game._dispatch_slash("/talk to Cassidy")
            mock.assert_called_once_with("Cassidy")

    def test_examine_calls_handle_examine(self, game):
        with patch.object(game, "handle_examine") as mock:
            game._dispatch_slash("/examine the desk")
            mock.assert_called_once_with("the desk")

    def test_arrest_calls_handle_arrest(self, game):
        with patch.object(game, "handle_arrest") as mock:
            game._dispatch_slash("/arrest Dolores Mink")
            mock.assert_called_once_with("Dolores Mink")

    def test_help_calls_show_help(self, game):
        with patch("noir.game.show_help") as mock:
            game._dispatch_slash("/help")
            mock.assert_called_once()

    def test_romance_calls_handler(self, game):
        with patch.object(game, "handle_slash_romance") as mock:
            game._dispatch_slash("/romance")
            mock.assert_called_once()


# ---------------------------------------------------------------------------
# handle_slash_suspects_remove — integration with DB
# ---------------------------------------------------------------------------

class TestHandleSlashSuspectsRemove:
    def test_removes_matching_suspect(self, game_with_case, capsys):
        db = game_with_case.conn
        case_id = game_with_case.active_case_id
        add_player_suspect(db, case_id=case_id, name="René Fontenot", note=None)
        game_with_case.handle_slash_suspects_remove("/suspects remove Fontenot")
        assert len(get_player_suspects(db, case_id)) == 0

    def test_reports_not_found(self, game_with_case, capsys):
        game_with_case.handle_slash_suspects_remove("/suspects remove Nobody")
        captured = capsys.readouterr()
        assert "Nobody" in captured.out

    def test_no_active_case(self, game, capsys):
        game.handle_slash_suspects_remove("/suspects remove Vera")
        captured = capsys.readouterr()
        assert "No active case" in captured.out

    def test_missing_name_arg(self, game_with_case, capsys):
        game_with_case.handle_slash_suspects_remove("/suspects remove")
        captured = capsys.readouterr()
        assert "Usage" in captured.out
