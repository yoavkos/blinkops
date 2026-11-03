"""HTTP client for the TicketForge API. No printing or prompting here."""

import logging
import time

import requests

BASE_URL = "https://integrations-assignment-ticketforge.vercel.app/api/tforge"
TIMEOUT = 10
MAX_RETRIES = 3

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Error returned by the API: HTTP status, short error code and message."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


class TicketForgeClient:
    def __init__(self, username, password, base_url=BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.auth = (username, password)  # Basic auth on every request

    def _request(self, method, path, **kwargs):
        """Send a request and return the JSON body, or raise ApiError."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.session.request(method, self.base_url + path, timeout=TIMEOUT, **kwargs)
            except requests.RequestException as e:
                raise ApiError(None, "network_error", f"Could not reach TicketForge ({type(e).__name__}).") from e

            if attempt < MAX_RETRIES and self._should_retry(method, response):
                try:
                    delay = float(response.headers["Retry-After"])
                except (KeyError, ValueError):  # missing, or an HTTP date
                    delay = 2 ** attempt
                log.warning("TicketForge returned %s, retrying in %ss...", response.status_code, delay)
                time.sleep(delay)
                continue
            break

        if response.ok:
            try:
                return response.json()
            except ValueError:
                raise ApiError(response.status_code, "bad_response", "Unexpected response from TicketForge.") from None

        # Errors look like {"err": "...", "message": "...", "retryable": ...}
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = body.get("message") or f"HTTP {response.status_code}"
        raise ApiError(response.status_code, body.get("err"), message)

    @staticmethod
    def _should_retry(method, response):
        # 429 means the request was not processed, so it is always safe to retry.
        # Retrying a POST after a 5xx could create a duplicate ticket.
        if response.status_code == 429:
            return True
        return response.status_code >= 500 and method != "POST"

    def list_tickets(self, limit=None, cursor=None):
        """Return one page: {"workitems": [...], "pagination": {...}}."""
        params = {"limit": limit, "cursor": cursor}
        return self._request("GET", "/workitems/mine", params=params)

    def get_ticket(self, ref):
        # view=deep includes customFields and dependsOn, which the list omits
        return self._request("GET", f"/workitem/{ref}", params={"view": "deep"})["workitem"]

    def create_ticket(self, title, description=None, depends_on=None):
        body = {"title": title, "description": description, "dependsOn": depends_on}
        return self._request("POST", "/workitem/publish", json=body)["workitem"]

    def update_ticket(self, ticket, **changes):
        """Apply changes to a ticket fetched with get_ticket().

        PUT replaces the whole ticket (missing fields are cleared), so we
        send every current field back along with the changes.
        """
        body = {
            "title": ticket["title"],
            "description": ticket.get("description"),
            "stage": ticket["stage"],
            "dependsOn": ticket.get("dependsOn"),
            "customFields": ticket.get("customFields") or {},
        }
        body.update(changes)
        return self._request("PUT", f"/workitem/{ticket['ref']}", json=body)["workitem"]

    def list_fields(self):
        return self._request("GET", "/custom-fields")["customFields"]

    def add_field(self, name, label):
        return self._request("POST", "/custom-fields", json={"name": name, "label": label})["customField"]

    def delete_field(self, field_id):
        self._request("DELETE", f"/custom-fields/{field_id}")
