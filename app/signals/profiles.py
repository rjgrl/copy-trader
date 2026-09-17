"""Provider-specific parser profiles.

Each monitored Telegram source can be bound to a named profile with
explicit required fields and range/order semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.settings import ValidationRules
from app.signals.parser import DefaultSignalParser, ParseHandler


@dataclass(slots=True)
class ProviderProfile:
    """Configuration for how messages from a provider are parsed/validated."""

    name: str
    parser_name: str = "standard"
    require_direction: bool = True
    require_symbol: bool = True
    require_entry: bool = True
    require_tp: bool = True
    require_sl: bool = True
    min_tp_count: int = 1
    validate_tp_ordering: bool = True
    # How implicit entry ranges (without LIMIT keyword) are classified
    range_as: str = "limit"  # limit | market | entry_zone
    symbol_aliases: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def to_validation_rules(self) -> ValidationRules:
        return ValidationRules(
            require_direction=self.require_direction,
            require_symbol=self.require_symbol,
            require_entry=self.require_entry,
            require_tp=self.require_tp,
            require_sl=self.require_sl,
            min_tp_count=self.min_tp_count,
        )


STANDARD_PROFILE = ProviderProfile(
    name="standard",
    parser_name="standard",
    range_as="limit",
    description="Default multi-format parser; ranges treated as LIMIT orders",
)

GOLD_VIP_PROFILE = ProviderProfile(
    name="gold_vip",
    parser_name="gold_vip",
    range_as="limit",
    description="Gold / VIP channels — ranges are limit entry zones",
)

VICTOR_B_PROFILE = ProviderProfile(
    name="victor_b",
    parser_name="victor_b",
    range_as="limit",
    description="Victor B Gold & Forex VIP — XAU/USD range = SELL/BUY LIMIT zone",
)

DEFAULT_PROFILES: dict[str, ProviderProfile] = {
    STANDARD_PROFILE.name: STANDARD_PROFILE,
    GOLD_VIP_PROFILE.name: GOLD_VIP_PROFILE,
    VICTOR_B_PROFILE.name: VICTOR_B_PROFILE,
}


class ProfileRegistry:
    """Resolve parser + validation rules for a Telegram source."""

    def __init__(self, profiles: dict[str, ProviderProfile] | None = None) -> None:
        self._profiles = dict(profiles or DEFAULT_PROFILES)
        self._source_bindings: dict[int, str] = {}
        self._parsers: dict[str, DefaultSignalParser] = {}
        self._rebuild_parsers()

    def _rebuild_parsers(self) -> None:
        for profile in self._profiles.values():
            self._parsers[profile.parser_name] = DefaultSignalParser(
                range_as=profile.range_as,
                parser_name=profile.parser_name,
                profile_name=profile.name,
            )
        if "standard" not in self._parsers:
            self._parsers["standard"] = DefaultSignalParser(range_as="limit")

    def register_profile(self, profile: ProviderProfile) -> None:
        self._profiles[profile.name] = profile
        self._parsers[profile.parser_name] = DefaultSignalParser(
            range_as=profile.range_as,
            parser_name=profile.parser_name,
            profile_name=profile.name,
        )

    def register_parser(self, name: str, parser: DefaultSignalParser) -> None:
        self._parsers[name] = parser

    def bind_source(self, chat_id: int, profile_name: str) -> None:
        if profile_name not in self._profiles:
            raise KeyError(f"Unknown profile: {profile_name}")
        self._source_bindings[chat_id] = profile_name

    def get_profile_by_name(self, name: str) -> ProviderProfile:
        if name not in self._profiles:
            raise KeyError(f"Unknown profile: {name}")
        return self._profiles[name]

    def get_profile(self, chat_id: int | None = None) -> ProviderProfile:
        if chat_id is not None and chat_id in self._source_bindings:
            return self._profiles[self._source_bindings[chat_id]]
        return self._profiles["standard"]

    def get_parser(self, chat_id: int | None = None) -> DefaultSignalParser:
        profile = self.get_profile(chat_id)
        return self._parsers.get(profile.parser_name, self._parsers["standard"])

    def get_parser_for_profile(self, profile_name: str) -> DefaultSignalParser:
        profile = self.get_profile_by_name(profile_name)
        return self._parsers.get(profile.parser_name, self._parsers["standard"])

    def list_profiles(self) -> list[ProviderProfile]:
        return list(self._profiles.values())
