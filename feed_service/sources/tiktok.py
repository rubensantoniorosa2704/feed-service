"""Source do TikTok via yt-dlp."""
import logging
from typing import Any

from yt_dlp import YoutubeDL

from ..clock import unix_to_iso, utc_now_iso

logger = logging.getLogger(__name__)

# Preferência de thumbnail: originCover é a capa escolhida pelo criador;
# cover é a capa gerada pelo TikTok; dynamicCover é um WebP animado (fallback).
_THUMBNAIL_PREFERENCE = ("originCover", "cover", "dynamicCover")


class TikTokSource:
    def __init__(self):
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "ignoreerrors": True,
            # extract_flat traz id, uploader, timestamp e thumbnails sem baixar
            # a página de cada vídeo — muito mais rápido.
            "extract_flat": True,
        }

    def fetch_recent_videos(self, channel_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Últimos `limit` vídeos do canal, normalizados para o formato do journal."""
        url = f"tiktokuser:{channel_id}"
        opts = {**self.ydl_opts, "playlistend": limit}

        try:
            with YoutubeDL(opts) as ydl:
                logger.debug(f"Fetching {limit} videos from {channel_id}")
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error(f"yt-dlp failed for {channel_id}: {e}")
            raise RuntimeError(f"TikTok extraction failed: {e}") from e

        if not info:
            raise RuntimeError("TikTok returned empty response")

        entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
        if not entries:
            logger.warning(f"No valid entries found for {channel_id}")
            return []

        videos = [self._normalize(e) for e in entries]
        logger.info(f"Fetched {len(videos)} videos from {channel_id}")
        return videos

    def _normalize(self, entry: dict[str, Any]) -> dict[str, Any]:
        video_id = entry["id"]
        uploader = entry.get("uploader", "unknown")

        return {
            "id": video_id,
            "title": entry.get("title") or entry.get("description") or "",
            "url": f"https://www.tiktok.com/@{uploader}/video/{video_id}",
            "thumbnail": _pick_thumbnail(entry.get("thumbnails") or []),
            "published_at": _timestamp_to_iso(entry.get("timestamp"), video_id),
        }


def _pick_thumbnail(thumbnails: list[dict[str, Any]]) -> str | None:
    by_id = {t.get("id"): t.get("url") for t in thumbnails}
    for preferred in _THUMBNAIL_PREFERENCE:
        if by_id.get(preferred):
            return by_id[preferred]
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
