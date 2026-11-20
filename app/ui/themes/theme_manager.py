"""Session preview and application of the globally committed appearance."""

import asyncio
import sys

import flet as ft

from ...utils.logger import logger
from .glass import HOVER_DURATION
from .theme import create_dark_theme, create_light_theme
from .theme_tokens import build_tokens, normalize_appearance, normalize_hex


class ThemeManager:
    def __init__(self, app):
        self.app = app
        self.page = app.page
        self.committed, self._revision = app.services.snapshot_appearance()
        self.committed = normalize_appearance(self.committed)
        self.draft = None
        self._observers = []
        self._disposed = False
        self._semantics = ft.SemanticsService()
        self.custom_font = "AlibabaPuHuiTi Light Mac" if sys.platform == "darwin" else "AlibabaPuHuiTi Light"
        self.page.fonts = {
            "AlibabaPuHuiTi Light": "/fonts/AlibabaPuHuiTi-2/AlibabaPuHuiTi-2-45-Light.otf",
            "AlibabaPuHuiTi Light Mac": "/fonts/AlibabaPuHuiTi-2/AlibabaPuHuiTi-2-45-Light-Mac.otf",
        }
        self._brightness_handler = self._on_brightness_change
        self.page.on_platform_brightness_change = self._brightness_handler
        self.apply(update=False)

    @property
    def effective_config(self):
        return self.draft if self.draft is not None else self.committed

    def _on_brightness_change(self, _):
        if self.effective_config["theme_mode"] == "system":
            self.apply()

    def apply(self, update=True):
        if self._disposed:
            return
        config = self.effective_config
        color, mode = config["theme_color"], config["theme_mode"]
        style = config["theme_style"]
        dark = mode == "dark" or (mode == "system" and self.page.platform_brightness == ft.Brightness.DARK)
        self.tokens = build_tokens(color, dark=dark, style=style)
        self.page.theme = create_light_theme(self.custom_font, color, style)
        self.page.dark_theme = create_dark_theme(self.custom_font, color, style)
        self.page.theme_mode = ft.ThemeMode(mode)
        self.page.bgcolor = self.tokens.background
        for callback in tuple(self._observers):
            try:
                callback()
            except Exception as error:
                logger.debug(f"Theme observer update failed: {error}")
        if update:
            try:
                self.page.update()
            except (ft.FletPageDisconnectedException, AssertionError):
                pass

    def preview(self, color=None, mode=None, style=None):
        draft = dict(self.effective_config)
        if color is not None:
            draft["theme_color"] = normalize_hex(color)
        if mode is not None:
            if mode not in ("light", "dark", "system"):
                raise ValueError("Unknown theme mode")
            draft["theme_mode"] = mode
        if style is not None:
            if style not in ("glass", "classic"):
                raise ValueError("Unknown theme style")
            draft["theme_style"] = style
        self.draft = draft
        self.apply()

    def cancel_preview(self):
        self.committed, self._revision = self.app.services.snapshot_appearance()
        self.committed = normalize_appearance(self.committed)
        self.draft = None
        self.apply()

    async def commit_preview(self):
        if self.draft is None:
            return
        submitted = self.draft
        saved, revision = await self.app.services.commit_appearance(dict(submitted))
        self.receive_committed(saved, revision)
        # An edit made while disk I/O was running remains an uncommitted preview.
        if self.draft is submitted:
            self.draft = None
        self.apply()

    async def toggle_mode(self):
        previewing = self.draft is not None
        self.preview(mode="light" if self.tokens.is_dark else "dark")
        if not previewing:
            await self.commit_preview()

    def receive_committed(self, config, revision):
        if self._disposed or revision < self._revision:
            return
        self.committed = normalize_appearance(config)
        self._revision = revision
        settings = getattr(self.app, "settings", None)
        if settings is not None:
            settings.user_config.update(self.committed)
        self.apply()

    def subscribe(self, callback):
        if self._disposed:
            return lambda: None
        self._observers.append(callback)

        def unsubscribe():
            if callback in self._observers:
                self._observers.remove(callback)

        return unsubscribe

    async def motion_duration(self):
        if self.tokens.is_classic:
            return 0
        # Read on interaction, so changing the OS/browser preference also takes effect.
        try:
            features = await asyncio.wait_for(self._semantics.get_accessibility_features(), timeout=1)
            return 0 if features.disable_animations or features.reduce_motion else HOVER_DURATION
        except Exception:
            # A missing/disconnected platform service must never enable unwanted motion.
            return 0

    def dispose(self):
        self._disposed = True
        self._observers.clear()
        if self.page.on_platform_brightness_change == self._brightness_handler:
            self.page.on_platform_brightness_change = None
