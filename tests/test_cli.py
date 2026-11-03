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
    responses.get(f"{BASE}/custom-fields", json={"customFields": [{"id": "f1", "name": "priority", "label": "Priority"}]})
    run(monkeypatch, "update", "TF-1", inputs=["", "", "", ""])  # Enter on every prompt
    assert len(responses.calls) == 2  # GET ticket and fields, no PUT
    assert "Nothing to change." in capsys.readouterr().out


@responses.activate
def test_update_remove_field_keeps_the_others(monkeypatch):
    ticket = {**TICKET, "customFields": {"priority": "high", "severity": "low"}}
    responses.get(f"{BASE}/workitem/TF-1", json={"workitem": ticket})
    responses.put(f"{BASE}/workitem/TF-1", json={"workitem": ticket})
    run(monkeypatch, "update", "TF-1", "--remove-field", "severity", "--field", "priority=low")
    assert json.loads(responses.calls[1].request.body)["customFields"] == {"priority": "low"}


@responses.activate
def test_create_sends_field_flags(monkeypatch):
    responses.post(f"{BASE}/workitem/publish", json={"workitem": TICKET})
    run(monkeypatch, "create", "--title", "T", "--field", "priority=high", "--field", "team=core")
    assert json.loads(responses.calls[0].request.body)["customFields"] == {"priority": "high", "team": "core"}


@responses.activate
def test_create_keeps_description_flag(monkeypatch):
    responses.get(f"{BASE}/custom-fields", json={"customFields": []})
    responses.post(f"{BASE}/workitem/publish", json={"workitem": TICKET})
    run(monkeypatch, "create", "--description", "From flag", inputs=["Typed title"])
    sent = json.loads(responses.calls[1].request.body)
    assert sent["title"] == "Typed title"
    assert sent["description"] == "From flag"


@responses.activate
def test_login_rejects_bad_password_without_saving(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "wrong")
    responses.get(f"{BASE}/workitems/mine", status=401, json={"err": "unauthorized", "message": "valid basic auth required"})
    with pytest.raises(SystemExit, match="Invalid username or password"):
        run(monkeypatch, "login", inputs=["alice"])
    assert not (tmp_path / "config.json").exists()


@responses.activate
def test_register_creates_account_and_saves_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "secret123")
    responses.post(f"{BASE}/user/register", json={"user": {"id": "1", "username": "alice"}})
    run(monkeypatch, "register", inputs=["alice"])
    assert json.loads(responses.calls[0].request.body) == {"username": "alice", "password": "secret123"}
    assert json.loads((tmp_path / "config.json").read_text())["username"] == "alice"


def test_register_stops_when_passwords_differ(monkeypatch):
    passwords = iter(["secret123", "typo"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(passwords))
    with pytest.raises(SystemExit, match="Passwords do not match"):
        run(monkeypatch, "register", inputs=["alice"])


@responses.activate
def test_show_without_ref_lets_user_pick_by_number(monkeypatch, capsys):
    page = {"workitems": [{**TICKET, "ref": "TF-2"}, TICKET], "pagination": {"hasMore": False}}
    responses.get(f"{BASE}/workitems/mine", json=page)
    responses.get(f"{BASE}/workitem/TF-1", json={"workitem": TICKET})
    run(monkeypatch, "show", inputs=["5", "2"])  # 5 is out of range, then pick the 2nd
    assert "Please enter a number from 1 to 2." in capsys.readouterr().out
    assert responses.calls[1].request.url.startswith(f"{BASE}/workitem/TF-1")
