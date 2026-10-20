"""Text Animations - reveal-style animations (they work on any clip, but shine on titles).

reveal: which edge the clip wipes in from. steps="chars" reveals one letter at a time."""


def register(api):
    api.register_animation("tan-typewriter", "Typewriter", reveal="left", steps="chars")
    api.register_animation("tan-wipe", "Wipe Reveal", reveal="left")
    api.register_animation("tan-rise", "Rise Reveal", reveal="up", dy="(0.04*(1-E))")
    api.register_animation("tan-drop", "Drop Reveal", reveal="down", dy="(-0.04*(1-E))")
    api.register_animation("tan-glide", "Glide In", reveal="left", dx="(-0.06*(1-E))", fade=True)
