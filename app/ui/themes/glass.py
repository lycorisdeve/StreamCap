"""Shared, theme-derived materials for the recording workspace."""

import flet as ft

from .theme_tokens import mix

CARD_RADIUS = 13
# The action buttons' 36 px hit area already includes the inset below their icons.
CARD_HEIGHT = 108
CONTROL_RADIUS = 20
CONTROL_HEIGHT = 40
FILTER_HEIGHT = 36
CARD_BORDER_WIDTH = 1
HOVER_DURATION = 200


def glass_gradient(tokens, tinted=False):
    base = tokens.selected_background if tinted else tokens.surface
    return ft.LinearGradient(
        begin=ft.Alignment.TOP_LEFT,
        end=ft.Alignment.BOTTOM_RIGHT,
        colors=[base, base]
        if tokens.is_classic
        else [ft.Colors.with_opacity(0.9, base), ft.Colors.with_opacity(0.78, base)],
    )


def glass_shadows(tokens, hovered=False):
    if tokens.is_classic:
        return None
    ink = mix(tokens.primary, tokens.on_surface, 0.55)
    return [
        ft.BoxShadow(
            color=ft.Colors.with_opacity(0.14 if hovered else 0.09, ink),
            blur_radius=18 if hovered else 12,
            spread_radius=-3,
            offset=ft.Offset(0, 6 if hovered else 3),
        ),
        ft.BoxShadow(color=ft.Colors.with_opacity(0.06, ink), blur_radius=3, offset=ft.Offset(0, 1)),
    ]


def glass_border(tokens):
    return ft.Border.all(1, ft.Colors.with_opacity(0.7, tokens.primary_border))
