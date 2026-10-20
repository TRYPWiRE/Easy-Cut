"""Motion Pack - in/out animations. E = eased progress, P = linear progress (0 hidden -> 1 shown)."""


def register(api):
    api.register_animation("mot-spin", "Spin", scale="(0.3+0.7*E)", rot="(-360*(1-E))", fade=True)
    api.register_animation("mot-swing", "Swing", rot="(30*(1-P)*cos(P*PI*2.5))", fade=True)
    api.register_animation("mot-zoom-out", "Zoom Out", scale="(1.8-0.8*E)", fade=True)
    api.register_animation("mot-rise", "Rise", dy="(0.25*(1-E))", fade=True)
    api.register_animation("mot-sweep", "Sweep", dx="(-0.6*(1-E))", rot="(-18*(1-E))", fade=True)
