import colorsys
import time

import flet as ft

from ...themes.theme_tokens import DEFAULT_COLOR, PRESET_COLORS, normalize_hex


class AppearanceSettings(ft.Column):
    """Session-local appearance draft; only Apply persists it."""

    PICKER_WIDTH = 264
    PICKER_HEIGHT = 148

    def __init__(self, app):
        super().__init__(spacing=20, scroll=ft.ScrollMode.AUTO, expand=True)
        self.app = app
        self.manager = app.theme_manager
        self._ = app.language_manager.language["appearance_settings"]
        self._unsubscribe = None
        self._last_preview = 0.0
        self._hex_editing = False
        self._invalid_hex = False
        self._changing_picker = False
        self._busy = False
        self._mounted = False
        self.hue, self.saturation, self.value = 0.0, 0.0, 0.0
        self.mode = ft.Dropdown(
            label=self._["mode"],
            width=264,
            options=[ft.dropdown.DropdownOption(key=key, text=self._[key]) for key in ("light", "dark", "system")],
            on_select=self.mode_changed,
        )
        self.hex_input = ft.TextField(
            label=self._["hex"],
            width=264,
            max_length=7,
            on_change=self.hex_changed,
            on_blur=self.hex_blurred,
            on_submit=self.hex_blurred,
        )
        self.color_plane = ft.Container(
            width=self.PICKER_WIDTH,
            height=self.PICKER_HEIGHT,
            border_radius=8,
        )
        self.cursor = ft.Container(
            width=14,
            height=14,
            border_radius=7,
            border=ft.Border.all(2, ft.Colors.WHITE),
            shadow=ft.BoxShadow(blur_radius=2, color=ft.Colors.BLACK),
        )
        self.picker = ft.GestureDetector(
            content=ft.Stack(
                [
                    self.color_plane,
                    ft.Container(
                        width=self.PICKER_WIDTH,
                        height=self.PICKER_HEIGHT,
                        border_radius=8,
                        gradient=ft.LinearGradient(
                            begin=ft.Alignment.TOP_CENTER,
                            end=ft.Alignment.BOTTOM_CENTER,
                            colors=[ft.Colors.TRANSPARENT, ft.Colors.BLACK],
                        ),
                    ),
                    self.cursor,
                ],
                width=self.PICKER_WIDTH,
                height=self.PICKER_HEIGHT,
            ),
            mouse_cursor=ft.MouseCursor.CLICK,
            drag_interval=50,
            on_tap_down=self.pick_color,
            on_tap_up=self.finish_pick,
            on_pan_start=self.pick_color,
            on_pan_update=self.pick_color,
            on_pan_end=self.finish_pick,
        )
        self.hue_slider = ft.Slider(
            min=0,
            max=360,
            value=0,
            label="{value}°",
            width=264,
            on_change=self.hue_changed,
            on_change_end=self.hue_finished,
        )
        self.saturation_slider = ft.Slider(
            min=0,
            max=100,
            value=0,
            label="{value}%",
            width=264,
            on_change=self.saturation_changed,
            on_change_end=self.finish_slider,
        )
        self.value_slider = ft.Slider(
            min=0,
            max=100,
            value=0,
            label="{value}%",
            width=264,
            on_change=self.value_changed,
            on_change_end=self.finish_slider,
        )
        self.preset_controls = []
        for key, color in PRESET_COLORS:
            swatch = ft.Container(
                content=ft.Row(
                    [ft.Container(width=22, height=22, bgcolor=color, border_radius=11), ft.Text(self._[key])],
                    spacing=8,
                ),
                width=142,
                padding=10,
                border_radius=8,
                ink=True,
                tooltip=f"{self._[key]} {color}",
                on_click=lambda _, selected=color: self.select_color(selected),
                data=color,
            )
            self.preset_controls.append(swatch)
        self.apply_button = ft.FilledButton(self._["apply"], on_click=self.apply_changes, disabled=True)
        self.cancel_button = ft.TextButton(self._["cancel"], on_click=self.cancel_changes)
        self.reset_button = ft.TextButton(self._["restore"], icon=ft.Icons.RESTORE, on_click=self.restore_defaults)
        self.preview_button = ft.FilledButton(self._["preview_button"], icon=ft.Icons.ADD)
        self.preview_filter = ft.Container(
            content=ft.Text(self._["preview_filter"], size=12), padding=8, border_radius=20
        )
        self.preview_navigation = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.DASHBOARD, size=18), ft.Text(self._["preview_navigation"])]),
            padding=10,
            border_radius=8,
        )
        self.preview_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(self._["preview_card"], weight=ft.FontWeight.W_600),
                    ft.Text("00:12:34", size=12),
                    ft.Row([ft.Icon(ft.Icons.PLAY_CIRCLE), ft.Icon(ft.Icons.FOLDER_OUTLINED)]),
                ],
                spacing=8,
            ),
            padding=12,
            border_radius=8,
        )
        self.preview_surface = ft.Container(
            content=ft.Column(
                [
                    self.preview_navigation,
                    ft.Row([self.preview_button, self.preview_filter], wrap=True),
                    ft.TextField(label=self._["preview_input"], dense=True),
                    self.preview_card,
                ],
                spacing=16,
            ),
            width=264,
            padding=16,
            border_radius=12,
        )
        self.controls = [
            ft.Text(self._["title"], size=20, weight=ft.FontWeight.W_600),
            ft.Text(self._["description"], color=ft.Colors.ON_SURFACE_VARIANT),
            self.mode,
            ft.Text(self._["presets"], weight=ft.FontWeight.W_600),
            ft.Row(self.preset_controls, wrap=True, spacing=8, run_spacing=8),
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(self._["custom"], weight=ft.FontWeight.W_600),
                            self.picker,
                            ft.Text(self._["hue"], size=12),
                            self.hue_slider,
                            self.hex_input,
                            ft.Text(self._["saturation"], size=12),
                            self.saturation_slider,
                            ft.Text(self._["value"], size=12),
                            self.value_slider,
                        ],
                        spacing=8,
                        width=264,
                    ),
                    ft.Column(
                        [ft.Text(self._["preview"], weight=ft.FontWeight.W_600), self.preview_surface],
                        spacing=12,
                    ),
                ],
                wrap=True,
                spacing=32,
                run_spacing=24,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            ft.Row([self.apply_button, self.cancel_button, self.reset_button], wrap=True, spacing=8),
        ]
        self.refresh_theme()
        self._unsubscribe = self.manager.subscribe(self.refresh_theme)

    def dispose(self):
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def will_unmount(self):
        self._mounted = False
        self.dispose()

    def did_mount(self):
        self._mounted = True
        if self._unsubscribe is None:
            self._unsubscribe = self.manager.subscribe(self.refresh_theme)
        self.refresh_theme()

    def _update(self):
        if self._mounted:
            self.update()

    @staticmethod
    def hsv_hex(hue, saturation, value):
        red, green, blue = colorsys.hsv_to_rgb((hue % 360) / 360, saturation, value)
        return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"

    def refresh_theme(self):
        config = self.manager.draft or self.manager.committed
        color = config["theme_color"]
        self.mode.value = config["theme_mode"]
        if not self._changing_picker:
            rgb = tuple(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
            hue, self.saturation, self.value = colorsys.rgb_to_hsv(*rgb)
            if self.saturation and self.value:
                self.hue = hue * 360
        if not self._hex_editing:
            self.hex_input.value = color
        self.hue_slider.value = self.hue
        self.saturation_slider.value = self.saturation * 100
        self.value_slider.value = self.value * 100
        self.color_plane.gradient = ft.LinearGradient(
            begin=ft.Alignment.CENTER_LEFT,
            end=ft.Alignment.CENTER_RIGHT,
            colors=[ft.Colors.WHITE, self.hsv_hex(self.hue, 1, 1)],
        )
        self.cursor.left = max(0, min(self.PICKER_WIDTH - 14, self.saturation * self.PICKER_WIDTH - 7))
        self.cursor.top = max(0, min(self.PICKER_HEIGHT - 14, (1 - self.value) * self.PICKER_HEIGHT - 7))
        tokens = self.manager.tokens
        for swatch in self.preset_controls:
            selected = swatch.data == color
            swatch.bgcolor = tokens.selected_background if selected else tokens.surface
            swatch.border = ft.Border.all(2 if selected else 1, tokens.primary if selected else tokens.primary_border)
        self.preview_surface.bgcolor = tokens.background
        self.preview_navigation.bgcolor = tokens.navigation_active
        for control in self.preview_navigation.content.controls:
            control.color = tokens.interactive_accent
        self.preview_filter.bgcolor = tokens.primary
        self.preview_filter.content.color = tokens.primary_foreground
        self.preview_card.bgcolor = tokens.selected_background
        self.preview_card.border = ft.Border.all(1, tokens.primary_border)
        self.apply_button.disabled = self._invalid_hex or self._busy or self.manager.draft is None
        self._update()

    def select_color(self, color):
        self._hex_editing = False
        self._invalid_hex = False
        self.hex_input.error_text = None
        self.manager.preview(color=color)
        self.refresh_theme()

    def hex_changed(self, event):
        self._hex_editing = True
        self.hex_input.value = event.control.value
        try:
            color = normalize_hex(self.hex_input.value or "")
        except ValueError:
            self._invalid_hex = True
            self.hex_input.error_text = self._["invalid_hex"]
            self.apply_button.disabled = True
            self._update()
            return
        self._invalid_hex = False
        self.hex_input.error_text = None
        self.manager.preview(color=color)
        self.refresh_theme()

    def hex_blurred(self, _):
        if not self._invalid_hex:
            self._hex_editing = False
            self.refresh_theme()

    def mode_changed(self, event):
        self.manager.preview(mode=event.control.value)

    def _preview_picker(self, force=False):
        now = time.monotonic()
        if not force and now - self._last_preview < 0.05:
            return
        self._last_preview = now
        self._changing_picker = True
        try:
            self.select_color(self.hsv_hex(self.hue, self.saturation, self.value))
        finally:
            self._changing_picker = False

    def pick_color(self, event):
        position = event.local_position
        if position is not None:
            self.saturation = min(1.0, max(0.0, position.x / self.PICKER_WIDTH))
            self.value = 1.0 - min(1.0, max(0.0, position.y / self.PICKER_HEIGHT))
        self._preview_picker()

    def finish_pick(self, event):
        self.pick_color(event)
        self._preview_picker(force=True)

    def hue_changed(self, event):
        self.hue = float(event.control.value)
        self._preview_picker()

    def hue_finished(self, event):
        self.hue = float(event.control.value)
        self._preview_picker(force=True)

    def saturation_changed(self, event):
        self.saturation = float(event.control.value) / 100
        self._preview_picker()

    def value_changed(self, event):
        self.value = float(event.control.value) / 100
        self._preview_picker()

    def finish_slider(self, event):
        if event.control is self.saturation_slider:
            self.saturation = float(event.control.value) / 100
        else:
            self.value = float(event.control.value) / 100
        self._preview_picker(force=True)

    async def apply_changes(self, _):
        if self._invalid_hex or self._busy:
            return
        self._busy = True
        self.refresh_theme()
        try:
            await self.manager.commit_preview()
        except Exception:
            await self.app.snack_bar.show_snack_bar(self._["save_failed"], bgcolor=ft.Colors.RED)
        else:
            await self.app.snack_bar.show_snack_bar(self._["saved"])
        finally:
            self._busy = False
            self.refresh_theme()

    def cancel_changes(self, _):
        self._invalid_hex = False
        self._hex_editing = False
        self.hex_input.error_text = None
        self.manager.cancel_preview()
        self.refresh_theme()

    def restore_defaults(self, _):
        self._invalid_hex = False
        self._hex_editing = False
        self.hex_input.error_text = None
        self.manager.preview(color=DEFAULT_COLOR, mode="light")
        self.refresh_theme()
