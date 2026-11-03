import requests

BASE_URL = "https://integrations-assignment-ticketforge.vercel.app/api/tforge"
TIMEOUT = 10


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


class TicketForgeClient:
    def __init__(self, username, password, base_url=BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.auth = (username, password)

    def _request(self, method, path, **kwargs):
        response = self.session.request(method, self.base_url + path, timeout=TIMEOUT, **kwargs)
        if response.ok:
            return response.json()

        try:
            body = response.json()
        except ValueError:
            body = {}
        message = body.get("message") or f"HTTP {response.status_code}"
        raise ApiError(response.status_code, body.get("err"), message)
