"""HTTP client for the TicketForge API. No printing or prompting here."""

import requests

BASE_URL = "https://integrations-assignment-ticketforge.vercel.app/api/tforge"
TIMEOUT = 10


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
        response = self.session.request(method, self.base_url + path, timeout=TIMEOUT, **kwargs)
        if response.ok:
            return response.json()

        # Errors look like {"err": "...", "message": "...", "retryable": ...}
        try:
            body = response.json()
        except ValueError:
            body = {}
        message = body.get("message") or f"HTTP {response.status_code}"
        raise ApiError(response.status_code, body.get("err"), message)

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
