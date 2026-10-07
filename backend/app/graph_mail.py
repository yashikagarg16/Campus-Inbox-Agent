"""Read-only Microsoft 365 / Outlook mail through Microsoft Graph.

Microsoft 365 no longer accepts passwords over IMAP, so college Outlook accounts are read
with Graph instead. The app asks only for the delegated Mail.Read and User.Read permissions: it can read
your mail and your own profile name, nothing else (no sending, deleting, moving, or marking as read).

Sign-in uses the device-code flow: the first run prints a short code to enter at
microsoft.com/devicelogin. The resulting token is cached in backend/.graph_token_cache.json
(gitignored) so later runs, including the web app's "Check inbox" button, don't ask again.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "User.Read"]  # read mail; read your own name (for redaction)
TOKEN_CACHE = Path(__file__).resolve().parent.parent / ".graph_token_cache.json"


class GraphAuthRequired(RuntimeError):
    """No cached sign-in and interactive sign-in isn't allowed here."""


def get_token(client_id: str, tenant: str = "organizations", cache_path: Path = TOKEN_CACHE,
              interactive: bool = True, show: Callable[[str], None] = print) -> str:
    import msal

    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}",
                                       token_cache=cache)
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    if not result:
        if not interactive:
            raise GraphAuthRequired("Not signed in to Outlook yet. Run: python -m tools.fetch_outlook --sign-in")
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Couldn't start Microsoft sign-in: {flow.get('error_description', flow)}")
        show(flow["message"])
        result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Microsoft sign-in failed: {result.get('error_description') or result.get('error')}")
    if cache.has_state_changed:
        cache_path.write_text(cache.serialize(), encoding="utf-8")
        try:
            os.chmod(cache_path, 0o600)
        except OSError:
            pass
    return result["access_token"]


def build_query(since: date, sender: str | None = None, keywords: list[str] | None = None) -> str:
    """KQL for Graph's $search."""
    parts = [f"received>={since:%Y-%m-%d}"]
    if keywords:
        parts.append("(" + " OR ".join(keywords) + ")")
    if sender:
        parts.append(f"from:{sender}")
    return " AND ".join(parts)


class GraphMail:
    def __init__(self, token: str, session=None):
        if session is None:
            import requests

            session = requests.Session()
        self._s = session
        self._s.headers["Authorization"] = f"Bearer {token}"

    def _search(self, query: str, select: str, limit: int) -> Iterator[dict]:
        url: str | None = f"{GRAPH}/me/messages"
        params: dict | None = {"$search": f'"{query}"', "$select": select, "$top": str(min(limit, 50))}
        count = 0
        while url and count < limit:
            r = self._s.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            for message in data.get("value", []):
                yield message
                count += 1
                if count >= limit:
                    return
            url, params = data.get("@odata.nextLink"), None  # nextLink already carries the query

    def identity(self) -> list[str]:
        """Your own name parts and mailbox name, so they can be redacted from collected emails."""
        r = self._s.get(f"{GRAPH}/me", params={"$select": "displayName,userPrincipalName,mail"}, timeout=30)
        r.raise_for_status()
        me = r.json()
        names = [me.get("displayName") or ""]
        names += [part for part in (me.get("displayName") or "").split() if len(part) >= 3]
        for address in (me.get("userPrincipalName"), me.get("mail")):
            if address:
                names.append(address.split("@")[0])
        return sorted({n for n in names if n}, key=len, reverse=True)

    def headers(self, since: date, keywords: list[str] | None = None, sender: str | None = None,
                limit: int = 500) -> Iterator[dict[str, str]]:
        query = build_query(since, sender, keywords)
        for m in self._search(query, "from,subject,receivedDateTime", limit):
            addr = (m.get("from") or {}).get("emailAddress") or {}
            sender_text = f"{addr.get('name', '')} <{addr.get('address', '')}>".strip()
            yield {"from": sender_text, "subject": m.get("subject") or "", "date": m.get("receivedDateTime") or ""}

    def raw_messages(self, since: date, sender: str | None = None, keywords: list[str] | None = None,
                     limit: int = 150) -> Iterator[bytes]:
        """Full messages as RFC 822 bytes (same format as IMAP or a downloaded .eml)."""
        for m in self._search(build_query(since, sender, keywords), "id", limit):
            r = self._s.get(f"{GRAPH}/me/messages/{quote(m['id'], safe='')}/$value", timeout=30)
            r.raise_for_status()
            yield r.content

