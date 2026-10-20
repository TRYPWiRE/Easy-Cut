"""Retro & Script Fonts - bundled fonts (SIL Open Font License, see the licenses folder)."""

FONTS = [
    ('fnt-press-start', 'Press Start 2P', 'fonts/PressStart2P-Regular.ttf'),
    ('fnt-pacifico', 'Pacifico', 'fonts/Pacifico-Regular.ttf'),
    ('fnt-lobster', 'Lobster', 'fonts/Lobster-Regular.ttf'),
    ('fnt-audiowide', 'Audiowide', 'fonts/Audiowide-Regular.ttf'),
    ('fnt-orbitron', 'Orbitron', 'fonts/Orbitron[wght].ttf'),
]


def register(api):
    for fid, name, file in FONTS:
        api.register_font(fid, name, file)
