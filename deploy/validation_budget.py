"""Conservative invocation budgets, not performance estimates or test authority."""
COMMAND_SECONDS = 900
CONTROL_SECONDS = 30
STARTUP_SECONDS = 900  # docker run may pull/extract on a fresh daemon
INTERRUPT_SECONDS = 10
KILL_WAIT_SECONDS = 5
CLEANUP_SECONDS = 120  # ownership inspect + port check + remove, with margin
READINESS_SECONDS = 2


def budget(profiles, *, inventory_only=False):
    browser = sum(profile in ('browser', 'siwc', 'clock') for profile in profiles)
    fixture = not inventory_only and any(profile != 'probes' for profile in profiles)
    stages = (1 if inventory_only else len(profiles) + ('backend' in profiles)
              + bool(browser) + browser)
    # Three Git calls; cold run plus port/inspect/port;40 readiness calls + sleeps.
    controls = 3 * CONTROL_SECONDS + (STARTUP_SECONDS + 3 * CONTROL_SECONDS
                + 40 * (READINESS_SECONDS + 0.5) if fixture else 0)
    execution = int(stages * COMMAND_SECONDS + controls)
    cleanup = CLEANUP_SECONDS if fixture else 0
    return {'command_seconds': COMMAND_SECONDS, 'control_seconds': CONTROL_SECONDS,
            'startup_seconds': STARTUP_SECONDS if fixture else 0,
            'execution_seconds': execution,
            'cleanup_grace_seconds': cleanup + INTERRUPT_SECONDS + KILL_WAIT_SECONDS,
            'recommended_outer_seconds': execution + cleanup + INTERRUPT_SECONDS + KILL_WAIT_SECONDS + 30,
            'basis': 'conservative stage ceilings, not expected runtime; no lock wait included'}
