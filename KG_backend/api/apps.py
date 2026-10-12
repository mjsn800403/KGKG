import os
import threading

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        # Warm the embedding model + index connection in the background so the
        # first assistant query is fast (cold model load is ~10-15s). Opt-in via
        # KG_WARMUP=1 (set in run_server.sh) so it never fires during migrations,
        # tests, or other management commands. Under the autoreloader only the
        # child process (RUN_MAIN=true) warms, not the watcher parent.
        if os.environ.get('KG_WARMUP') != '1':
            return
        if os.environ.get('RUN_MAIN') == 'false':
            return

        def _warm():
            try:
                from .rag import service
                service.warmup()
            except Exception:
                pass

        threading.Thread(target=_warm, name='rag-warmup', daemon=True).start()
