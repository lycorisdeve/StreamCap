import os
import threading
import weakref

from ...utils.logger import logger
from .config_manager import ConfigManager


class LanguageManager:
    """
    Manages language settings and loads internationalization (i18n) configurations.
    """

    def __init__(self, app):
        self._initialize_observer_registry()
        self.language = {}
        self.app = app
        self.services = getattr(app, "services", None) if app is not None else None
        self.run_path = app.run_path if app is not None else None
        self.load()

    @classmethod
    def create_headless(cls, services) -> "LanguageManager":
        instance = cls.__new__(cls)
        instance._initialize_observer_registry()
        instance.language = {}
        instance.app = None
        instance.services = services
        instance.run_path = services.run_path
        instance.load()
        return instance

    def _initialize_observer_registry(self) -> None:
        self._observers: list[weakref.ReferenceType] = []
        self._observers_lock = threading.RLock()

    def _resolve_language_code(self) -> str:
        services = self.services
        if services is not None and hasattr(services, "settings_config"):
            sc = services.settings_config
            if sc is not None and hasattr(sc, "language_code"):
                return sc.language_code
        app = self.app
        if app is not None and hasattr(app, "settings"):
            settings = app.settings
            if settings is not None and hasattr(settings, "language_code"):
                return settings.language_code
        return "zh_CN"

    def load(self):
        """
        Initialize the LanguageManager with settings and load the language configuration.
        """
        run_path = self.run_path or (self.app.run_path if self.app is not None else None) or ""
        config_manager = ConfigManager(run_path)
        language_code = self._resolve_language_code() or "zh_CN"
        logger.info(f"Language Code: {language_code}")
        i18n_filename = f"{language_code}.json"
        i18n_file_path = os.path.join(run_path, "locales", i18n_filename)
        self.language = config_manager.load_i18n_config(i18n_file_path)
        return self.language

    def add_observer(self, observer):
        """Add an observer that will be notified when the language changes."""
        observer_ref = weakref.ref(observer)
        with self._observers_lock:
            alive_refs = []
            already_registered = False
            for existing_ref in self._observers:
                existing = existing_ref()
                if existing is None:
                    continue
                alive_refs.append(existing_ref)
                if existing is observer:
                    already_registered = True

            self._observers = alive_refs
            if not already_registered:
                self._observers.append(observer_ref)

    def remove_observer(self, observer):
        """Remove an observer."""
        with self._observers_lock:
            self._observers = [
                observer_ref
                for observer_ref in self._observers
                if (existing := observer_ref()) is not None and existing is not observer
            ]

    def notify_observers(self):
        """Notify all observers that the language has changed."""
        with self._observers_lock:
            observers = []
            alive_refs = []
            for observer_ref in self._observers:
                observer = observer_ref()
                if observer is None:
                    continue
                alive_refs.append(observer_ref)
                observers.append(observer)
            self._observers = alive_refs

        for observer in observers:
            if hasattr(observer, "page_name"):
                observer.load_language()
            else:
                observer.load()
