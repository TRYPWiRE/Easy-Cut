"""Essential Transitions. Expressions use E (eased 0..1) - see easycut/animations.py."""


def register(api):
    api.register_transition("ess-dip-white", "Dip to White", alpha="half", veil="#ffffff")
    api.register_transition("ess-zoom-in", "Zoom In", scale="(0.25+0.75*E)", alpha="fade")
    api.register_transition("ess-zoom-out", "Zoom Out", scale="(1.8-0.8*E)", alpha="fade")
    api.register_transition("ess-slide-up", "Slide Up", dy="(1-E)", alpha="none")
    api.register_transition("ess-slide-down", "Slide Down", dy="(-(1-E))", alpha="none")
