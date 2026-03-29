"""Data models for account information."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AccountResult:
    username: str
    password: str
    status: str = "UNKNOWN"  # VALID, INVALID, BANNED, ERROR, RATE_LIMITED
    region: str = ""
    summoner_name: str = ""
    level: int = 0
    rank: str = "UNRANKED"
    rp: int = 0
    blue_essence: int = 0
    champion_count: int = 0
    skin_count: int = 0
    skins: list[str] = field(default_factory=list)
    champions: list[str] = field(default_factory=list)
    email_verified: bool = False
    ban_status: str = ""
    error_message: str = ""

    @property
    def combo(self) -> str:
        return f"{self.username}:{self.password}"

    def summary_line(self) -> str:
        if self.status != "VALID":
            return f"{self.combo} | {self.status}"
        return (
            f"{self.combo} | {self.region} | Lvl {self.level} | {self.rank} | "
            f"RP: {self.rp} | BE: {self.blue_essence} | "
            f"Skins: {self.skin_count} | Champs: {self.champion_count}"
        )
