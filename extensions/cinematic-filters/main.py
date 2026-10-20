"""Cinematic Filters - five film-style colour grades (matrix + tone, identical in preview and export)."""


def register(api):
    api.register_filter("cine-teal-orange", "Teal & Orange",
                        matrix=[[1.18, -0.05, -0.08], [-0.04, 1.02, 0.04], [-0.12, 0.10, 1.10]],
                        contrast=1.12, swatch="#e8955b")
    api.register_filter("cine-bleach", "Bleach Bypass",
                        matrix=[[0.62, 0.32, 0.06], [0.18, 0.74, 0.08], [0.18, 0.32, 0.50]],
                        contrast=1.32, brightness=-0.02, swatch="#9aa0a6")
    api.register_filter("cine-moody-blue", "Moody Blue",
                        matrix=[[0.82, 0.08, 0.04], [0.04, 0.92, 0.08], [0.08, 0.16, 1.12]],
                        contrast=1.10, brightness=-0.05, lift=0.03, swatch="#3d5a80")
    api.register_filter("cine-golden-hour", "Golden Hour",
                        matrix=[[1.16, 0.06, 0.0], [0.04, 1.04, 0.0], [-0.04, 0.0, 0.80]],
                        contrast=1.04, brightness=0.04, swatch="#f4a259")
    api.register_filter("cine-matte", "Matte Film",
                        matrix=[[0.92, 0.06, 0.02], [0.04, 0.92, 0.04], [0.02, 0.08, 0.90]],
                        contrast=0.86, lift=0.10, swatch="#b8a99a")
