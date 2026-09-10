"""Renderizador de feed Atom.

Os elementos são criados com nomes qualificados ({uri}tag) e quem emite as
declarações xmlns é o próprio ElementTree, na serialização. Setar xmlns="..."
na mão como atributo, junto com register_namespace, gera declaração duplicada
e XML inválido.
"""
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from .clock import utc_now_iso

ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"

ET.register_namespace("", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)


def _atom(tag: str) -> str:
    return f"{{{ATOM_NS}}}{tag}"


def _media(tag: str) -> str:
    return f"{{{MEDIA_NS}}}{tag}"


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, _atom(tag), {k: v for k, v in attrs.items()})
    if text is not None:
        el.text = text
    return el


def render_atom_feed(
    profile_name: str,
    entries: list[dict[str, Any]],
    base_url: str = "http://localhost:8080",
) -> str:
    feed_url = f"{base_url}/feed/{quote(profile_name)}.xml"
    profile_url = f"https://www.tiktok.com/@{profile_name}"

    feed = ET.Element(_atom("feed"))

    _sub(feed, "title", profile_name)
    _sub(feed, "id", f"tiktok:user:{profile_name}")
    _sub(feed, "link", rel="self", href=feed_url)
    _sub(feed, "link", rel="alternate", href=profile_url)

    author = _sub(feed, "author")
    _sub(author, "name", profile_name)
    _sub(author, "uri", profile_url)

    # <updated> do feed: a entry mais recente, ou agora se o journal está vazio.
    if entries:
        _sub(feed, "updated", max(e["published_at"] for e in entries))
    else:
        _sub(feed, "updated", utc_now_iso())

    _sub(feed, "generator", "feed-service", uri=base_url)

    for entry_data in entries:
        entry = _sub(feed, "entry")

        _sub(entry, "id", f"tiktok:video:{entry_data['video_id']}")
        _sub(entry, "title", entry_data.get("title") or "Untitled")
        _sub(entry, "published", entry_data["published_at"])
        # <updated> = quando o serviço viu o vídeo; para vídeos que já existiam
        # antes do primeiro fetch fica depois de <published>. O leitor usa
        # <published> para ordenar, então isso é inofensivo.
        _sub(entry, "updated", entry_data["first_seen_at"])
        _sub(entry, "link", rel="alternate", href=entry_data["url"])
        _sub(entry, "summary", entry_data.get("title") or "")

        if entry_data.get("thumbnail"):
            media_group = ET.SubElement(entry, _media("group"))
            ET.SubElement(
                media_group,
                _media("thumbnail"),
                {"url": entry_data["thumbnail"]},
            )

    ET.indent(feed, space="  ")
    body = ET.tostring(feed, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}'
