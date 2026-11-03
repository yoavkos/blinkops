"""CLI tests: commands run end to end against mocked HTTP (no real network calls)."""

import json

import pytest
import responses

from ticketforge import cli, config
from ticketforge.client import BASE_URL as BASE

TICKET = {
    "ref": "TF-1",
    "title": "Title",
    "description": "Desc",
    "stage": "open",
    "dependsOn": None,
    "customFields": {},
    "created": "c",
    "updated": "u",
}


@pytest.fixture(autouse=True)
def logged_in(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: ("alice", "secret"))


def run(monkeypatch, *argv, inputs=()):
    """Run the CLI with these arguments, answering prompts from inputs."""
    answers = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("sys.argv", ["ticketforge", *argv])
    cli.main()


@responses.activate
def test_update_with_flag_sends_change(monkeypatch):
    responses.get(f"{BASE}/workitem/TF-1", json={"workitem": TICKET})
    responses.put(f"{BASE}/workitem/TF-1", json={"workitem": TICKET})
    run(monkeypatch, "update", "tf-1", "--stage", "review")
    assert json.loads(responses.calls[1].request.body)["stage"] == "review"


@responses.activate
def test_update_without_changes_sends_nothing(monkeypatch, capsys):
    responses.get(f"{BASE}/workitem/TF-1", json={"workitem": TICKET})
    run(monkeypatch, "update", "TF-1", inputs=["", "", ""])  # Enter on every prompt
    assert len(responses.calls) == 1  # only the GET, no PUT
    assert "Nothing to change." in capsys.readouterr().out


@responses.activate
def test_create_keeps_description_flag(monkeypatch):
    responses.post(f"{BASE}/workitem/publish", json={"workitem": TICKET})
    run(monkeypatch, "create", "--description", "From flag", inputs=["Typed title"])
    sent = json.loads(responses.calls[0].request.body)
    assert sent["title"] == "Typed title"
    assert sent["description"] == "From flag"


@responses.activate
def test_setup_rejects_bad_password_without_saving(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "wrong")
    responses.get(f"{BASE}/workitems/mine", status=401, json={"err": "unauthorized", "message": "valid basic auth required"})
    with pytest.raises(SystemExit, match="Invalid username or password"):
        run(monkeypatch, "setup", inputs=["alice"])
    assert not (tmp_path / "config.json").exists()
