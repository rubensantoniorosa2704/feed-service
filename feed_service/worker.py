"""Worker que raspa perfis em background."""
import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone

from .config import resolve_profile_interval
from .db import Journal
from .sources.tiktok import TikTokSource

logger = logging.getLogger(__name__)

# Cadência do loop de verificação. Menor não faz diferença: as raspagens
# são agendadas em minutos e o jitter absorve pequenos desvios.
_TICK_SECONDS = 30
_ERROR_BACKOFF_SECONDS = 60

# Jitter da primeira execução, para espalhar os perfis no arranque do processo.
_INITIAL_JITTER_SECONDS = 60


class FeedWorker:
    def __init__(self, config: dict, journal: Journal):
        self.config = config
        self.journal = journal
        self.tiktok = TikTokSource()
        self.running = False
        self._thread: threading.Thread | None = None
        self._profile_schedules: dict[str, datetime] = {}

    def start(self):
        if self.running:
            logger.warning("Worker already running")
            return
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Feed worker started")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Feed worker stopped")

    def force_fetch_profile(self, profile_name: str) -> bool:
        """Executa raspagem imediata; retorna False se o perfil não existe."""
        for profile in self.config["profiles"]:
            if profile["name"] == profile_name:
                logger.info(f"Force fetching {profile_name}")
                self._fetch_profile(profile)
                self._reschedule_profile(profile)
                return True
        logger.warning(f"Profile {profile_name} not found for force fetch")
        return False

    def _run_loop(self):
        logger.info("Worker loop started")
        self._schedule_all_profiles()
        while self.running:
            try:
                self._process_due_profiles()
                time.sleep(_TICK_SECONDS)
            except Exception:
                logger.exception("Unexpected error in worker loop")
                time.sleep(_ERROR_BACKOFF_SECONDS)

    def _schedule_all_profiles(self):
        now = datetime.now(timezone.utc)
        for profile in self.config["profiles"]:
            name = profile["name"]
            next_run = now + timedelta(seconds=random.uniform(0, _INITIAL_JITTER_SECONDS))
            self._profile_schedules[name] = next_run
            logger.info(f"Scheduled {name} for {next_run.strftime('%H:%M:%S')}")

    def _process_due_profiles(self):
        now = datetime.now(timezone.utc)
        for profile in self.config["profiles"]:
            name = profile["name"]
            next_run = self._profile_schedules.get(name)
            if not next_run:
                logger.warning(f"{name} not in schedule! This should not happen.")
                continue
            if now < next_run:
                time_until = (next_run - now).total_seconds()
                logger.debug(f"{name} not due yet ({time_until:.0f}s remaining)")
                continue
            logger.info(f"{name} is due, executing fetch")
            self._fetch_profile(profile)
            self._reschedule_profile(profile)

    def _fetch_profile(self, profile: dict):
        name = profile["name"]
        channel_id = profile["channel_id"]
        limit = self.config["defaults"]["fetch_limit"]

        logger.info(f"Fetching {name} ({channel_id})")
        try:
            videos = self.tiktok.fetch_recent_videos(channel_id, limit)
            added = self.journal.add_entries(name, videos)
            self.journal.update_profile_state(name, success=True)
            if added > 0:
                logger.info(f"{name}: {added} new videos added to journal")
            else:
                logger.debug(f"{name}: no new videos")
        except Exception as e:
            logger.error(f"Failed to fetch {name}: {e}")
            self.journal.update_profile_state(name, success=False, error=str(e))

    def _reschedule_profile(self, profile: dict):
        name = profile["name"]
        defaults = self.config["defaults"]
        base = resolve_profile_interval(profile, defaults)

        # Backoff exponencial em cima do intervalo base, capado.
        # consecutive_failures é escrito pelo próprio _fetch_profile via
        # update_profile_state e resetado em qualquer sucesso.
        state = self.journal.get_profile_state(name)
        failures = state["consecutive_failures"] if state else 0
        if failures > 0:
            cap = defaults.get("max_backoff_minutes", 240)
            interval_min = min(base * (2 ** (failures - 1)), cap)
        else:
            interval_min = base

        jitter = random.uniform(0, defaults["jitter_seconds"])
        next_run = datetime.now(timezone.utc) + timedelta(
            minutes=interval_min, seconds=jitter
        )
        self._profile_schedules[name] = next_run

        when = f"{next_run.strftime('%H:%M:%S')} (+{interval_min}m{jitter:.0f}s)"
        if failures > 0:
            logger.info(f"{name} in backoff ({failures} failures), next fetch at {when}")
        else:
            logger.debug(f"Rescheduled {name} for {when}")
