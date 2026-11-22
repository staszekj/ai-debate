from pathlib import Path

from debate_core.config import Settings, find_env_file
from debate_core.llms import make_debater


def test_base_url_defaults_to_shared_server() -> None:
    s = Settings(debater_base_url="http://shared/v1")
    assert s.base_url_for("dogs") == "http://shared/v1"
    assert s.base_url_for("cats") == "http://shared/v1"


def test_base_url_per_side_override() -> None:
    s = Settings(debater_base_url="http://shared/v1", cats_base_url="http://cats/v1")
    assert s.base_url_for("dogs") == "http://shared/v1"
    assert s.base_url_for("cats") == "http://cats/v1"


def test_experts_use_independent_endpoints_and_models() -> None:
    settings = Settings(dogs_base_url="http://dogs/v1", cats_base_url="http://cats/v1",
                        dogs_model="dogs-slm", cats_model="cats-slm")
    dogs = make_debater("dogs", settings)
    cats = make_debater("cats", settings)
    assert (dogs.openai_api_base, dogs.model_name) == ("http://dogs/v1", "dogs-slm")
    assert (cats.openai_api_base, cats.model_name) == ("http://cats/v1", "cats-slm")


def test_find_env_file_walks_up(tmp_path: Path) -> None:
    (tmp_path / ".env.local").write_text("HOST_MODEL=x:y\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_env_file(nested) == tmp_path / ".env.local"
