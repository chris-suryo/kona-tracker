"""One router per domain, each built by a `make_<domain>_router(deps)`
factory from the `AppDeps` that `create_app()` assembled. No prefixes: every
path is written out in full in its decorator, so a grep for "/robot/stop"
finds the handler.
"""
