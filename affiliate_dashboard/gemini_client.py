"""Geteilter Gemini-Client-Helper -- ein einziger Ort fuer Modellwahl, Timeout und
Grounding-Quellen-Extraktion, genutzt von ``seo/research_agent.py`` UND
``content/article_generator.py``.

Wichtig: ``google-genai`` setzt standardmaessig KEIN Timeout (``HttpOptions().timeout``
ist ``None``) -- ohne explizites Limit haengt ein Netzwerk-Problem den aufrufenden
Hintergrund-Thread (und damit z. B. einen Recherche-Projekt-Lock) unbegrenzt fest, ohne
je eine Exception zu werfen (echter Vorfall: Live-Server hing 30+ Minuten fest, Lock
blieb belegt, siehe Memory zum SEO-Rechercheagent). Deshalb IMMER ueber diesen Helper
aufrufen, nie ``genai.Client()`` direkt instanziieren.
"""

from __future__ import annotations

import json

from google import genai
from google.genai import types as genai_types

MODEL = "gemini-pro-latest"  # rollierender Alias -- bewusst keine feste Versionsnummer
DEFAULT_TIMEOUT_MS = 180_000


def extract_sources(response) -> list[dict]:
    """Grounding-Quellen aus einer Gemini-Antwort extrahieren (leer, wenn das Modell
    das Search-Tool fuer diese Antwort nicht genutzt hat oder gar nicht aktiviert war)."""
    sources = []
    try:
        grounding = response.candidates[0].grounding_metadata
        for chunk in (grounding.grounding_chunks or []) if grounding else []:
            if chunk.web:
                sources.append({"title": chunk.web.title, "uri": chunk.web.uri,
                                 "domain": chunk.web.domain})
    except (AttributeError, IndexError):
        pass
    return sources


def generate(contents, system_instruction: str, api_key: str, *,
             max_output_tokens: int = 16000, search: bool = False,
             response_schema: dict | None = None,
             timeout_ms: int = DEFAULT_TIMEOUT_MS):
    """Ein ``generate_content()``-Call.

    ``search=True`` aktiviert das Google-Search-Grounding-Tool -- bewusste, auf
    Wettbewerbs-/Marktkontext begrenzte Ausnahme von der sonstigen "kein Tool-Use
    fuers Modell"-Architektur (Wettbewerber lassen sich nicht vorab deterministisch
    enumerieren, im Gegensatz zu eigenen GSC/GA4/SE-Ranking-Zahlen).

    ``response_schema`` aktiviert strukturierten JSON-Output -- fuer Faelle, in denen
    mehrere Felder maschinell weiterverarbeitet werden muessen (z. B. Artikel-Titel
    getrennt vom Body, SEO-Meta-Description separat), statt eine Freitext-Antwort zu
    parsen.

    Gibt ``(text, sources)`` zurueck, oder bei gesetztem ``response_schema``
    ``(geparstes_dict, sources)``. ``sources`` ist leer ohne ``search=True``.
    """
    client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=timeout_ms))
    config_kwargs: dict = {
        "system_instruction": system_instruction,
        "max_output_tokens": max_output_tokens,
    }
    if search:
        config_kwargs["tools"] = [genai_types.Tool(google_search=genai_types.GoogleSearch())]
    if response_schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = response_schema

    response = client.models.generate_content(
        model=MODEL, contents=contents,
        config=genai_types.GenerateContentConfig(**config_kwargs),
    )
    sources = extract_sources(response)
    if response_schema is not None:
        return json.loads(response.text), sources
    return response.text, sources
