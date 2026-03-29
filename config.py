"""Configuration constants for the LoL Account Checker."""

# Riot Auth endpoints
AUTH_URL = "https://auth.riotgames.com/api/v1/authorization"
ENTITLEMENTS_URL = "https://entitlements.auth.riotgames.com/api/token/v1"
USERINFO_URL = "https://auth.riotgames.com/userinfo"
STORE_URL = "https://{region}.store.leagueoflegends.com/storefront/v3/view/misc"
INVENTORY_URL = "https://{region}.store.leagueoflegends.com/storefront/v3/history/purchase"

# Region mappings
REGION_MAP = {
    "BR": "br",
    "EUNE": "eune",
    "EUW": "euw",
    "JP": "jp",
    "KR": "kr",
    "LAN": "lan",
    "LAS": "las",
    "NA": "na",
    "OCE": "oce",
    "PH": "ph",
    "RU": "ru",
    "SG": "sg",
    "TH": "th",
    "TR": "tr",
    "TW": "tw",
    "VN": "vn",
}

PLATFORM_MAP = {
    "BR": "BR1",
    "EUNE": "EUN1",
    "EUW": "EUW1",
    "JP": "JP1",
    "KR": "KR",
    "LAN": "LA1",
    "LAS": "LA2",
    "NA": "NA1",
    "OCE": "OC1",
    "PH": "PH2",
    "RU": "RU",
    "SG": "SG2",
    "TH": "TH2",
    "TR": "TR1",
    "TW": "TW2",
    "VN": "VN2",
}

RANKED_TIERS = {
    "IRON": 0,
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
    "PLATINUM": 4,
    "EMERALD": 5,
    "DIAMOND": 6,
    "MASTER": 7,
    "GRANDMASTER": 8,
    "CHALLENGER": 9,
}

# Concurrency
DEFAULT_THREADS = 10
DEFAULT_TIMEOUT = 15
RETRY_ATTEMPTS = 2
