"""Client tests against mocked HTTP responses (no real network calls)."""

import json

import pytest
import requests
import responses

from ticketforge import client as client_module
from ticketforge.client import ApiError, TicketForgeClient

BASE = "https://tf.test/api"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)  # don't wait in retries
    return TicketForgeClient("alice", "secret", base_url=BASE)


@responses.activate
def test_sends_basic_auth(client):
    responses.get(f"{BASE}/workitems/mine", json={"workitems": [], "pagination": {}})
    client.list_tickets()
    # base64("alice:secret")
    assert responses.calls[0].request.headers["Authorization"] == "Basic YWxpY2U6c2VjcmV0"


@responses.activate
def test_passes_cursor_for_next_page(client):
    responses.get(f"{BASE}/workitems/mine", json={"workitems": [], "pagination": {}})
    client.list_tickets(cursor="2026-11-03T14:16:09.077Z:abc")
    assert "cursor=2026-11-03T14%3A16%3A09.077Z%3Aabc" in responses.calls[0].request.url


@responses.activate
def test_error_body_becomes_api_error(client):
    # The API reports a missing ticket as 400 (not 404) with err=not_found.
    responses.get(
        f"{BASE}/workitem/TF-9",
        status=400,
        json={"err": "not_found", "message": "workitem TF-9 does not exist", "retryable": False},
    )
    with pytest.raises(ApiError) as error:
        client.get_ticket("TF-9")
    assert error.value.status == 400
    assert error.value.code == "not_found"
    assert str(error.value) == "workitem TF-9 does not exist"


@responses.activate
def test_non_json_error_still_raises_api_error(client):
    responses.get(f"{BASE}/workitems/mine", status=502, body="Bad Gateway")
    with pytest.raises(ApiError, match="HTTP 502"):
        client.list_tickets()


@responses.activate
def test_retries_after_rate_limit(client):
    responses.get(f"{BASE}/workitems/mine", status=429, headers={"Retry-After": "1"}, json={"err": "rate_limit_exceeded"})
    responses.get(f"{BASE}/workitems/mine", json={"workitems": [], "pagination": {}})
    assert client.list_tickets()["workitems"] == []
    assert len(responses.calls) == 2


@responses.activate
def test_gives_up_after_max_retries(client):
    responses.get(f"{BASE}/workitems/mine", status=429, json={"err": "rate_limit_exceeded", "message": "slow down"})
    with pytest.raises(ApiError, match="slow down"):
        client.list_tickets()
    assert len(responses.calls) == client_module.MAX_RETRIES + 1


@responses.activate
def test_does_not_retry_post_on_server_error(client):
    # A retry could create the ticket twice.
    responses.post(f"{BASE}/workitem/publish", status=500, json={"message": "boom"})
    with pytest.raises(ApiError):
        client.create_ticket("Title")
    assert len(responses.calls) == 1


@responses.activate
def test_network_error_becomes_api_error(client):
    responses.get(f"{BASE}/workitems/mine", body=requests.ConnectionError())
    with pytest.raises(ApiError) as error:
        client.list_tickets()
    assert error.value.code == "network_error"


@responses.activate
def test_update_sends_every_field(client):
    # PUT replaces the whole ticket, so unchanged fields must be sent back.
    ticket = {
        "ref": "TF-1",
        "title": "Old title",
        "description": "Keep me",
        "stage": "open",
        "dependsOn": ["TF-0"],
        "customFields": {"priority": "high"},
    }
    responses.put(f"{BASE}/workitem/TF-1", json={"workitem": ticket})

    client.update_ticket(ticket, stage="review")

    sent = json.loads(responses.calls[0].request.body)
    assert sent == {
        "title": "Old title",
        "description": "Keep me",
        "stage": "review",
        "dependsOn": ["TF-0"],
        "customFields": {"priority": "high"},
    }


@responses.activate
def test_retry_after_with_decimal_seconds(client):
    responses.get(f"{BASE}/workitems/mine", status=429, headers={"Retry-After": "1.5"}, json={})
    responses.get(f"{BASE}/workitems/mine", json={"workitems": [], "pagination": {}})
    assert client.list_tickets()["workitems"] == []


@responses.activate
def test_non_json_success_raises_api_error(client):
    responses.get(f"{BASE}/workitems/mine", body="<html>")
    with pytest.raises(ApiError, match="Unexpected response"):
        client.list_tickets()
