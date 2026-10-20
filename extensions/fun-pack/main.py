"""Fun Pack - bouncy animations."""


def register(api):
    api.register_animation("fun-elastic", "Elastic", scale="max(0.02,1-exp(-6*P)*cos(12*P))")
    api.register_animation("fun-wobble", "Wobble", rot="(22*(1-P)*sin(P*PI*6))", scale="(0.6+0.4*E)",
                           fade=True)
    api.register_animation("fun-bounce", "Bounce Drop", dy="(-0.6*abs(cos(P*PI*2.5))*pow(1-P,2))")
    api.register_animation("fun-heartbeat", "Heartbeat", scale="(E*(1+0.25*abs(sin(P*PI*3))*(1-P)))")
    api.register_animation("fun-whirl", "Whirl", rot="(540*(1-E))", scale="max(0.02,E)", fade=True)
