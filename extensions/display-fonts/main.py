"""Display Fonts - bundled fonts (SIL Open Font License, see the licenses folder)."""

FONTS = [
    ('fnt-bungee', 'Bungee', 'fonts/Bungee-Regular.ttf'),
    ('fnt-monoton', 'Monoton', 'fonts/Monoton-Regular.ttf'),
    ('fnt-bangers', 'Bangers', 'fonts/Bangers-Regular.ttf'),
    ('fnt-creepster', 'Creepster', 'fonts/Creepster-Regular.ttf'),
    ('fnt-righteous', 'Righteous', 'fonts/Righteous-Regular.ttf'),
]


def register(api):
    for fid, name, file in FONTS:
        api.register_font(fid, name, file)
