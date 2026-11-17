"""TinyTune: reproductor de audio local para la bandeja del sistema."""

from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import queue
import random
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from enum import Enum
from io import BytesIO
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import BooleanVar, filedialog, ttk
from typing import Callable, Optional

import customtkinter as ctk
import mutagen
import pygame
import pystray
from PIL import Image, ImageDraw, ImageOps

APP_NAME = "TinyTune"
APP_VERSION = "3.1.0"
CREDITS_URL = "https://www.instagram.com/markbn115/?hl=es"

AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".ogg", ".wav", ".flac", ".opus",
    ".aiff", ".aif", ".mod", ".xm", ".it", ".s3m", ".mid", ".midi",
})

COLOR_BG = "#111214"
COLOR_SURFACE = "#191A1D"
COLOR_HOVER = "#26282C"
COLOR_ACCENT = "#1DB954"
COLOR_TEXT = "#F5F5F5"
COLOR_SUBTLE = "#9A9DA3"
COLOR_BORDER = "#2A2C30"

WIN_W = 372
WIN_H_COLLAPSED = 232
WIN_H_EXPANDED = 552
COVER_SIZE = (64, 64)

ICON_FONT = "Segoe MDL2 Assets"
ICON_PLAY = "\uE768"
ICON_PAUSE = "\uE769"
ICON_PREV = "\uE892"
ICON_NEXT = "\uE893"
ICON_VOLUME = "\uE767"
ICON_MUTE = "\uE74F"
ICON_FOLDER = "\uED25"
ICON_LIST = "\uE8FD"
ICON_SHUFFLE = "\uE8B1"
ICON_REPEAT_ALL = "\uE8EE"
ICON_REPEAT_ONE = "\uE8ED"
ICON_WEB = "\uE774"
ICON_SETTINGS = "\uE713"
ICON_CLOSE = "\uE711"

PLAY_MODES = ("seq", "loop", "one", "shuffle")


def _config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


CONFIG_DIR = _config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "tinytune.log"
COVER_CACHE_DIR = CONFIG_DIR / "covers"
LEGACY_CONFIG_FILE = Path.home() / ".tinytune" / "config.json"

_INSTANCE_MUTEX = f"Local\\{APP_NAME}.Instance"
_SHOW_EVENT = f"Local\\{APP_NAME}.Show"


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger(APP_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=256 * 1024, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        ))
        logger.addHandler(handler)
    except OSError:
        pass
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        stream.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(stream)
    return logger


logger = _setup_logging()


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _documents_folder() -> Path:
    if os.name == "nt":
        try:
            guid = _GUID(
                0xFDD39AD0, 0x238F, 0x46AF,
                (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
            )
            result = ctypes.c_wchar_p()
            shell32 = ctypes.windll.shell32
            shell32.SHGetKnownFolderPath.argtypes = [
                ctypes.POINTER(_GUID), ctypes.c_ulong, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_wchar_p),
            ]
            shell32.SHGetKnownFolderPath.restype = ctypes.c_long
            if shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(result)
            ) == 0 and result.value:
                try:
                    return Path(result.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(
                        ctypes.cast(result, ctypes.c_void_p)
                    )
        except Exception as exc:
            logger.debug("No se pudo resolver Documentos: %s", exc)
    return Path.home() / "Documents"


def default_music_folder() -> Path:
    folder = _documents_folder() / f"{APP_NAME} Music"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    except OSError:
        fallback = Path.home() / f"{APP_NAME} Music"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def resolve_music_folder(value: Optional[str]) -> Path:
    default = default_music_folder()
    if value:
        folder = Path(value)
        if folder.is_dir():
            return folder
    return default


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def acquire_instance_lock() -> tuple[Optional[int], bool]:
    if os.name != "nt":
        return None, False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, 0, _INSTANCE_MUTEX)
        if not handle:
            return None, False
        if kernel32.GetLastError() == 183:
            kernel32.CloseHandle(handle)
            return None, True
        return handle, False
    except Exception:
        return None, False


def signal_existing_instance() -> bool:
    if os.name != "nt":
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.OpenEventW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        event = kernel32.OpenEventW(0x0002, 0, _SHOW_EVENT)
        if not event:
            return False
        try:
            return bool(kernel32.SetEvent(event))
        finally:
            kernel32.CloseHandle(event)
    except Exception:
        return False


def create_show_event() -> Optional[int]:
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p,
        ]
        kernel32.CreateEventW.restype = ctypes.c_void_p
        return kernel32.CreateEventW(None, 0, 0, _SHOW_EVENT) or None
    except Exception:
        return None


def format_time(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "0:00"
    total = int(seconds)
    if total >= 3600:
        return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


def ellipsize(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _clean_text(value: object) -> str:
    return " ".join(str(value).split())


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _strip_track_number(title: str) -> str:
    text = title.strip()
    digits = 0
    while digits < len(text) and digits < 3 and text[digits].isdigit():
        digits += 1
    if 0 < digits < len(text):
        rest = text[digits:].lstrip()
        if rest[:1] in "-._)]":
            return rest[1:].strip() or text
    return text


def _as_float(value: object, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _as_int(value: object) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class Config:
    volume: float = 0.8
    muted: bool = False
    play_mode: str = "seq"
    window_x: Optional[int] = None
    window_y: Optional[int] = None
    playlist_open: bool = False
    music_folder: Optional[str] = None
    last_track: Optional[str] = None
    online_covers: bool = False

    @classmethod
    def load(cls) -> "Config":
        if CONFIG_FILE.is_file():
            config = cls._read(CONFIG_FILE)
            if config is not None:
                return config
            try:
                CONFIG_FILE.replace(CONFIG_FILE.with_suffix(".corrupt"))
            except OSError:
                pass
            return cls()
        if LEGACY_CONFIG_FILE.is_file():
            config = cls._read(LEGACY_CONFIG_FILE)
            if config is not None:
                return config
        return cls()

    @classmethod
    def _read(cls, path: Path) -> Optional["Config"]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            mode = str(data.get("play_mode", "seq"))
            return cls(
                volume=_as_float(data.get("volume"), 0.8, 0.0, 1.0),
                muted=bool(data.get("muted", False)),
                play_mode=mode if mode in PLAY_MODES or mode == "random" else "seq",
                window_x=_as_int(data.get("window_x")),
                window_y=_as_int(data.get("window_y")),
                playlist_open=bool(data.get("playlist_open", False)),
                music_folder=str(data["music_folder"]) if data.get("music_folder") else None,
                last_track=str(data["last_track"]) if data.get("last_track") else None,
                online_covers=bool(data.get("online_covers", False)),
            )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("Configuración no válida en %s: %s", path, exc)
            return None

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            temporary = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
            temporary.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(temporary, CONFIG_FILE)
        except OSError as exc:
            logger.error("No se pudo guardar la configuración: %s", exc)


@dataclass(slots=True)
class Track:
    path: Path
    title: str
    artist: str = ""
    album: str = ""
    duration: float = 0.0

    @property
    def display_name(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title

    @property
    def subtitle(self) -> str:
        return " · ".join(part for part in (self.artist, self.album) if part)


def _tag_value(tags: object, key: str) -> str:
    try:
        value = tags.get(key)  # type: ignore[union-attr]
    except Exception:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return _clean_text(value) if value is not None else ""


def read_metadata(path: Path) -> tuple[str, str, str, float]:
    title, artist, album, duration = path.stem, "", "", 0.0
    try:
        audio = mutagen.File(path, easy=True)
        if audio is None:
            return title, artist, album, duration
        info = getattr(audio, "info", None)
        if info is not None:
            duration = max(0.0, float(getattr(info, "length", 0.0) or 0.0))
        tags = getattr(audio, "tags", None)
        if tags:
            title = _tag_value(tags, "title") or title
            artist = _tag_value(tags, "artist")
            album = _tag_value(tags, "album")
    except Exception as exc:
        logger.debug("Metadatos no disponibles en %s: %s", path.name, exc)
    return title, artist, album, duration


def read_cover(path: Path, size: tuple[int, int]) -> Optional[Image.Image]:
    data: Optional[bytes] = None
    try:
        audio = mutagen.File(path)
        if audio is None:
            return None
        tags = getattr(audio, "tags", None)
        if tags is not None and hasattr(tags, "getall"):
            for picture in tags.getall("APIC"):
                if getattr(picture, "data", None):
                    data = picture.data
                    break
        if data is None:
            pictures = getattr(audio, "pictures", None)
            if pictures:
                data = pictures[0].data
        if data is None and tags is not None and "covr" in tags:
            covers = tags["covr"]
            if covers:
                data = bytes(covers[0])
        if data:
            with Image.open(BytesIO(data)) as source:
                return ImageOps.fit(
                    source.convert("RGB"), size, method=Image.Resampling.LANCZOS
                )
    except Exception as exc:
        logger.debug("Carátula no disponible en %s: %s", path.name, exc)
    return None


def rounded_cover(image: Image.Image, radius: int = 10) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=radius, fill=255
    )
    result = Image.new("RGBA", image.size, (0, 0, 0, 0))
    result.paste(image, (0, 0), mask)
    return result


def cover_cache_path(title: str, artist: str) -> Path:
    key = _normalize(f"{artist}|{title}").encode("utf-8")
    return COVER_CACHE_DIR / (hashlib.sha1(key).hexdigest() + ".img")


class OnlineCoverService:
    def __init__(
        self, enabled: bool, on_cover: Callable[[str, Image.Image], None]
    ) -> None:
        self.enabled = bool(enabled)
        self._on_cover = on_cover
        self._queue: queue.SimpleQueue[Optional[tuple[str, str, str]]] = (
            queue.SimpleQueue()
        )
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._last_request = 0.0
        if self.enabled:
            self._ensure_thread()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.enabled = bool(enabled)
        if enabled:
            self._ensure_thread()

    def request(self, track: Track) -> None:
        if not self.enabled or not track.title:
            return
        path = str(track.path)
        with self._lock:
            if path in self._pending:
                return
            self._pending.add(path)
        self._ensure_thread()
        self._queue.put((path, track.title, track.artist))

    def stop(self) -> None:
        with self._lock:
            self.enabled = False
        self._queue.put(None)

    @staticmethod
    def clear_cache() -> None:
        try:
            for entry in COVER_CACHE_DIR.iterdir():
                if entry.is_file():
                    entry.unlink(missing_ok=True)
        except OSError:
            pass

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, title, artist = item
            try:
                if self.enabled:
                    image = self._fetch(title, artist)
                    if image is not None and self.enabled:
                        self._on_cover(path, image)
            except Exception as exc:
                logger.debug("Carátula en línea no disponible: %s", exc)
            finally:
                with self._lock:
                    self._pending.discard(path)

    def _fetch(self, title: str, artist: str) -> Optional[Image.Image]:
        cache = cover_cache_path(title, artist)
        data: Optional[bytes] = None
        if cache.is_file():
            try:
                data = cache.read_bytes()
            except OSError:
                data = None
        if not data:
            data = self._download(title, artist)
            if not data:
                return None
            try:
                COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(data)
                self._prune_cache()
            except OSError:
                pass
        with Image.open(BytesIO(data)) as source:
            return ImageOps.fit(
                source.convert("RGB"), COVER_SIZE, method=Image.Resampling.LANCZOS
            )

    def _download(self, title: str, artist: str) -> Optional[bytes]:
        search = _strip_track_number(title)
        if not search:
            return None
        elapsed = time.monotonic() - self._last_request
        if elapsed < 1.2:
            time.sleep(1.2 - elapsed)
        self._last_request = time.monotonic()

        want_title = _normalize(search)
        want_artist = _normalize(artist)
        terms = f'artist:"{artist}" track:"{search}"' if artist else f'track:"{search}"'
        query = urllib.parse.urlencode({"q": terms, "limit": 6, "output": "json"})
        payload = self._json(f"https://api.deezer.com/search?{query}")
        for item in payload.get("data", []):
            if _normalize(str(item.get("title", ""))) != want_title:
                continue
            got_artist = _normalize(str(item.get("artist", {}).get("name", "")))
            if want_artist and got_artist and not (
                want_artist in got_artist or got_artist in want_artist
            ):
                continue
            album = item.get("album", {})
            url = album.get("cover_big") or album.get("cover_medium") or album.get("cover")
            if url:
                data = self._bytes(url)
                if data:
                    return data

        term = f"{artist} {search}".strip()
        params = urllib.parse.urlencode({"term": term, "entity": "song", "limit": 8})
        payload = self._json(f"https://itunes.apple.com/search?{params}")
        for item in payload.get("results", []):
            if _normalize(str(item.get("trackName", ""))) != want_title:
                continue
            got_artist = _normalize(str(item.get("artistName", "")))
            if want_artist and got_artist and not (
                want_artist in got_artist or got_artist in want_artist
            ):
                continue
            url = str(item.get("artworkUrl100", ""))
            if url:
                return self._bytes(url.replace("100x100bb", "600x600bb"))
        return None

    @staticmethod
    def _json(url: str) -> dict:
        request = urllib.request.Request(
            url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = response.read(1_500_000).decode("utf-8", "replace")
        return json.loads(payload)

    @staticmethod
    def _bytes(url: str) -> Optional[bytes]:
        request = urllib.request.Request(
            url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
        )
        with urllib.request.urlopen(request, timeout=6) as response:
            data = response.read(3_000_000)
        return data if len(data) > 512 else None

    @staticmethod
    def _prune_cache() -> None:
        try:
            files = list(COVER_CACHE_DIR.iterdir())
            if len(files) <= 400:
                return
            files.sort(key=lambda entry: entry.stat().st_mtime)
            for stale in files[: len(files) - 400]:
                stale.unlink(missing_ok=True)
        except OSError:
            pass


def scan_audio_files(folder: Path) -> list[Path]:
    found: list[Path] = []
    if not folder.is_dir():
        return found
    try:
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$", "~")))
            for name in files:
                if name.startswith("."):
                    continue
                if Path(name).suffix.lower() in AUDIO_EXTENSIONS:
                    found.append(Path(root) / name)
    except OSError as exc:
        logger.warning("No se pudo recorrer %s: %s", folder, exc)
    found.sort(key=lambda item: str(item).casefold())
    return found


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class PlayMode(Enum):
    SEQUENTIAL = "seq"
    REPEAT_ALL = "loop"
    REPEAT_ONE = "one"
    SHUFFLE = "shuffle"

    @classmethod
    def from_value(cls, value: str) -> "PlayMode":
        if value == "random":
            return cls.SHUFFLE
        for mode in cls:
            if mode.value == value:
                return mode
        return cls.SEQUENTIAL

    @property
    def label(self) -> str:
        return {
            PlayMode.SEQUENTIAL: "Secuencial",
            PlayMode.REPEAT_ALL: "Repetir todo",
            PlayMode.REPEAT_ONE: "Repetir pista",
            PlayMode.SHUFFLE: "Aleatorio",
        }[self]


class AudioPlayer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._volume = _as_float(config.volume, 0.8, 0.0, 1.0)
        self._muted = bool(config.muted)
        self._mode = PlayMode.from_value(config.play_mode)
        self._folder = resolve_music_folder(config.music_folder)
        self._tracks: list[Track] = []
        self._index = 0
        self._state = PlaybackState.STOPPED
        self._offset = 0.0
        self._pause_position = 0.0
        self._last_action = 0.0
        self._scan_token = 0
        self._device_ready = False
        self.on_library_changed: Optional[Callable[[], None]] = None
        self.on_tracks_enriched: Optional[Callable[[list[int]], None]] = None

        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            self._device_ready = True
        except pygame.error as exc:
            logger.error("Sin salida de audio: %s", exc)
        if self._device_ready:
            self._apply_volume()

        self.reload_playlist(enrich=False)
        if config.last_track:
            self._select_path(Path(config.last_track))

    @property
    def music_folder(self) -> Path:
        with self._lock:
            return self._folder

    @property
    def tracks(self) -> tuple[Track, ...]:
        with self._lock:
            return tuple(self._tracks)

    @property
    def state(self) -> PlaybackState:
        with self._lock:
            return self._state

    @property
    def mode(self) -> PlayMode:
        with self._lock:
            return self._mode

    @property
    def index(self) -> int:
        with self._lock:
            return self._index

    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def duration(self) -> float:
        with self._lock:
            track = self._current_locked()
            return track.duration if track else 0.0

    def current(self) -> Optional[Track]:
        with self._lock:
            return self._current_locked()

    def _current_locked(self) -> Optional[Track]:
        return self._tracks[self._index] if self._tracks else None

    def _select_path(self, path: Path) -> None:
        with self._lock:
            for index, track in enumerate(self._tracks):
                if track.path == path:
                    self._index = index
                    return

    def _notify_library_changed(self) -> None:
        callback = self.on_library_changed
        if callback:
            try:
                callback()
            except Exception:
                logger.exception("Fallo notificando la biblioteca")

    def _start_metadata_scan(self, tracks: list[Track], token: int) -> None:
        if not tracks:
            return
        threading.Thread(
            target=self._enrich_tracks, args=(token, tracks), daemon=True
        ).start()

    def _enrich_tracks(self, token: int, tracks: list[Track]) -> None:
        with self._lock:
            first = self._index
        order = [first] + [index for index in range(len(tracks)) if index != first]
        pending: list[int] = []
        last_emit = time.monotonic()
        for index in order:
            if token != self._scan_token:
                return
            track = tracks[index]
            title, artist, album, duration = read_metadata(track.path)
            track.title = title or track.title
            track.artist = artist
            track.album = album
            track.duration = duration
            pending.append(index)
            now = time.monotonic()
            if len(pending) >= 24 or now - last_emit >= 0.25:
                self._emit_enriched(pending)
                pending = []
                last_emit = now
        if pending:
            self._emit_enriched(pending)

    def _emit_enriched(self, indices: list[int]) -> None:
        callback = self.on_tracks_enriched
        if not callback:
            return
        try:
            callback(indices)
        except Exception:
            logger.exception("Fallo notificando metadatos")

    def enrich_library(self) -> None:
        with self._lock:
            self._scan_token += 1
            token = self._scan_token
            tracks = list(self._tracks)
        self._start_metadata_scan(tracks, token)

    def reload_playlist(self, enrich: bool = True) -> int:
        with self._lock:
            self._scan_token += 1
            token = self._scan_token
            previous = self._current_locked()
            previous_path = previous.path if previous else None
            paths = scan_audio_files(self._folder)
            tracks = [Track(path=path, title=path.stem) for path in paths]
            self._tracks = tracks
            self._index = 0
            if tracks:
                wanted = previous_path or (
                    Path(self.config.last_track) if self.config.last_track else None
                )
                if wanted is not None:
                    self._index = next(
                        (i for i, track in enumerate(tracks) if track.path == wanted), 0
                    )
            count = len(tracks)
        if enrich:
            self._start_metadata_scan(tracks, token)
        logger.info("Biblioteca: %d pistas en %s", count, self._folder)
        self._notify_library_changed()
        return count

    def set_music_folder(self, folder: Path) -> int:
        folder = Path(folder)
        if not folder.is_dir():
            raise ValueError(f"Carpeta no válida: {folder}")
        with self._lock:
            was_playing = self._state is PlaybackState.PLAYING
            self.stop()
            self._folder = folder
            self.config.music_folder = str(folder)
            self.config.last_track = None
        count = self.reload_playlist()
        if was_playing and count:
            self.play_index(0)
        return count

    def _apply_volume(self) -> None:
        if self._device_ready:
            pygame.mixer.music.set_volume(0.0 if self._muted else self._volume)

    def _touch(self) -> None:
        self._last_action = time.monotonic()

    def play(self) -> bool:
        with self._lock:
            track = self._current_locked()
            if track is None or not self._device_ready:
                return False
            if track.duration <= 0:
                title, artist, album, duration = read_metadata(track.path)
                track.title = title or track.title
                track.artist = artist
                track.album = album
                track.duration = duration
            try:
                pygame.mixer.music.load(str(track.path))
                self._apply_volume()
                pygame.mixer.music.play()
                self._offset = 0.0
                self._pause_position = 0.0
                self._state = PlaybackState.PLAYING
                self.config.last_track = str(track.path)
                self._touch()
                return True
            except Exception as exc:
                logger.error("No se pudo reproducir %s: %s", track.path, exc)
                self._state = PlaybackState.STOPPED
                return False

    def play_index(self, index: int) -> bool:
        with self._lock:
            if not 0 <= index < len(self._tracks):
                return False
            self._index = index
            return self.play()

    def pause(self) -> None:
        with self._lock:
            if self._state is not PlaybackState.PLAYING or not self._device_ready:
                return
            position = pygame.mixer.music.get_pos()
            fallback = self._offset
            self._pause_position = (
                self._offset + position / 1000.0 if position >= 0 else fallback
            )
            pygame.mixer.music.pause()
            self._state = PlaybackState.PAUSED
            self._touch()

    def resume(self) -> None:
        with self._lock:
            if self._state is not PlaybackState.PAUSED or not self._device_ready:
                return
            pygame.mixer.music.unpause()
            self._state = PlaybackState.PLAYING
            self._touch()

    def toggle_pause(self) -> None:
        state = self.state
        if state is PlaybackState.PLAYING:
            self.pause()
        elif state is PlaybackState.PAUSED:
            self.resume()
        else:
            self.play()

    def stop(self) -> None:
        with self._lock:
            if self._device_ready:
                pygame.mixer.music.stop()
            self._state = PlaybackState.STOPPED
            self._offset = 0.0
            self._pause_position = 0.0
            self._touch()

    def next(self, auto: bool = False) -> None:
        with self._lock:
            if not self._tracks:
                return
            size = len(self._tracks)
            mode = self._mode
            if auto and mode is PlayMode.SEQUENTIAL:
                if self._index + 1 >= size:
                    self.stop()
                    return
                self._index += 1
            elif mode is PlayMode.SHUFFLE:
                if size > 1:
                    self._index = random.choice(
                        [i for i in range(size) if i != self._index]
                    )
                elif auto:
                    self._index = 0
            elif auto and mode is PlayMode.REPEAT_ONE:
                pass
            else:
                self._index = (self._index + 1) % size
            self.play()

    def previous(self) -> None:
        with self._lock:
            if not self._tracks:
                return
            if self.get_position() > 3.0:
                self.seek(0.0)
                return
            self._index = (self._index - 1) % len(self._tracks)
            self.play()

    def cycle_mode(self) -> PlayMode:
        with self._lock:
            modes = tuple(PlayMode)
            self._mode = modes[(modes.index(self._mode) + 1) % len(modes)]
            self.config.play_mode = self._mode.value
            return self._mode

    def set_volume(self, value: float) -> None:
        with self._lock:
            self._volume = _as_float(value, self._volume, 0.0, 1.0)
            if self._volume > 0.0:
                self._muted = False
            self.config.volume = self._volume
            self.config.muted = self._muted
            self._apply_volume()

    def toggle_mute(self) -> None:
        with self._lock:
            self._muted = not self._muted
            self.config.muted = self._muted
            self._apply_volume()
            self._touch()

    def seek(self, seconds: float) -> None:
        with self._lock:
            track = self._current_locked()
            if track is None or not self._device_ready or track.duration <= 0:
                return
            target = max(0.0, min(float(seconds), max(0.0, track.duration - 0.25)))
            previous_state = self._state
            try:
                pygame.mixer.music.load(str(track.path))
                self._apply_volume()
                pygame.mixer.music.play(start=target)
                self._offset = target
                self._pause_position = target
                if previous_state is PlaybackState.PLAYING:
                    self._state = PlaybackState.PLAYING
                else:
                    pygame.mixer.music.pause()
                    self._state = PlaybackState.PAUSED
                self._touch()
            except Exception as exc:
                logger.warning("No se pudo buscar en %s: %s", track.path, exc)

    def get_position(self) -> float:
        with self._lock:
            return self._position_locked()

    def _position_locked(self) -> float:
        if not self._device_ready:
            return self._offset
        if self._state is PlaybackState.PAUSED:
            return self._pause_position
        if self._state is PlaybackState.STOPPED:
            return 0.0
        try:
            position = pygame.mixer.music.get_pos()
        except pygame.error:
            return self._offset
        if position < 0:
            return self._offset
        result = self._offset + position / 1000.0
        track = self._current_locked()
        if track and track.duration > 0:
            result = min(result, track.duration)
        return result

    def is_finished(self) -> bool:
        with self._lock:
            return (
                self._state is PlaybackState.PLAYING
                and self._device_ready
                and not pygame.mixer.music.get_busy()
                and time.monotonic() - self._last_action > 0.8
            )

    def shutdown(self) -> None:
        with self._lock:
            self._device_ready = False
            self._state = PlaybackState.STOPPED
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.quit()
            except Exception:
                pass


class MiniPlayer(ctk.CTk):
    def __init__(self, player: AudioPlayer, config: Config, app: "TinyTuneApp") -> None:
        super().__init__()
        self.player = player
        self.config = config
        self.app = app
        self._events: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._seeking = False
        self._quitting = False
        self._playlist_visible = bool(config.playlist_open)
        self._cover_key: Optional[str] = None
        self._cover_image: Optional[ctk.CTkImage] = None
        self._flash_text = ""
        self._flash_until = 0.0
        self._search_query = ""
        self._search_job: Optional[str] = None
        self._current_row: Optional[str] = None
        self._last_state: Optional[tuple] = None
        self._drag_offset = (0, 0)
        self._x = 0
        self._y = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=COLOR_BG)
        self.title(APP_NAME)
        self.protocol("WM_DELETE_WINDOW", self.hide)

        self._build_geometry()
        self._build_ui()
        self._bind_shortcuts()
        self.reload_library_view()
        self._drain_events()
        self._tick_ui()
        self._tick_progress()

    def post(self, callback: Callable[[], None]) -> None:
        self._events.put(callback)

    def _drain_events(self) -> None:
        while True:
            try:
                callback = self._events.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                logger.exception("Error ejecutando una tarea de interfaz")
        if not self._quitting:
            self.after(80, self._drain_events)

    def _scaled(self, value: float) -> int:
        return max(1, round(value * self._get_window_scaling()))

    def _build_geometry(self) -> None:
        scale = self._get_window_scaling()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = round(WIN_W * scale)
        height = round(
            (WIN_H_EXPANDED if self._playlist_visible else WIN_H_COLLAPSED) * scale
        )
        x = self.config.window_x
        y = self.config.window_y
        if x is None:
            x = screen_w - width - self._scaled(20)
        if y is None:
            y = screen_h - height - self._scaled(56)
        x = max(0, min(int(x), max(0, screen_w - width)))
        y = max(0, min(int(y), max(0, screen_h - height - self._scaled(40))))
        self._x, self._y = x, y
        self.geometry(f"{WIN_W}x{WIN_H_EXPANDED if self._playlist_visible else WIN_H_COLLAPSED}+{x}+{y}")
        icon = resource_path("icon.ico")
        if icon.is_file():
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass

    def _build_ui(self) -> None:
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=74)
        self.header.pack(fill="x", padx=14, pady=(12, 2))
        self.header.pack_propagate(False)

        self.cover_label = ctk.CTkLabel(
            self.header, text="♪", width=COVER_SIZE[0], height=COVER_SIZE[1],
            fg_color=COLOR_SURFACE, corner_radius=10,
            font=("Segoe UI Symbol", 26), text_color=COLOR_SUBTLE,
        )
        self.cover_label.pack(side="left", padx=(0, 12))

        title_box = ctk.CTkFrame(self.header, fg_color="transparent")
        title_box.pack(side="left", fill="both", expand=True)

        self.lbl_title = ctk.CTkLabel(
            title_box, text="Sin pistas", font=("Segoe UI", 14, "bold"),
            text_color=COLOR_TEXT, anchor="w", justify="left",
        )
        self.lbl_title.pack(fill="x", pady=(7, 0))

        self.lbl_subtitle = ctk.CTkLabel(
            title_box, text="Añade música a tu carpeta", font=("Segoe UI", 10),
            text_color=COLOR_SUBTLE, anchor="w", justify="left",
        )
        self.lbl_subtitle.pack(fill="x", pady=(1, 0))

        self.btn_close = ctk.CTkButton(
            self.header, text=ICON_CLOSE, width=26, height=26,
            fg_color="transparent", hover_color=COLOR_HOVER,
            text_color=COLOR_SUBTLE, font=(ICON_FONT, 10),
            command=self.hide, corner_radius=6,
        )
        self.btn_close.pack(side="right", anchor="n")

        self.btn_settings = ctk.CTkButton(
            self.header, text=ICON_SETTINGS, width=26, height=26,
            fg_color="transparent", hover_color=COLOR_HOVER,
            text_color=COLOR_SUBTLE, font=(ICON_FONT, 11),
            command=self._open_settings, corner_radius=6,
        )
        self.btn_settings.pack(side="right", anchor="n", padx=(0, 2))

        progress = ctk.CTkFrame(self, fg_color="transparent")
        progress.pack(fill="x", padx=14, pady=(3, 0))

        self.lbl_time_current = ctk.CTkLabel(
            progress, text="0:00", font=("Segoe UI", 9), text_color=COLOR_SUBTLE, width=34,
        )
        self.lbl_time_current.pack(side="left")

        self.slider_progress = ctk.CTkSlider(
            progress, from_=0, to=100, height=12, button_length=10,
            fg_color=COLOR_HOVER, progress_color=COLOR_ACCENT,
            button_color=COLOR_TEXT, button_hover_color=COLOR_ACCENT,
            command=self._on_seek_drag,
        )
        self.slider_progress.pack(side="left", fill="x", expand=True, padx=8)
        self.slider_progress.bind("<ButtonPress-1>", self._on_seek_start)
        self.slider_progress.bind("<ButtonRelease-1>", self._on_seek_release)

        self.lbl_time_total = ctk.CTkLabel(
            progress, text="0:00", font=("Segoe UI", 9), text_color=COLOR_SUBTLE, width=34,
        )
        self.lbl_time_total.pack(side="right")

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(pady=(7, 7))

        self.btn_mode = self._icon_button(
            controls, ICON_REPEAT_ALL, self._cycle_mode, 32, 13
        )
        self.btn_mode.pack(side="left", padx=3)
        self._icon_button(controls, ICON_PREV, self._previous, 32, 13).pack(
            side="left", padx=3
        )

        self.btn_play = ctk.CTkButton(
            controls, text=ICON_PLAY, width=48, height=48, corner_radius=24,
            fg_color=COLOR_TEXT, hover_color="#E4E4E4",
            text_color="#0B0B0C", font=(ICON_FONT, 17),
            command=self._toggle_play,
        )
        self.btn_play.pack(side="left", padx=11)

        self._icon_button(controls, ICON_NEXT, self._next, 32, 13).pack(
            side="left", padx=3
        )
        self.btn_list = self._icon_button(
            controls, ICON_LIST, self._toggle_playlist, 32, 13
        )
        self.btn_list.pack(side="left", padx=3)

        volume = ctk.CTkFrame(self, fg_color="transparent")
        volume.pack(fill="x", padx=16, pady=(0, 9))
        volume.grid_columnconfigure(2, weight=1)

        self._icon_button(
            volume, ICON_FOLDER, self._change_folder, 28, 12
        ).grid(row=0, column=0, padx=(0, 7))

        self.btn_mute = self._icon_button(
            volume, ICON_VOLUME, self._toggle_mute, 28, 12
        )
        self.btn_mute.grid(row=0, column=1)

        self.slider_volume = ctk.CTkSlider(
            volume, from_=0, to=1, height=12, button_length=10,
            fg_color=COLOR_HOVER, progress_color=COLOR_ACCENT,
            button_color=COLOR_TEXT, button_hover_color=COLOR_ACCENT,
            command=self._on_volume,
        )
        self.slider_volume.set(self.player.volume)
        self.slider_volume.grid(row=0, column=2, sticky="ew", padx=10)
        self.slider_volume.bind("<ButtonRelease-1>", self._save_volume)

        self._icon_button(
            volume, ICON_WEB, self._open_credits, 28, 12
        ).grid(row=0, column=3, padx=(7, 0))

        self.playlist_frame = ctk.CTkFrame(
            self, fg_color=COLOR_SURFACE, corner_radius=12
        )
        self.search_entry = ctk.CTkEntry(
            self.playlist_frame, placeholder_text="Buscar en la biblioteca",
            fg_color=COLOR_BG, border_color=COLOR_BORDER, border_width=1,
            text_color=COLOR_TEXT, height=32, font=("Segoe UI", 11),
        )
        self.search_entry.pack(fill="x", padx=10, pady=(10, 7))
        self.search_entry.bind("<KeyRelease>", self._on_search_change)
        self.search_entry.bind("<Escape>", self._clear_search)

        tree_box = ctk.CTkFrame(self.playlist_frame, fg_color="transparent")
        tree_box.pack(fill="both", expand=True, padx=(8, 5), pady=(0, 8))

        self._configure_tree_style()
        self.tree = ttk.Treeview(
            tree_box, columns=("title", "time"), show="",
            selectmode="browse", style="Tiny.Treeview",
        )
        self.tree.column("title", width=self._scaled(268), anchor="w", stretch=True)
        self.tree.column("time", width=self._scaled(48), anchor="e", stretch=False)
        self.tree.tag_configure("odd", background=COLOR_SURFACE, foreground=COLOR_TEXT)
        self.tree.tag_configure("even", background="#1D1E22", foreground=COLOR_TEXT)
        self.tree.tag_configure("current", foreground=COLOR_ACCENT, font=("Segoe UI", 10, "bold"))
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<Return>", self._on_tree_enter)

        scrollbar = ctk.CTkScrollbar(
            tree_box, command=self.tree.yview, width=10,
            fg_color="transparent", button_color="#34373C", button_hover_color="#4A4E55",
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.empty_label = ctk.CTkLabel(
            tree_box, text="No hay pistas\nAñade archivos a tu carpeta de música",
            font=("Segoe UI", 11), text_color=COLOR_SUBTLE, justify="center",
        )

        if self._playlist_visible:
            self.playlist_frame.pack(fill="both", expand=True, padx=12, pady=(5, 12))

        for widget in (self.header, self.cover_label, self.lbl_title, self.lbl_subtitle):
            widget.bind("<ButtonPress-1>", self._start_move)
            widget.bind("<B1-Motion>", self._do_move)
            widget.bind("<ButtonRelease-1>", self._end_move)
            widget.bind("<Double-Button-1>", lambda _event: self._toggle_playlist())
        self.bind("<Configure>", self._on_configure)

    def _icon_button(
        self, parent, glyph: str, command, size: int, icon_size: int,
        color: str = COLOR_SUBTLE,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=glyph, width=size, height=size,
            fg_color="transparent", hover_color=COLOR_HOVER,
            text_color=color, font=(ICON_FONT, icon_size),
            command=command, corner_radius=7,
        )

    def _configure_tree_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Tiny.Treeview",
            background=COLOR_SURFACE, fieldbackground=COLOR_SURFACE,
            foreground=COLOR_TEXT, borderwidth=0, relief="flat",
            rowheight=self._scaled(27), font=("Segoe UI", 10),
        )
        style.map(
            "Tiny.Treeview",
            background=[("selected", COLOR_HOVER)],
            foreground=[("selected", COLOR_TEXT)],
        )
        style.layout("Tiny.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def _bind_shortcuts(self) -> None:
        self.bind("<space>", self._shortcut_play)
        self.bind("<Left>", lambda _event: self._shortcut_seek(-5))
        self.bind("<Right>", lambda _event: self._shortcut_seek(5))
        self.bind("<Up>", lambda _event: self._shortcut_volume(0.05))
        self.bind("<Down>", lambda _event: self._shortcut_volume(-0.05))
        self.bind("<n>", self._shortcut_next)
        self.bind("<p>", self._shortcut_previous)
        self.bind("<m>", self._shortcut_mute)
        self.bind("<l>", self._shortcut_list)
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Control-q>", lambda _event: self.app._quit())
        self.bind("<Escape>", lambda _event: self.hide())

    def _is_typing(self) -> bool:
        widget = self.focus_get()
        try:
            return widget is not None and widget.winfo_class() in ("Entry", "TEntry", "Text")
        except Exception:
            return False

    def _shortcut_play(self, _event) -> str:
        if not self._is_typing():
            self._toggle_play()
        return "break"

    def _shortcut_seek(self, delta: float) -> None:
        if self._is_typing():
            return
        self.player.seek(self.player.get_position() + delta)
        self.sync_playback()

    def _shortcut_volume(self, delta: float) -> None:
        if self._is_typing():
            return
        value = max(0.0, min(1.0, self.player.volume + delta))
        self.slider_volume.set(value)
        self.player.set_volume(value)
        self._update_mute_button()

    def _shortcut_next(self, _event) -> None:
        if not self._is_typing():
            self._next()

    def _shortcut_previous(self, _event) -> None:
        if not self._is_typing():
            self._previous()

    def _shortcut_mute(self, _event) -> None:
        if not self._is_typing():
            self._toggle_mute()

    def _shortcut_list(self, _event) -> None:
        if not self._is_typing():
            self._toggle_playlist()

    def _focus_search(self, _event=None) -> str:
        if not self._playlist_visible:
            self._set_playlist_visible(True)
        self.search_entry.focus_set()
        return "break"

    def _start_move(self, event) -> None:
        self._drag_offset = (
            event.x_root - self.winfo_rootx(),
            event.y_root - self.winfo_rooty(),
        )

    def _do_move(self, event) -> None:
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        width = self.winfo_width()
        height = self.winfo_height()
        x = max(0, min(x, self.winfo_screenwidth() - width))
        y = max(0, min(y, self.winfo_screenheight() - height - self._scaled(40)))
        self._x, self._y = x, y
        self.geometry(f"+{x}+{y}")

    def _end_move(self, _event) -> None:
        self.config.window_x = self._x
        self.config.window_y = self._y

    def _on_configure(self, event) -> None:
        if event.widget is self and not self._quitting and self.winfo_viewable():
            self._x, self._y = self.winfo_x(), self.winfo_y()
            self.config.window_x = self._x
            self.config.window_y = self._y

    def _toggle_play(self) -> None:
        self.player.toggle_pause()
        if self.player.state is PlaybackState.STOPPED and self.player.current():
            self._flash("No se pudo reproducir la pista")
        self.sync_playback()

    def _next(self) -> None:
        self.player.next()
        self.sync_playback()

    def _previous(self) -> None:
        self.player.previous()
        self.sync_playback()

    def _cycle_mode(self) -> None:
        mode = self.player.cycle_mode()
        self.config.save()
        self._update_mode_button()
        self._flash(f"Modo: {mode.label}")

    def _toggle_mute(self) -> None:
        self.player.toggle_mute()
        self._update_mute_button()
        self.config.save()

    def _update_mute_button(self) -> None:
        muted = self.player.muted
        self.btn_mute.configure(text=ICON_MUTE if muted else ICON_VOLUME)

    def _on_volume(self, value: float) -> None:
        self.player.set_volume(value)
        self._update_mute_button()

    def _save_volume(self, _event) -> None:
        self.config.save()

    def _on_seek_start(self, _event) -> None:
        self._seeking = True

    def _on_seek_drag(self, value: float) -> None:
        if self._seeking:
            self.lbl_time_current.configure(text=format_time(value))

    def _on_seek_release(self, _event) -> None:
        if not self._seeking:
            return
        self._seeking = False
        self.player.seek(self.slider_progress.get())
        self.sync_playback()

    def _change_folder(self) -> None:
        self.attributes("-topmost", False)
        try:
            chosen = filedialog.askdirectory(
                parent=self, title="Selecciona tu carpeta de música",
                initialdir=str(self.player.music_folder), mustexist=True,
            )
        finally:
            self.attributes("-topmost", True)
        if not chosen:
            return
        try:
            self.search_entry.delete(0, "end")
            self._search_query = ""
            count = self.player.set_music_folder(Path(chosen))
            self.config.save()
            self._flash(f"Biblioteca: {count} pistas")
            self.app.refresh_tray()
        except Exception as exc:
            logger.exception("No se pudo cambiar la carpeta: %s", exc)
            self._flash("No se pudo cambiar la carpeta")

    def _open_credits(self) -> None:
        webbrowser.open(CREDITS_URL, new=2)

    def _open_settings(self) -> None:
        if not self.winfo_viewable():
            self.show()
        existing = getattr(self, "_settings", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass
        settings = ctk.CTkToplevel(self)
        self._settings = settings
        settings.title("Ajustes")
        settings.resizable(False, False)
        settings.configure(fg_color=COLOR_BG)
        settings.transient(self)
        settings.attributes("-topmost", True)
        icon = resource_path("icon.ico")
        if icon.is_file():
            try:
                settings.iconbitmap(str(icon))
            except Exception:
                pass

        width, height = 352, 360
        scale = self._get_window_scaling()
        x = self.winfo_rootx() + (self.winfo_width() - round(width * scale)) // 2
        y = self.winfo_rooty() + (self.winfo_height() - round(height * scale)) // 2
        settings.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

        ctk.CTkLabel(
            settings, text="Ajustes", font=("Segoe UI", 18, "bold"),
            text_color=COLOR_TEXT,
        ).pack(pady=(16, 10))

        def add_switch(
            heading: str, description: str, value: bool, command
        ) -> BooleanVar:
            card = ctk.CTkFrame(settings, fg_color=COLOR_SURFACE, corner_radius=12)
            card.pack(fill="x", padx=16, pady=(0, 8))
            text_box = ctk.CTkFrame(card, fg_color="transparent")
            text_box.pack(side="left", fill="both", expand=True, padx=(12, 4), pady=10)
            ctk.CTkLabel(
                text_box, text=heading, font=("Segoe UI", 11, "bold"),
                text_color=COLOR_TEXT, anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                text_box, text=description, font=("Segoe UI", 9),
                text_color=COLOR_SUBTLE, anchor="w", justify="left", wraplength=228,
            ).pack(fill="x", pady=(1, 0))
            variable = BooleanVar(value=value)
            ctk.CTkSwitch(
                card, text="", width=40, variable=variable, command=command,
                progress_color=COLOR_ACCENT, button_color=COLOR_TEXT,
            ).pack(side="right", padx=(0, 12))
            return variable

        self.var_online = add_switch(
            "Carátulas en línea",
            "Busca una portada en internet cuando el archivo no trae una.",
            self.config.online_covers,
            self._toggle_online_covers,
        )
        if os.name == "nt":
            self.var_startup = add_switch(
                "Iniciar con Windows",
                "Abre TinyTune en la bandeja al encender el equipo.",
                self.app._startup_enabled(),
                self._toggle_startup_setting,
            )

        ctk.CTkButton(
            settings, text="Vaciar caché de carátulas", height=30,
            fg_color=COLOR_HOVER, hover_color="#323439",
            text_color=COLOR_TEXT, font=("Segoe UI", 10),
            command=self._clear_cover_cache,
        ).pack(pady=(2, 0))

        self.lbl_settings_status = ctk.CTkLabel(
            settings, text="", font=("Segoe UI", 9), text_color=COLOR_SUBTLE,
        )
        self.lbl_settings_status.pack(pady=(7, 0))

        ctk.CTkButton(
            settings, text="Cerrar", height=30, width=100,
            fg_color="transparent", hover_color=COLOR_HOVER,
            text_color=COLOR_SUBTLE, font=("Segoe UI", 10),
            command=settings.destroy,
        ).pack(pady=(8, 4))
        ctk.CTkLabel(
            settings, text=f"{APP_NAME} {APP_VERSION}", font=("Segoe UI", 9),
            text_color=COLOR_SUBTLE,
        ).pack(pady=(0, 10))

        settings.bind("<Escape>", lambda _event: settings.destroy())
        settings.after(80, lambda: (
            settings.grab_set(), settings.lift(), settings.focus_force()
        ))

    def _toggle_online_covers(self) -> None:
        enabled = bool(self.var_online.get())
        self.app.set_online_covers(enabled)
        self._set_settings_status(
            "Búsqueda de carátulas activada." if enabled
            else "Búsqueda de carátulas desactivada."
        )

    def _toggle_startup_setting(self) -> None:
        enabled = bool(self.var_startup.get())
        self.app.set_startup(enabled)
        self._set_settings_status(
            "TinyTune se abrirá con Windows." if enabled
            else "Inicio con Windows desactivado."
        )

    def _clear_cover_cache(self) -> None:
        self.app.clear_cover_cache()
        self._set_settings_status("Caché de carátulas vaciada.")

    def _set_settings_status(self, text: str) -> None:
        label = getattr(self, "lbl_settings_status", None)
        if label is not None:
            try:
                label.configure(text=text)
            except Exception:
                pass

    def _flash(self, text: str, seconds: float = 2.5) -> None:
        self._flash_text = text
        self._flash_until = time.monotonic() + seconds
        self.lbl_subtitle.configure(text=text)

    def _toggle_playlist(self) -> None:
        self._set_playlist_visible(not self._playlist_visible)

    def _set_playlist_visible(self, visible: bool) -> None:
        if visible == self._playlist_visible:
            return
        self._playlist_visible = visible
        self.config.playlist_open = visible
        self.config.save()
        scale = self._get_window_scaling()
        collapsed_h = round(WIN_H_COLLAPSED * scale)
        expanded_h = round(WIN_H_EXPANDED * scale)
        x, y = self._x, self._y
        if visible:
            new_y = max(0, y - (expanded_h - collapsed_h))
            self.playlist_frame.pack(fill="both", expand=True, padx=12, pady=(5, 12))
            self._populate_playlist()
        else:
            new_y = min(
                y + (expanded_h - collapsed_h),
                max(0, self.winfo_screenheight() - collapsed_h - self._scaled(40)),
            )
            self.playlist_frame.pack_forget()
        self._x, self._y = x, new_y
        self.geometry(
            f"{WIN_W}x{WIN_H_EXPANDED if visible else WIN_H_COLLAPSED}+{x}+{new_y}"
        )

    def _on_search_change(self, _event) -> None:
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(150, self._apply_search)

    def _apply_search(self) -> None:
        self._search_job = None
        self._search_query = self.search_entry.get().strip().lower()
        self._populate_playlist()

    def _clear_search(self, _event=None) -> str:
        self.search_entry.delete(0, "end")
        self._search_query = ""
        self._populate_playlist()
        return "break"

    def _filtered_indices(self) -> list[int]:
        tracks = self.player.tracks
        if not self._search_query:
            return list(range(len(tracks)))
        query = _normalize(self._search_query)
        result = []
        for index, track in enumerate(tracks):
            haystack = _normalize(
                f"{track.display_name} {track.album} {track.path.name}"
            )
            if query in haystack:
                result.append(index)
        return result

    def _populate_playlist(self) -> None:
        if not self._playlist_visible:
            return
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        tracks = self.player.tracks
        visible = 0
        for index in self._filtered_indices():
            track = tracks[index]
            stripe = "odd" if visible % 2 == 0 else "even"
            self.tree.insert(
                "", "end", iid=str(index),
                values=(track.display_name, format_time(track.duration)),
                tags=(stripe,),
            )
            visible += 1
        self._current_row = None
        if visible:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        self._paint_current_row()

    def _row_tags(self, iid: str) -> list[str]:
        try:
            tags = [tag for tag in self.tree.item(iid, "tags") if tag != "current"]
        except Exception:
            return []
        tags.append("current")
        return tags

    def _paint_current_row(self) -> None:
        if not self._playlist_visible:
            return
        if self._current_row and self.tree.exists(self._current_row):
            tags = [tag for tag in self.tree.item(self._current_row, "tags") if tag != "current"]
            self.tree.item(self._current_row, tags=tags)
        current = str(self.player.index)
        if self.tree.exists(current):
            self.tree.item(current, tags=self._row_tags(current))
            self._current_row = current
        else:
            self._current_row = None

    def _on_tree_click(self, event) -> None:
        if event.num != 1:
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        index = int(iid)
        if index == self.player.index:
            if self.player.state is PlaybackState.PLAYING:
                return
            if self.player.state is PlaybackState.PAUSED:
                self.player.resume()
                self.sync_playback()
                return
        self.player.play_index(index)
        self.sync_playback()

    def _on_tree_enter(self, _event) -> str:
        selection = self.tree.selection()
        if selection:
            self.player.play_index(int(selection[0]))
            self.sync_playback()
        return "break"

    def apply_metadata(self, indices: list[int]) -> None:
        if not indices:
            return
        self._update_tree_rows(indices)
        if self.player.index in indices:
            self.sync_playback()

    def _update_tree_rows(self, indices: list[int]) -> None:
        if not self._playlist_visible:
            return
        tracks = self.player.tracks
        for index in indices:
            if index >= len(tracks):
                continue
            iid = str(index)
            if self.tree.exists(iid):
                track = tracks[index]
                self.tree.item(
                    iid, values=(track.display_name, format_time(track.duration))
                )

    def reload_library_view(self) -> None:
        self._current_row = None
        self._cover_key = None
        self._populate_playlist()
        self.sync_playback()

    def sync_playback(self) -> None:
        track = self.player.current()
        state = self.player.state
        if track:
            self.lbl_title.configure(text=ellipsize(track.title, 34))
            default_subtitle = track.subtitle or track.path.parent.name
            self.lbl_time_total.configure(text=format_time(track.duration))
            self._update_cover(track)
        else:
            self.lbl_title.configure(text="Sin pistas")
            default_subtitle = "Añade música a tu carpeta"
            self.lbl_time_total.configure(text="0:00")
            self._update_cover(None)
        if time.monotonic() < self._flash_until:
            self.lbl_subtitle.configure(text=self._flash_text)
        else:
            self.lbl_subtitle.configure(text=default_subtitle)
        self.btn_play.configure(
            text=ICON_PAUSE if state is PlaybackState.PLAYING else ICON_PLAY
        )
        self._update_mode_button()
        self._update_mute_button()
        self._paint_current_row()
        self.app.refresh_tray()

    def _update_mode_button(self) -> None:
        mode = self.player.mode
        if mode is PlayMode.SEQUENTIAL:
            glyph, color = ICON_REPEAT_ALL, COLOR_SUBTLE
        elif mode is PlayMode.REPEAT_ALL:
            glyph, color = ICON_REPEAT_ALL, COLOR_ACCENT
        elif mode is PlayMode.REPEAT_ONE:
            glyph, color = ICON_REPEAT_ONE, COLOR_ACCENT
        else:
            glyph, color = ICON_SHUFFLE, COLOR_ACCENT
        self.btn_mode.configure(text=glyph, text_color=color)

    def _update_cover(self, track: Optional[Track]) -> None:
        key = str(track.path) if track else None
        if key == self._cover_key:
            return
        if not self.winfo_viewable():
            return
        self._cover_key = key
        image = read_cover(track.path, COVER_SIZE) if track else None
        self._set_cover_image(image)
        if image is None and track is not None and self.config.online_covers:
            self.app.request_online_cover(track)

    def _set_cover_image(self, image: Optional[Image.Image]) -> None:
        if image is not None:
            image = rounded_cover(image)
            self._cover_image = ctk.CTkImage(
                light_image=image, dark_image=image, size=COVER_SIZE
            )
            self.cover_label.configure(image=self._cover_image, text="")
        else:
            self._cover_image = None
            self.cover_label.configure(image=None, text="♪")

    def apply_online_cover(self, path: str, image: Image.Image) -> None:
        track = self.player.current()
        if track is None or str(track.path) != path or not self.winfo_viewable():
            return
        self._set_cover_image(image)

    def refresh_cover(self) -> None:
        self._cover_key = None
        if self.winfo_viewable():
            self.sync_playback()

    def _tick_ui(self) -> None:
        signature = (self.player.index, self.player.state)
        if signature != self._last_state:
            self._last_state = signature
            self.sync_playback()
        if self._flash_until and time.monotonic() >= self._flash_until:
            self._flash_until = 0.0
            self.sync_playback()
        delay = 400 if self.winfo_viewable() else 1200
        if not self._quitting:
            self.after(delay, self._tick_ui)

    def _tick_progress(self) -> None:
        if not self._quitting and self.winfo_viewable() and not self._seeking:
            state = self.player.state
            duration = self.player.duration
            if state in (PlaybackState.PLAYING, PlaybackState.PAUSED):
                position = self.player.get_position()
                if duration > 0:
                    self.slider_progress.configure(to=duration, state="normal")
                    self.slider_progress.set(min(position, duration))
                else:
                    self.slider_progress.configure(state="disabled")
                self.lbl_time_current.configure(text=format_time(position))
                self.lbl_time_total.configure(text=format_time(duration))
            elif state is PlaybackState.STOPPED:
                self.slider_progress.set(0)
                self.lbl_time_current.configure(text="0:00")
        delay = 250 if self.winfo_viewable() else 600
        if not self._quitting:
            self.after(delay, self._tick_progress)

    def show(self) -> None:
        scale = self._get_window_scaling()
        width = round(WIN_W * scale)
        height = round(
            (WIN_H_EXPANDED if self._playlist_visible else WIN_H_COLLAPSED) * scale
        )
        x = max(0, min(self._x, self.winfo_screenwidth() - width))
        y = max(0, min(
            self._y, self.winfo_screenheight() - height - self._scaled(40)
        ))
        self._x, self._y = x, y
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.update_idletasks()
        self.lift()
        self._x, self._y = self.winfo_x(), self.winfo_y()
        self._cover_key = None
        self.sync_playback()
        self._tick_progress()

    def hide(self) -> None:
        if self.winfo_viewable():
            self._x, self._y = self.winfo_x(), self.winfo_y()
        self.config.window_x = self._x
        self.config.window_y = self._y
        self.config.save()
        self.withdraw()

    def quit_app(self) -> None:
        self._quitting = True
        self.config.save()
        self.destroy()


class TinyTuneApp:
    def __init__(self, start_hidden: bool = False) -> None:
        self.config = Config.load()
        self.player = AudioPlayer(self.config)
        self._icon: Optional[pystray.Icon] = None
        self._running = True
        self._tray_signature: Optional[tuple] = None
        self._tray_paused, self._tray_playing = self._load_tray_images()
        self._hotkey_thread_id = 0
        self._show_event = create_show_event()
        self.cover_service = OnlineCoverService(
            self.config.online_covers, self._deliver_cover
        )

        self.root = MiniPlayer(self.player, self.config, self)
        self.player.on_library_changed = lambda: self.root.post(self.root.reload_library_view)
        self.player.on_tracks_enriched = lambda indices: self.root.post(
            lambda: self.root.apply_metadata(indices)
        )
        self.player.enrich_library()

        if start_hidden:
            self.root.withdraw()
        elif self.player.tracks:
            self.player.play()
            self.root.sync_playback()

        threading.Thread(target=self._monitor_playback, daemon=True).start()
        threading.Thread(target=self._run_tray, daemon=True).start()
        threading.Thread(target=self._media_hotkeys, daemon=True).start()
        if self._show_event:
            threading.Thread(target=self._wait_show_event, daemon=True).start()
        logger.info("%s %s iniciado", APP_NAME, APP_VERSION)

    def _wait_show_event(self) -> None:
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel32.WaitForSingleObject.restype = ctypes.c_ulong
            while self._running:
                result = kernel32.WaitForSingleObject(self._show_event, 500)
                if result == 0 and self._running:
                    self.root.post(self.root.show)
                elif result == 0xFFFFFFFF:
                    time.sleep(0.5)
        except Exception:
            logger.debug("No se pudo escuchar la señal de instancia", exc_info=True)

    def _deliver_cover(self, path: str, image: Image.Image) -> None:
        root = getattr(self, "root", None)
        if root is not None:
            root.post(lambda: root.apply_online_cover(path, image))

    def request_online_cover(self, track: Track) -> None:
        self.cover_service.request(track)

    def set_online_covers(self, enabled: bool) -> None:
        self.config.online_covers = bool(enabled)
        self.config.save()
        self.cover_service.set_enabled(enabled)
        if enabled:
            self.root.post(self.root.refresh_cover)

    @staticmethod
    def clear_cover_cache() -> None:
        OnlineCoverService.clear_cache()

    def _load_tray_images(self) -> tuple[Image.Image, Image.Image]:
        try:
            with Image.open(resource_path("icon.ico")) as source:
                base = ImageOps.fit(
                    source.convert("RGBA"), (64, 64), method=Image.Resampling.LANCZOS
                )
        except Exception:
            base = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(base)
            draw.ellipse((2, 2, 61, 61), fill=(29, 185, 84, 255))
            draw.ellipse((18, 34, 29, 45), fill=(10, 10, 10, 255))
            draw.ellipse((33, 25, 44, 36), fill=(10, 10, 10, 255))
            draw.rectangle((26, 14, 29, 39), fill=(10, 10, 10, 255))
            draw.rectangle((41, 7, 44, 31), fill=(10, 10, 10, 255))
            draw.rectangle((26, 14, 44, 18), fill=(10, 10, 10, 255))
        paused = base.copy()
        playing = base.copy()
        draw = ImageDraw.Draw(playing)
        draw.ellipse(
            (45, 45, 62, 62), fill=(29, 185, 84, 255), outline=(17, 18, 20, 255), width=2
        )
        return paused, playing

    def refresh_tray(self) -> None:
        icon = self._icon
        if icon is None:
            return
        track = self.player.current()
        state = self.player.state
        name = track.display_name if track else "Sin pistas"
        signature = (self.player.index, state, name)
        if signature == self._tray_signature:
            return
        self._tray_signature = signature
        prefix = {
            PlaybackState.PLAYING: "Reproduciendo",
            PlaybackState.PAUSED: "En pausa",
            PlaybackState.STOPPED: "Detenido",
        }[state]
        try:
            icon.title = ellipsize(f"{prefix}: {name} — {APP_NAME}", 120)
            icon.icon = self._tray_playing if state is PlaybackState.PLAYING else self._tray_paused
        except Exception:
            logger.debug("No se pudo actualizar el icono de bandeja", exc_info=True)

    @staticmethod
    def _startup_command() -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        return f'"{sys.executable}" "{Path(__file__).resolve()}" --minimized'

    def _startup_enabled(self, *_args) -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return value == self._startup_command()
        except OSError:
            return False

    def _toggle_startup(self, *_args) -> None:
        self.set_startup(not self._startup_enabled())

    def set_startup(self, enabled: bool, notify: bool = True) -> None:
        if os.name != "nt":
            return
        try:
            import winreg
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                if enabled:
                    winreg.SetValueEx(
                        key, APP_NAME, 0, winreg.REG_SZ, self._startup_command()
                    )
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except FileNotFoundError:
                        pass
            if notify:
                self.root.post(lambda: self.root._flash(
                    "Inicio con Windows activado" if enabled
                    else "Inicio con Windows desactivado"
                ))
        except OSError as exc:
            logger.error("No se pudo cambiar el inicio automático: %s", exc)

    def _build_menu(self) -> pystray.Menu:
        def track_label(_item) -> str:
            track = self.player.current()
            return ellipsize(track.display_name, 52) if track else "Sin pistas"

        def toggle_label(_item) -> str:
            return (
                "Pausar"
                if self.player.state is PlaybackState.PLAYING
                else "Reproducir"
            )

        def has_tracks(_item) -> bool:
            return bool(self.player.tracks)

        return pystray.Menu(
            pystray.MenuItem(track_label, lambda *_args: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(toggle_label, self._tray_toggle),
            pystray.MenuItem("Siguiente", self._tray_next, enabled=has_tracks),
            pystray.MenuItem("Anterior", self._tray_previous, enabled=has_tracks),
            pystray.MenuItem(
                "Silenciar", self._tray_mute,
                checked=lambda _item: self.player.muted,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Mostrar reproductor",
                lambda *_args: self.root.post(self.root.show),
                default=True,
            ),
            pystray.MenuItem("Abrir carpeta", self._open_folder),
            pystray.MenuItem(
                "Cambiar carpeta…",
                lambda *_args: self.root.post(self.root._change_folder),
            ),
            pystray.MenuItem("Recargar biblioteca", self._reload_library),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Iniciar con Windows", self._toggle_startup,
                checked=self._startup_enabled,
            ),
            pystray.MenuItem(
                "Ajustes…",
                lambda *_args: self.root.post(self.root._open_settings),
            ),
            pystray.MenuItem(
                "Créditos", lambda *_args: webbrowser.open(CREDITS_URL, new=2)
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", self._quit),
        )

    def _tray_action(self, action: Callable[[], object]) -> None:
        try:
            action()
        except Exception:
            logger.exception("Error en una acción de bandeja")
        self.refresh_tray()
        self.root.post(self.root.sync_playback)

    def _tray_toggle(self, *_args) -> None:
        self._tray_action(self.player.toggle_pause)

    def _tray_next(self, *_args) -> None:
        self._tray_action(self.player.next)

    def _tray_previous(self, *_args) -> None:
        self._tray_action(self.player.previous)

    def _tray_mute(self, *_args) -> None:
        self._tray_action(self.player.toggle_mute)

    def _run_tray(self) -> None:
        try:
            self._icon = pystray.Icon(
                APP_NAME, icon=self._tray_paused, title=APP_NAME,
                menu=self._build_menu(),
            )
            self.refresh_tray()
            self._icon.run()
        except Exception as exc:
            logger.exception("Fallo en la bandeja del sistema: %s", exc)

    def _monitor_playback(self) -> None:
        while self._running:
            time.sleep(0.5)
            if not self._running:
                break
            try:
                if self.player.is_finished():
                    self.player.next(auto=True)
                    self.refresh_tray()
                    self.root.post(self.root.sync_playback)
            except Exception:
                logger.exception("Error vigilando la reproducción")

    def _media_hotkeys(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes.wintypes as wintypes
            user32 = ctypes.windll.user32
            self._hotkey_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            bindings = (
                (1, 0xB3, self.player.toggle_pause),
                (2, 0xB0, self.player.next),
                (3, 0xB1, self.player.previous),
                (4, 0xB2, self.player.stop),
            )
            registered = [
                (hotkey_id, action)
                for hotkey_id, virtual_key, action in bindings
                if user32.RegisterHotKey(None, hotkey_id, 0, virtual_key)
            ]
            if not registered:
                return
            message = wintypes.MSG()
            while self._running and user32.GetMessageW(
                ctypes.byref(message), None, 0, 0
            ) > 0:
                if message.message == 0x0312:
                    for hotkey_id, action in registered:
                        if message.wParam == hotkey_id:
                            action()
                            self.refresh_tray()
                            self.root.post(self.root.sync_playback)
                            break
            for hotkey_id, _action in registered:
                user32.UnregisterHotKey(None, hotkey_id)
        except Exception:
            logger.debug("Atajos multimedia no disponibles", exc_info=True)

    def _open_folder(self, *_args) -> None:
        try:
            folder = self.player.music_folder
            if os.name == "nt":
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            logger.error("No se pudo abrir la carpeta: %s", exc)

    def _reload_library(self, *_args) -> None:
        try:
            was_playing = self.player.state is PlaybackState.PLAYING
            self.player.stop()
            count = self.player.reload_playlist()
            if was_playing and count:
                self.player.play()
            self.refresh_tray()
            self.root.post(lambda: self.root._flash(f"Biblioteca: {count} pistas"))
        except Exception:
            logger.exception("No se pudo recargar la biblioteca")

    def _quit(self, *_args) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self.config.save()
        except Exception:
            pass
        self.player.shutdown()
        self.cover_service.stop()
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
        if self._hotkey_thread_id and os.name == "nt":
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self._hotkey_thread_id, 0x0012, 0, 0
                )
            except Exception:
                pass
        self.root.post(self.root.quit_app)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    _mutex, already_running = acquire_instance_lock()
    if already_running:
        if not signal_existing_instance():
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    "TinyTune ya está en ejecución.\n"
                    "Usa el icono de la bandeja del sistema.",
                    APP_NAME, 0x40,
                )
            except Exception:
                pass
        return
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"{APP_NAME}.{APP_VERSION}"
            )
        except Exception:
            pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("green")
    app = TinyTuneApp(start_hidden="--minimized" in sys.argv)
    try:
        app.run()
    except KeyboardInterrupt:
        app._quit()
    except Exception:
        logger.exception("Fallo fatal")
        if os.name == "nt" and sys.stderr is None:
            ctypes.windll.user32.MessageBoxW(
                None, "TinyTune no pudo iniciarse. Revisa el registro de errores.",
                APP_NAME, 0x10,
            )


if __name__ == "__main__":
    main()
