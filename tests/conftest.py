import pytest
import sqlite3
from noir.persistence.db import create_schema
from noir.llm.mock import MockLLMBackend


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def mock_llm():
    return MockLLMBackend()
