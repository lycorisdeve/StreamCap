"""Brand colors and accessible light/dark palettes, independent of UI controls."""

import re
from dataclasses import dataclass

DEFAULT_COLOR = "#7555F6"
CLASSIC_COLOR = "#2196F3"
PRESET_COLORS = [
    ("dream_purple", DEFAULT_COLOR),
    ("classic_blue", "#2389F5"),
    ("mint_green", "#0EAFA0"),
    ("cherry_pink", "#EC599A"),
    ("vivid_orange", "#F28B30"),
    ("minimal_black", "#303443"),
]
LEGACY_COLORS = {
    "deeppurple": "#673AB7",
    "purple": "#9C27B0",
    "indigo": "#3F51B5",
    "blue": "#2196F3",
    "teal": "#009688",
    "deeporange": "#FF5722",
    "orange": "#FF9800",
    "pink": "#E91E63",
    "brown": "#795548",
    "bluegrey": "#607D8B",
    "green": "#4CAF50",
    "cyan": "#00BCD4",
    "lightblue": "#03A9F4",
}


def normalize_hex(value: str) -> str:
    """Accept opaque RGB shorthand/full HEX; reject incomplete or alpha values."""
    if not isinstance(value, str):
        raise ValueError("Enter a 3- or 6-digit HEX color")
    text = value.strip().removeprefix("#")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", text):
        raise ValueError("Enter a 3- or 6-digit HEX color")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    return "#" + text.upper()


def normalize_color(value) -> str:
    """Read old named Material colors without changing an existing user's choice."""
    if isinstance(value, str) and value.lower() in LEGACY_COLORS:
        return LEGACY_COLORS[value.lower()]
    try:
        return normalize_hex(value)
    except ValueError:
        return DEFAULT_COLOR


def normalize_appearance(config: dict) -> dict:
    mode = config.get("theme_mode", "light")
    style = config.get("theme_style", "glass")
    return {
        "theme_color": normalize_color(config.get("theme_color")),
        "theme_mode": mode if mode in ("light", "dark", "system") else "light",
        "theme_style": style if style in ("glass", "classic") else "glass",
    }


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def mix(color: str, other: str, amount: float) -> str:
    channels = [round(a + (b - a) * amount) for a, b in zip(_rgb(color), _rgb(other), strict=True)]
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _luminance(color: str) -> float:
    values = [channel / 255 for channel in _rgb(color)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def contrast_ratio(first: str, second: str) -> float:
    a, b = sorted((_luminance(first), _luminance(second)))
    return (b + 0.05) / (a + 0.05)


def _readable_accent(color: str, backgrounds: tuple[str, ...], dark: bool) -> str:
    if all(contrast_ratio(color, background) >= 4.5 for background in backgrounds):
        return color
    target = "#FFFFFF" if dark else "#000000"
    for step in range(1, 101):
        candidate = mix(color, target, step / 100)
        if all(contrast_ratio(candidate, background) >= 4.5 for background in backgrounds):
            return candidate
    return target


@dataclass(frozen=True)
class ThemeTokens:
    primary: str
    primary_hover: str
    primary_active: str
    primary_light: str
    primary_border: str
    primary_foreground: str
    focus_ring: str
    selected_background: str
    navigation_active: str
    interactive_accent: str
    background: str
    surface: str
    on_surface: str
    on_surface_variant: str
    is_dark: bool
    is_classic: bool = False


def build_tokens(color: str, dark: bool = False, style: str = "glass") -> ThemeTokens:
    base = normalize_color(color)
    classic = style == "classic"
    background = mix("#16181F", base, 0.04) if dark else mix("#FFFFFF", base, 0.035)
    if classic:
        background = "#181818" if dark else "#FFFFFF"
    surface = "#20222B" if dark else "#FFFFFF"
    primary = base
    foreground = max(("#FFFFFF", "#000000"), key=lambda value: contrast_ratio(value, primary))
    # The original light preset preserves Material blue and its white button labels.
    original_blue = classic and not dark and primary == CLASSIC_COLOR
    if original_blue:
        foreground = "#FFFFFF"
    # Move away from the foreground so hover/press retain readable button labels.
    shade = "#000000" if foreground == "#FFFFFF" else "#FFFFFF"
    if primary == shade:
        shade = foreground
    primary_light = mix(surface, base, 0.14 if dark else 0.08)
    selected_background = mix(surface, base, 0.26 if dark else 0.14)
    navigation_active = mix(surface, base, 0.30 if dark else 0.18)
    accent = _readable_accent(
        primary, (background, surface, primary_light, selected_background, navigation_active), dark
    )
    return ThemeTokens(
        primary=primary,
        primary_hover=mix(primary, shade, 0.08),
        primary_active=mix(primary, shade, 0.16),
        primary_light=primary_light,
        primary_border=mix(surface, base, 0.52 if dark else 0.24),
        primary_foreground=foreground,
        focus_ring=accent,
        selected_background=selected_background,
        navigation_active=navigation_active,
        interactive_accent=primary if original_blue else accent,
        background=background,
        surface=surface,
        on_surface="#F3F2F7" if dark else "#23222B",
        on_surface_variant="#C5C3D0" if dark else "#5F5B6B",
        is_dark=dark,
        is_classic=classic,
    )
