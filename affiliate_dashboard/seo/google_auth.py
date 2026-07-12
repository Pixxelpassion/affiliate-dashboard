"""Google-OAuth fuer Search Console + GA4 (einmaliger lokaler Login, danach Auto-Refresh).

Ablauf:
    python -m affiliate_dashboard.seo.google_auth   # einmalig: oeffnet Browser, Consent,
                                                     # schreibt den Token nach data/google_token.json
Danach laedt jeder Lauf (gsc_client.py/ga4_client.py) den Token ueber get_credentials()
und erneuert ihn bei Bedarf automatisch -- kein manueller Login mehr noetig, solange der
refresh_token gueltig bleibt. Alles bleibt lokal (kein Server/Rechnertrennung noetig).
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from ..config import BASE_DIR, Config

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
]


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else (BASE_DIR / p)


def get_credentials(cfg: Config) -> Credentials:
    """Geladene/erneuerte Google-Credentials fuer GSC + GA4 zurueckgeben.

    Erwartet einen vorherigen Lauf von ``python -m affiliate_dashboard.seo.google_auth``
    (Token existiert bereits unter ``seo.google.token_path``).
    """
    google_cfg = cfg.get("seo", {}).get("google", {})
    token_path = _resolve(google_cfg.get("token_path", "data/google_token.json"))
    if not token_path.exists():
        raise RuntimeError(
            f"Kein Google-Token gefunden ({token_path}). Einmalig ausfuehren: "
            "python -m affiliate_dashboard.seo.google_auth"
        )

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def run_local_login(cfg: Config) -> None:
    """Einmaliger lokaler OAuth-Consent-Flow; schreibt den Token auf die Platte."""
    google_cfg = cfg.get("seo", {}).get("google", {})
    client_secret_path = _resolve(google_cfg.get("client_secret_path", "seo_client_secret.json"))
    token_path = _resolve(google_cfg.get("token_path", "data/google_token.json"))
    if not client_secret_path.exists():
        raise RuntimeError(
            f"OAuth-Client-Datei fehlt: {client_secret_path}. In der Google Cloud Console "
            "einen OAuth-Client vom Typ 'Desktop-App' anlegen und die JSON-Datei dort ablegen."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Login erfolgreich. Token gespeichert unter: {token_path}")


if __name__ == "__main__":
    run_local_login(Config.load())
