"""Deploy ordering that only production exercises, checked on the files (billing_server#74)."""
import json
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEREDOC = "cat > /tmp/ssm-params.json <<'EOF'\n"


def _ssm_commands():
    text = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.index(HEREDOC) + len(HEREDOC)
    end = text.index("\n          EOF", start)
    return json.loads(textwrap.dedent(text[start:end]))["commands"]


class DeployOrderTests(unittest.TestCase):
    def test_checkout_is_updated_after_env_fetch_restart(self):
        # The app units Require env-fetch: its restart restarts them at once. If the
        # checkout were already on the new code, they would run it with the old venv.
        commands = _ssm_commands()

        def position(needle):
            return next(i for i, c in enumerate(commands) if needle in c)

        env_fetch = position("systemctl restart poker-env-fetch")
        checkout = position("git reset --hard")
        deploy = position("deploy/deploy.sh")
        self.assertLess(env_fetch, checkout)
        self.assertLess(checkout, deploy)
        for unit in ("asgi", "celery", "celery-beat"):
            text = (ROOT / f"deploy/systemd/poker-{unit}.service").read_text(encoding="utf-8")
            self.assertIn("Requires=poker-env-fetch.service", text)
