from pathlib import Path

from debate_core.config import Settings, find_env_file


def test_base_url_defaults_to_shared_server() -> None:
    s = Settings(debater_base_url="http://shared/v1")
    assert s.base_url_for("dogs") == "http://shared/v1"
    assert s.base_url_for("cats") == "http://shared/v1"


def test_base_url_per_side_override() -> None:
    s = Settings(debater_base_url="http://shared/v1", cats_base_url="http://cats/v1")
    assert s.base_url_for("dogs") == "http://shared/v1"
    assert s.base_url_for("cats") == "http://cats/v1"


def test_find_env_file_walks_up(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("HOST_MODEL=x:y\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_env_file(nested) == tmp_path / ".env.local"
