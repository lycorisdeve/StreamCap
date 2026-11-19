"""A static vector backdrop; regenerated only for size or theme changes."""

import flet as ft


def background_svg(width, height, tokens):
    color = tokens.primary
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="0.65"/>' for y in range(14, height, 28) for x in range(14, width, 28))
    waves = "".join(
        f'<path d="M {-width * 0.1:.1f} {height * 1.02 + i * 3:.1f} '
        f"C {width * 0.28:.1f} {height * 1.08 - i * 2:.1f}, "
        f"{width * 0.45:.1f} {height * 0.76 + i * 3:.1f}, {width * 0.64:.1f} {height * 0.91 + i:.1f} "
        f'S {width * 0.86:.1f} {height * 0.77 + i * 4:.1f}, {width * 1.08:.1f} {height * 0.73 + i * 5:.1f}"/>'
        for i in range(16)
    )
    opacity = 0.08 if tokens.is_dark else 0.13
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <defs>
        <radialGradient id="halo" cx="88%" cy="4%" r="70%">
          <stop offset="0" stop-color="{color}" stop-opacity="{opacity}"/>
          <stop offset="1" stop-color="{color}" stop-opacity="0"/>
        </radialGradient>
        <radialGradient id="lower" cx="0%" cy="100%" r="65%">
          <stop offset="0" stop-color="{color}" stop-opacity="{opacity * 0.7}"/>
          <stop offset="1" stop-color="{color}" stop-opacity="0"/>
        </radialGradient>
        <linearGradient id="wave"><stop offset="0" stop-color="{color}" stop-opacity="0.01"/>
          <stop offset="1" stop-color="{color}" stop-opacity="0.15"/></linearGradient>
      </defs>
      <rect width="{width}" height="{height}" fill="url(#halo)"/>
      <rect width="{width}" height="{height}" fill="url(#lower)"/>
      <g fill="{color}" fill-opacity="0.065">{dots}</g>
      <g fill="none" stroke="url(#wave)" stroke-width="1">{waves}</g>
    </svg>'''.encode()


class AmbientBackground(ft.Container):
    def __init__(self, tokens):
        self.tokens = tokens
        self._size = (0, 0)
        self.art = ft.Image(src=background_svg(1, 1, tokens), fit=ft.BoxFit.FILL, exclude_from_semantics=True)
        super().__init__(
            content=self.art,
            ignore_interactions=True,
            on_size_change=self.resize_art,
            size_change_interval=150,
        )

    def set_theme(self, tokens):
        if tokens == self.tokens:
            return
        self.tokens = tokens
        self.render_art()

    def render_art(self):
        width, height = self._size
        if width > 0 and height > 0:
            self.art.src = background_svg(width, height, self.tokens)

    def resize_art(self, event):
        size = (round(event.width), round(event.height))
        if size != self._size and min(size) > 0:
            self._size = size
            self.render_art()
            self.update()
