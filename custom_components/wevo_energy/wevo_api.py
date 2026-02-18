from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession, WSMsgType


class WevoApiError(Exception):
    """Raised when Wevo API returns an error."""


@dataclass
class WevoTokens:
    access_token: str
    refresh_token: str | None
    expires_at: int
    cognito_username: str


class WevoApiClient:
    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        cognito_region: str,
        cognito_client_id: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._cognito_region = cognito_region
        self._cognito_client_id = cognito_client_id

    @property
    def ws_url(self) -> str:
        return self._base_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws"

    @property
    def cognito_url(self) -> str:
        return f"https://cognito-idp.{self._cognito_region}.amazonaws.com/"

    async def login(self, email: str, password: str) -> WevoTokens:
        usernames = [email, f"wevo/{email}"] if not email.startswith("wevo/") else [email]
        last_error: Exception | None = None

        for username in usernames:
            try:
                payload = {
                    "AuthFlow": "USER_PASSWORD_AUTH",
                    "ClientId": self._cognito_client_id,
                    "AuthParameters": {"USERNAME": username, "PASSWORD": password},
                }
                data = await self._cognito_call(payload)
                auth = data.get("AuthenticationResult", {})
                access = auth.get("AccessToken")
                refresh = auth.get("RefreshToken")
                expires_in = int(auth.get("ExpiresIn", 3600))
                if not access:
                    raise WevoApiError("Missing access token in login response")
                return WevoTokens(
                    access_token=access,
                    refresh_token=refresh,
                    expires_at=int(time.time()) + expires_in,
                    cognito_username=username,
                )
            except Exception as err:  # noqa: BLE001
                last_error = err

        raise WevoApiError("Unable to login to Wevo") from last_error

    async def refresh_access_token(self, refresh_token: str, username: str | None = None) -> WevoTokens:
        payload = {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": self._cognito_client_id,
            "AuthParameters": {"REFRESH_TOKEN": refresh_token},
        }
        data = await self._cognito_call(payload)
        auth = data.get("AuthenticationResult", {})
        access = auth.get("AccessToken")
        expires_in = int(auth.get("ExpiresIn", 3600))
        if not access:
            raise WevoApiError("Missing access token in refresh response")

        return WevoTokens(
            access_token=access,
            refresh_token=refresh_token,
            expires_at=int(time.time()) + expires_in,
            cognito_username=username or "",
        )

    async def get_user_details(self, access_token: str) -> dict[str, Any]:
        return await self._rest_get("/rest/user/details?refreshCognitoData=false", access_token)

    async def get_transactions(self, access_token: str) -> list[dict[str, Any]]:
        data = await self._rest_get("/rest/transactions", access_token)
        return data if isinstance(data, list) else []

    async def get_state(self, access_token: str, charger_identifier: str, connector: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._session.ws_connect(self.ws_url, headers=headers, heartbeat=20) as ws:
            await ws.send_json(
                {
                    "command": "getState",
                    "chargerIdentifier": charger_identifier,
                    "connector": connector,
                }
            )

            for _ in range(5):
                msg = await ws.receive(timeout=8)
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("chargerIdentifier") == charger_identifier:
                        return data
                elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        raise WevoApiError("No state response from Wevo websocket")

    async def authorize(self, access_token: str, charger_identifier: str, connector: str) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._session.ws_connect(self.ws_url, headers=headers, heartbeat=20) as ws:
            await ws.send_json(
                {
                    "command": "authorize",
                    "chargerIdentifier": charger_identifier,
                    "connector": connector,
                }
            )

            for _ in range(6):
                msg = await ws.receive(timeout=1)
                if msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

    async def _rest_get(self, path: str, access_token: str) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._session.get(url, headers=headers, timeout=15) as resp:
            if resp.status >= 400:
                txt = await resp.text()
                raise WevoApiError(f"GET {path} failed ({resp.status}): {txt[:200]}")
            return await resp.json()

    async def _cognito_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            "Content-Type": "application/x-amz-json-1.1",
        }
        async with self._session.post(self.cognito_url, headers=headers, json=payload, timeout=20) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400 or "__type" in data:
                message = data.get("message") or data.get("Message") or str(data)
                raise WevoApiError(message)
            return data
