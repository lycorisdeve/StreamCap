"""Map semantic theme tokens to Flet's global component themes."""

import flet as ft

from .theme_tokens import DEFAULT_COLOR, ThemeTokens, build_tokens, contrast_ratio


def create_theme(custom_font: str, tokens: ThemeTokens) -> ft.Theme:
    state = ft.ControlState
    overlay = {
        state.HOVERED: tokens.primary_light,
        state.PRESSED: tokens.selected_background,
        state.FOCUSED: tokens.selected_background,
    }
    filled_style = ft.ButtonStyle(
        bgcolor={
            state.DISABLED: tokens.primary_border,
            state.HOVERED: tokens.primary_hover,
            state.PRESSED: tokens.primary_active,
            state.DEFAULT: tokens.primary,
        },
        color={state.DISABLED: tokens.on_surface_variant, state.DEFAULT: tokens.primary_foreground},
    )
    text_style = ft.ButtonStyle(color=tokens.interactive_accent, overlay_color=overlay)
    accent_foreground = max(("#FFFFFF", "#000000"), key=lambda color: contrast_ratio(color, tokens.interactive_accent))
    return ft.Theme(
        font_family=custom_font,
        text_theme=ft.TextTheme(
            **{
                name: ft.TextStyle(color=tokens.on_surface, font_family=custom_font)
                for name in (
                    "body_small",
                    "body_medium",
                    "body_large",
                    "display_small",
                    "display_medium",
                    "display_large",
                    "headline_small",
                    "headline_medium",
                    "headline_large",
                    "title_small",
                    "title_medium",
                    "title_large",
                    "label_small",
                    "label_medium",
                    "label_large",
                )
            }
        ),
        use_material3=True,
        color_scheme_seed=tokens.primary,
        color_scheme=ft.ColorScheme(
            primary=tokens.interactive_accent,
            on_primary=accent_foreground,
            primary_container=tokens.primary_light,
            on_primary_container=tokens.on_surface,
            secondary=tokens.interactive_accent,
            on_secondary=accent_foreground,
            secondary_container=tokens.navigation_active,
            on_secondary_container=tokens.on_surface,
            tertiary=tokens.interactive_accent,
            on_tertiary=accent_foreground,
            surface=tokens.surface,
            on_surface=tokens.on_surface,
            on_surface_variant=tokens.on_surface_variant,
            outline=tokens.primary_border,
            outline_variant=tokens.primary_border,
            surface_container_lowest=tokens.surface,
            surface_container_low=tokens.background,
            surface_container=tokens.background,
            surface_container_high=tokens.primary_light,
            surface_container_highest=tokens.selected_background,
        ),
        scaffold_bgcolor=tokens.background,
        hover_color=tokens.primary_light,
        focus_color=tokens.selected_background,
        highlight_color=tokens.selected_background,
        splash_color=tokens.primary_light,
        button_theme=ft.ButtonTheme(style=text_style),
        filled_button_theme=ft.FilledButtonTheme(style=filled_style),
        text_button_theme=ft.TextButtonTheme(style=text_style),
        outlined_button_theme=ft.OutlinedButtonTheme(style=text_style),
        icon_button_theme=ft.IconButtonTheme(style=text_style),
        input_decoration_theme=ft.InputDecorationTheme(
            border={
                state.DEFAULT: ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(1, tokens.primary_border)),
                state.FOCUSED: ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(2, tokens.focus_ring)),
            },
            hint_style=ft.TextStyle(color=tokens.on_surface_variant),
            fill_color=tokens.surface,
            hover_color=tokens.primary_light,
            focus_color=tokens.primary_light,
        ),
        checkbox_theme=ft.CheckboxTheme(
            fill_color={state.SELECTED: tokens.primary},
            check_color={state.SELECTED: tokens.primary_foreground},
            overlay_color=overlay,
        ),
        radio_theme=ft.RadioTheme(fill_color={state.SELECTED: tokens.primary}, overlay_color=overlay),
        switch_theme=ft.SwitchTheme(
            track_color={state.SELECTED: tokens.primary},
            thumb_color={state.SELECTED: tokens.primary_foreground},
            overlay_color=overlay,
        ),
        dialog_theme=ft.DialogTheme(bgcolor=tokens.surface),
        popup_menu_theme=ft.PopupMenuTheme(color=tokens.surface),
    )


def create_light_theme(custom_font: str, color: str = DEFAULT_COLOR) -> ft.Theme:
    return create_theme(custom_font, build_tokens(color))


def create_dark_theme(custom_font: str, color: str = DEFAULT_COLOR) -> ft.Theme:
    return create_theme(custom_font, build_tokens(color, dark=True))
