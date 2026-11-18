import os
import sys
from collections.abc import Callable, Mapping, Sequence

import httpx

from .models import Alert


# env and post are injected so tests can check Slack is called only when configured.
def notify(
    alerts: Sequence[Alert],
    env: Mapping[str, str] = os.environ,
    post: Callable[..., object] = httpx.post,
) -> None:
    for alert in alerts:
        print(alert, file=sys.stderr)
    webhook = env.get("SLACK_WEBHOOK_URL")
    if webhook and alerts:
        post(webhook, json={"text": "\n".join(map(str, alerts))}, timeout=10)
