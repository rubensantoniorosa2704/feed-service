"""Ponto de entrada do feed-service."""
import logging
import sys

from waitress import serve

from .config import load_config
from .db import Journal
from .web import create_app
from .worker import FeedWorker


def setup_logging(debug: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("playwright").setLevel(logging.WARNING)


def _parse_args(argv: list[str]) -> tuple[bool, str]:
    debug = "--debug" in argv
    config_path = "config.toml"
    if "--config" in argv:
        try:
            config_path = argv[argv.index("--config") + 1]
        except (IndexError, ValueError):
            print("Usage: python -m feed_service [--debug] [--config CONFIG.toml]")
            sys.exit(1)
    return debug, config_path


def main():
    debug, config_path = _parse_args(sys.argv)
    setup_logging(debug)
    logger = logging.getLogger(__name__)

    journal: Journal | None = None
    worker: FeedWorker | None = None
    try:
        logger.info(f"Loading config from {config_path}")
        config = load_config(config_path)

        db_path = config["storage"]["db_path"]
        logger.info(f"Initializing journal at {db_path}")
        journal = Journal(db_path)

        worker = FeedWorker(config, journal)
        app = create_app(config, journal, worker)
        worker.start()

        host = config["server"]["host"]
        port = config["server"]["port"]

        logger.info(f"Starting feed-service on {host}:{port}")
        logger.info(f"Profiles configured: {[p['name'] for p in config['profiles']]}")

        if debug:
            logger.info("Debug mode: using Flask dev server")
            app.run(host=host, port=port, debug=True, use_reloader=False)
        else:
            logger.info("Production mode: using Waitress WSGI server")
            serve(app, host=host, port=port)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)
    finally:
        try:
            if worker:
                worker.stop()
            if journal:
                journal.close()
        except Exception:
            logger.exception("Error during cleanup")


if __name__ == "__main__":
    main()
