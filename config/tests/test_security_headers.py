"""Une seule source pour HSTS et nosniff : nginx (audit 2026-10-18, M12).

En live, `poker-api` renvoyait HSTS deux fois — nginx (`max-age=63072000`) et la
SecurityMiddleware de Django (`max-age=31536000; preload`). Deux valeurs
contradictoires : un navigateur n'en retient qu'une, et laquelle n'est pas
spécifiée. nginx couvre aussi /static/, /media/ et ses propres pages d'erreur,
que Django ne voit jamais.
"""
import importlib
import re
from pathlib import Path

VHOST = Path(__file__).resolve().parents[2] / "deploy" / "nginx" / "poker-api.conf"


def test_nginx_sends_one_hsts_value_everywhere():
    conf = VHOST.read_text(encoding="utf-8")
    values = set(re.findall(r'add_header Strict-Transport-Security "([^"]+)"', conf))
    # Répété dans /media/ (nginx n'hérite pas des add_header), mais une seule valeur.
    assert values == {"max-age=63072000; includeSubDomains"}


def test_django_does_not_emit_them_in_production():
    prod = importlib.import_module("config.settings.prod")

    assert prod.SECURE_HSTS_SECONDS == 0
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is False
