"""API HTTP do feed service."""
import hashlib
import logging
from datetime import datetime, timezone

from flask import Flask, Response, abort, request

from .atom import render_atom_feed
from .clock import iso_to_datetime, utc_now_iso
from .db import Journal

logger = logging.getLogger(__name__)


def create_app(config: dict, journal: Journal, worker=None) -> Flask:
    app = Flask(__name__)

    @app.route("/healthz")
    def healthz():
        try:
            journal.get_all_profile_states()
            return {"status": "ok", "timestamp": utc_now_iso()}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "error", "error": str(e)}, 500

    @app.route("/status")
    def status():
        try:
            return {"profiles": journal.get_all_profile_states()}
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {"error": str(e)}, 500

    @app.route("/feed/<profile_name>.xml")
    def feed(profile_name: str):
        if not any(p["name"] == profile_name for p in config["profiles"]):
            abort(404)

        try:
            max_entries = config["defaults"]["feed_max_entries"]
            entries = journal.get_feed_entries(profile_name, max_entries)

            base_url = request.url_root.rstrip("/")
            atom_xml = render_atom_feed(profile_name, entries, base_url)

            etag = hashlib.sha256(atom_xml.encode()).hexdigest()[:16]

            # Last-Modified é só otimização de cache: um published_at fora do
            # formato canônico cai em "agora" em vez de derrubar o feed.
            last_modified = datetime.now(timezone.utc)
            if entries:
                try:
                    last_modified = iso_to_datetime(
                        max(e["published_at"] for e in entries)
                    )
                except (TypeError, ValueError):
                    logger.warning(
                        f"Could not parse published_at for feed {profile_name}"
                    )

            if request.headers.get("If-None-Match") == f'"{etag}"':
                return Response(status=304)

            response = Response(
                atom_xml,
                mimetype="application/atom+xml; charset=utf-8",
            )
            response.headers["ETag"] = f'"{etag}"'
            response.headers["Last-Modified"] = last_modified.strftime(
                "%a, %d %b %Y %H:%M:%S GMT"
            )
            response.headers["Cache-Control"] = "public, max-age=300"
            return response

        except Exception as e:
            logger.error(f"Feed generation failed for {profile_name}: {e}")
            return {"error": str(e)}, 500

    @app.route("/force/<profile_name>", methods=["POST"])
    def force_fetch(profile_name: str):
        """Dispara raspagem imediata de um perfil (uso de debug)."""
        if not worker:
            return {"error": "Worker not available"}, 503
        if worker.force_fetch_profile(profile_name):
            return {"message": f"Forced fetch of {profile_name}"}
        return {"error": f"Profile {profile_name} not found"}, 404

    return app
