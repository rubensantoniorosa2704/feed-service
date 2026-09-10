"""Source do TikTok via Playwright (Chromium headless).

Estratégia:
1. Abre a página do perfil (@username) num Chromium headless.
2. Extrai o `secUid` do JSON embutido `__UNIVERSAL_DATA_FOR_REHYDRATION__`.
3. Chama a API `/api/post/item_list/` pela mesma sessão do navegador, então
   os cookies e o TLS fingerprint do Chromium acompanham a chamada.
4. Fecha o navegador.

Um Chromium por fetch. Zero estado persistente entre execuções — evita
memory leak e processo zumbi em execução 24/7. Custa alguns segundos a mais
por fetch, o que é irrelevante para intervalos de 30+ minutos.
"""
import json
import logging
from typing import Any

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from ..clock import unix_to_iso, utc_now_iso

logger = logging.getLogger(__name__)

# Preferência de thumbnail: originCover é a capa escolhida pelo criador;
# cover é a capa gerada pelo TikTok; dynamicCover é um WebP animado (fallback).
_THUMBNAIL_PREFERENCE = ("originCover", "cover", "dynamicCover")

# Timeouts em milissegundos. Página do TikTok é pesada; 30s é folga suficiente.
_PAGE_LOAD_TIMEOUT_MS = 30_000
_SCRIPT_WAIT_TIMEOUT_MS = 15_000
_API_TIMEOUT_MS = 15_000

# Máximo aceito pela API item_list por página. Se precisar de mais, teria que
# paginar com o cursor; por ora, `limit` sempre cabe numa única chamada.
_API_MAX_COUNT = 35


class TikTokSource:
    """Extrai vídeos recentes de um perfil do TikTok via navegador headless."""

    def fetch_recent_videos(
        self, username: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Últimos `limit` vídeos do perfil, normalizados para o formato do journal."""
        username = username.lstrip("@")
        logger.debug(f"Fetching {limit} videos from @{username}")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        locale="pt-BR",
                    )
                    page = context.new_page()
                    sec_uid = self._get_sec_uid(page, username)
                    items = self._get_video_list(page, sec_uid, limit)
                finally:
                    # `browser.close()` já fecha os contextos filhos.
                    browser.close()
        except PlaywrightTimeout as e:
            raise RuntimeError(
                f"TikTok extraction timeout for @{username}: {e}"
            ) from e
        except RuntimeError:
            # Erros já formatados nos métodos internos.
            raise
        except Exception as e:
            logger.error(f"Playwright failed for @{username}: {e}")
            raise RuntimeError(f"TikTok extraction failed: {e}") from e

        videos = [self._normalize(item, username) for item in items[:limit]]
        logger.info(f"Fetched {len(videos)} videos from @{username}")
        return videos

    def _get_sec_uid(self, page: Page, username: str) -> str:
        """Carrega a página do perfil e extrai o `secUid` do JSON embutido."""
        url = f"https://www.tiktok.com/@{username}"
        page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#__UNIVERSAL_DATA_FOR_REHYDRATION__",
            timeout=_SCRIPT_WAIT_TIMEOUT_MS,
        )

        raw = page.eval_on_selector(
            "#__UNIVERSAL_DATA_FOR_REHYDRATION__",
            "el => el.textContent",
        )
        if not raw:
            raise RuntimeError(
                f"Rehydration script is empty for @{username} "
                f"(possível bloqueio ou perfil inexistente)"
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Rehydration script has invalid JSON for @{username}: {e}"
            ) from e

        sec_uid = (
            data.get("__DEFAULT_SCOPE__", {})
            .get("webapp.user-detail", {})
            .get("userInfo", {})
            .get("user", {})
            .get("secUid")
        )
        if not sec_uid:
            raise RuntimeError(
                f"secUid not found in rehydration JSON for @{username}"
            )
        return sec_uid

    def _get_video_list(
        self, page: Page, sec_uid: str, limit: int
    ) -> list[dict[str, Any]]:
        """Chama a API `item_list` pela sessão do navegador (mesmos cookies)."""
        count = min(max(limit, 1), _API_MAX_COUNT)
        response = page.request.get(
            "https://www.tiktok.com/api/post/item_list/",
            params={
                "aid": "1988",
                "count": str(count),
                "cursor": "0",
                "device_platform": "web_pc",
                "secUid": sec_uid,
            },
            timeout=_API_TIMEOUT_MS,
        )
        if not response.ok:
            raise RuntimeError(
                f"item_list API returned HTTP {response.status}"
            )

        try:
            data = response.json()
        except Exception as e:
            raise RuntimeError(f"item_list API returned non-JSON: {e}") from e

        return data.get("itemList") or []

    def _normalize(self, item: dict[str, Any], username: str) -> dict[str, Any]:
        video_id = item.get("id")
        if not video_id:
            raise ValueError(f"Video item without id in itemList for @{username}")

        return {
            "id": video_id,
            "title": item.get("desc") or "",
            "url": f"https://www.tiktok.com/@{username}/video/{video_id}",
            "thumbnail": _pick_thumbnail(item.get("video") or {}),
            "published_at": _timestamp_to_iso(item.get("createTime"), video_id),
        }


def _pick_thumbnail(video: dict[str, Any]) -> str | None:
    for field in _THUMBNAIL_PREFERENCE:
        url = video.get(field)
        if url:
            return url
    return None


def _timestamp_to_iso(timestamp: Any, video_id: str) -> str:
    if timestamp is None:
        logger.warning(f"Video {video_id} has no timestamp")
        return utc_now_iso()
    try:
        return unix_to_iso(timestamp)
    except (TypeError, ValueError, OSError, OverflowError):
        logger.warning(f"Video {video_id} has invalid timestamp: {timestamp!r}")
        return utc_now_iso()
