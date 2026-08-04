from pathlib import Path


NGINX_CONFIG = Path(__file__).parents[2] / "apps" / "web" / "nginx.conf"


def test_spa_entry_is_not_cached_but_hashed_assets_are_immutable() -> None:
    config = NGINX_CONFIG.read_text(encoding="utf-8")

    assert "location = /index.html" in config
    assert 'Cache-Control "no-store, no-cache, must-revalidate"' in config
    assert "location /assets/" in config
    assert 'Cache-Control "public, max-age=31536000, immutable"' in config
