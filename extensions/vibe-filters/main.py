"""Vibe Filters - five punchy social-media looks."""


def register(api):
    api.register_filter("vibe-pastel", "Pastel Dream",
                        matrix=[[0.86, 0.10, 0.10], [0.08, 0.86, 0.10], [0.12, 0.10, 0.90]],
                        contrast=0.82, brightness=0.06, lift=0.12, swatch="#f7c6d9")
    api.register_filter("vibe-neon", "Neon Nights",
                        matrix=[[1.25, -0.15, 0.10], [-0.10, 1.05, 0.05], [0.15, -0.10, 1.35]],
                        contrast=1.25, brightness=-0.04, swatch="#c04cfd")
    api.register_filter("vibe-cyber-pink", "Cyber Pink",
                        matrix=[[1.20, 0.05, 0.15], [-0.05, 0.85, 0.10], [0.10, 0.0, 1.15]],
                        contrast=1.12, swatch="#ff4fa3")
    api.register_filter("vibe-retro80", "Retro 80s",
                        matrix=[[1.12, 0.10, 0.02], [0.02, 0.92, 0.10], [0.10, 0.02, 1.05]],
                        contrast=1.06, lift=0.06, swatch="#ff7e5f")
    api.register_filter("vibe-arctic", "Arctic",
                        matrix=[[0.78, 0.12, 0.10], [0.06, 0.96, 0.10], [0.04, 0.12, 1.20]],
                        contrast=1.06, brightness=0.05, swatch="#9bd4f5")
