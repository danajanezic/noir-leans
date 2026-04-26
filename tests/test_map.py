import sqlite3
from noir.persistence.db import create_schema
from noir.neighborhoods import seed_neighborhoods
from noir.map import render_map
from noir.parser import parse_command, Intent


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    create_schema(c)
    seed_neighborhoods(c)
    return c


def test_render_map_returns_string():
    conn = _conn()
    result = render_map(conn, "french_quarter", {})
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_map_contains_neighborhood_name():
    conn = _conn()
    result = render_map(conn, "french_quarter", {})
    assert "FRENCH QTR" in result


def test_render_map_active_box_double_border():
    conn = _conn()
    result = render_map(conn, "french_quarter", {})
    assert "╔" in result
    assert "╝" in result


def test_render_map_different_active_neighborhood():
    conn = _conn()
    result = render_map(conn, "mid_city", {})
    assert "MID-CITY" in result


def test_parse_map_command():
    assert parse_command("map").intent == Intent.MAP


def test_parse_map_command_variants():
    assert parse_command("show map").intent == Intent.MAP
    assert parse_command("open map").intent == Intent.MAP
    assert parse_command("view map").intent == Intent.MAP
