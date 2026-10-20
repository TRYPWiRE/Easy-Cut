"""Dynamic Transitions."""


def register(api):
    api.register_transition("dyn-spin", "Spin", scale="(0.15+0.85*E)", rot="(300*(1-E))", alpha="fade")
    api.register_transition("dyn-wipe-right", "Wipe Right", reveal="left", alpha="none")
    api.register_transition("dyn-wipe-down", "Wipe Down", reveal="down", alpha="none")
    api.register_transition("dyn-pop", "Pop", scale="max(0.02,E*(1+0.35*sin(PI*E)))", alpha="none")
    api.register_transition("dyn-swing", "Swing In", rot="(-28*(1-E))", dx="(0.45*(1-E))", alpha="fade")
