"""
TinyTune - Reproductor de audio ultraligero, estable y fluido
"""
import os
import sys
import threading
import time
import random
from pathlib import Path
from PIL import Image, ImageDraw
import pystray
import pygame
import customtkinter as ctk
import mutagen

# ============ CONFIG Y UTILIDADES ============
APP_NAME = "TinyTune"
EXTENSIONS = {".mp3", ".ogg", ".wav", ".flac", ".opus", ".mod", ".mid", ".midi"}

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_music_folder() -> Path:
    docs = Path.home() / "Documents"
    if not docs.exists():
        alt = Path.home() / "Documentos"
        if alt.exists(): docs = alt
    folder = docs / "TinyTune Music"
    folder.mkdir(parents=True, exist_ok=True)
    return folder

MUSIC_FOLDER = get_music_folder()

def format_time(seconds):
    if seconds < 0 or seconds is None: return "0:00"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"

def make_tray_icon(playing: bool, size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (30, 215, 96, 255) if playing else (100, 100, 100, 255)
    d.ellipse((2, 2, size - 2, size - 2), fill=bg)
    cx, cy = size // 2, size // 2
    d.ellipse((cx - 14, cy + 6, cx - 2, cy + 18), fill=(0, 0, 0))
    d.ellipse((cx + 4, cy - 2, cx + 16, cy + 10), fill=(0, 0, 0))
    d.rectangle((cx - 4, cy - 18, cx - 1, cy + 12), fill=(0, 0, 0))
    d.rectangle((cx + 14, cy - 26, cx + 17, cy + 4), fill=(0, 0, 0))
    d.rectangle((cx - 4, cy - 18, cx + 17, cy - 14), fill=(0, 0, 0))
    return img

# ============ LÓGICA DEL REPRODUCTOR ============
class Player:
    def __init__(self):
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        self.tracks = []
        self.index = 0
        self.playing = False
        self.paused = False
        self._volume = 0.8
        self.modes = ['seq', 'loop', 'random']
        self.current_mode = 0
        self.duration = 0
        self.offset = 0.0
        self.lock = threading.RLock() 
        pygame.mixer.music.set_volume(self._volume)
        self.load_playlist()

    def load_playlist(self):
        with self.lock:
            self.tracks = sorted([p for p in MUSIC_FOLDER.rglob("*") if p.suffix.lower() in EXTENSIONS])

    def current(self):
        with self.lock:
            return self.tracks[self.index] if self.tracks else None

    def get_duration(self, filepath):
        try:
            audio = mutagen.File(filepath)
            return audio.info.length if audio else 0
        except:
            return 0

    def play(self):
        with self.lock:
            if not self.tracks: return
            track = self.current()
            if not track: return
            try:
                pygame.mixer.music.load(str(track))
                pygame.mixer.music.play()
                self.duration = self.get_duration(track)
                self.playing = True
                self.paused = False
                self.offset = 0.0
            except Exception as e:
                print(f"Error: {e}")

    def play_index(self, idx):
        with self.lock:
            if 0 <= idx < len(self.tracks):
                self.index = idx
                self.stop()
                self.play()

    def pause(self):
        with self.lock:
            if self.playing and not self.paused:
                pygame.mixer.music.pause()
                self.paused = True
            elif self.paused:
                pygame.mixer.music.unpause()
                self.paused = False

    def stop(self):
        with self.lock:
            pygame.mixer.music.stop()
            self.playing = False
            self.paused = False
            self.offset = 0.0

    def next(self, auto=False):
        with self.lock:
            if not self.tracks: return
            if auto and self.modes[self.current_mode] == 'loop':
                self.stop()
                self.play()
                return
            if self.modes[self.current_mode] == 'random':
                self.index = random.randint(0, len(self.tracks) - 1)
            else:
                self.index = (self.index + 1) % len(self.tracks)
            self.stop()
            self.play()

    def prev(self):
        with self.lock:
            if not self.tracks: return
            self.index = (self.index - 1) % len(self.tracks)
            self.stop()
            self.play()

    def change_mode(self):
        with self.lock:
            self.current_mode = (self.current_mode + 1) % len(self.modes)
            return self.modes[self.current_mode]

    def set_volume(self, vol):
        with self.lock:
            self._volume = float(vol)
            pygame.mixer.music.set_volume(self._volume)

    def seek(self, pos_sec):
        with self.lock:
            track = self.current()
            if not track or self.duration <= 0: return
            pos_sec = min(float(pos_sec), self.duration - 1)
            was_paused = self.paused
            try:
                self.offset = pos_sec
                pygame.mixer.music.load(str(track))
                pygame.mixer.music.play(start=pos_sec)
                self.playing = True
                self.paused = False
                if was_paused:
                    pygame.mixer.music.pause()
                    self.paused = True
            except:
                pass

    def get_pos(self):
        with self.lock:
            if not self.playing: return self.offset
            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms < 0: return self.offset
            return self.offset + (pos_ms / 1000.0)

# ============ INTERFAZ GRÁFICA ============
class MiniPlayer(ctk.CTk):
    def __init__(self, player, app):
        super().__init__()
        self.player = player
        self.app = app
        self.is_seeking = False
        self.playlist_visible = False
        self.last_state = None
        self.playlist_buttons = []
        
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#121212")
        
        self.win_w = 340
        self.win_h_collapsed = 160
        self.win_h_expanded = 400
        self.height_diff = self.win_h_expanded - self.win_h_collapsed # 240px
        
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        
        # Posición inicial (abajo a la derecha)
        self.geometry(f"{self.win_w}x{self.win_h_collapsed}+{screen_w - self.win_w - 20}+{screen_h - 220}")
        
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            try: self.iconbitmap(icon_path)
            except: pass

        # Header
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=40)
        self.header.pack(fill="x", padx=10, pady=(5, 0))
        self.lbl_title = ctk.CTkLabel(self.header, text="Sin pistas", font=("Segoe UI", 13, "bold"), text_color="#FFFFFF", anchor="w")
        self.lbl_title.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(self.header, text="✕", width=25, height=25, fg_color="transparent", hover_color="#333333", text_color="#B3B3B3", command=self.hide).pack(side="right")

        self.lbl_artist = ctk.CTkLabel(self, text="Detenido", font=("Segoe UI", 10), text_color="#B3B3B3", anchor="w")
        self.lbl_artist.pack(fill="x", padx=10)

        # Barra de Progreso
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=10, pady=(5, 0))
        self.lbl_time_curr = ctk.CTkLabel(self.progress_frame, text="0:00", font=("Segoe UI", 9), text_color="#B3B3B3", width=30)
        self.lbl_time_curr.pack(side="left")
        
        self.progress_slider = ctk.CTkSlider(self.progress_frame, from_=0, to=100, progress_color="#1DB954", button_color="#FFFFFF", button_hover_color="#1DB954", command=self.on_seek_drag)
        self.progress_slider.pack(side="left", fill="x", expand=True, padx=5)
        self.progress_slider.bind("<ButtonPress-1>", self.on_seek_start)
        self.progress_slider.bind("<ButtonRelease-1>", self.on_seek_release)
        
        self.lbl_time_total = ctk.CTkLabel(self.progress_frame, text="0:00", font=("Segoe UI", 9), text_color="#B3B3B3", width=30)
        self.lbl_time_total.pack(side="right")

        # Controles
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(pady=5)
        self.btn_mode = ctk.CTkButton(controls, text="🔁", width=30, height=30, fg_color="transparent", hover_color="#333333", text_color="#B3B3B3", command=self.toggle_mode)
        self.btn_mode.pack(side="left", padx=5)
        ctk.CTkButton(controls, text="⏮", width=30, height=30, fg_color="transparent", hover_color="#333333", text_color="#FFFFFF", command=self.prev).pack(side="left", padx=5)
        self.btn_play = ctk.CTkButton(controls, text="▶", width=40, height=40, corner_radius=20, fg_color="#FFFFFF", hover_color="#E0E0E0", text_color="#000000", font=("Segoe UI", 16), command=self.toggle_play)
        self.btn_play.pack(side="left", padx=10)
        ctk.CTkButton(controls, text="⏭", width=30, height=30, fg_color="transparent", hover_color="#333333", text_color="#FFFFFF", command=self.next).pack(side="left", padx=5)
        self.btn_list = ctk.CTkButton(controls, text="📋", width=30, height=30, fg_color="transparent", hover_color="#333333", text_color="#B3B3B3", command=self.toggle_playlist)
        self.btn_list.pack(side="left", padx=5)

        # Volumen
        vol_frame = ctk.CTkFrame(self, fg_color="transparent")
        vol_frame.pack(fill="x", padx=15, pady=(0, 10))
        ctk.CTkLabel(vol_frame, text="🔊", font=("Segoe UI", 12), text_color="#B3B3B3").pack(side="left")
        self.vol_slider = ctk.CTkSlider(vol_frame, from_=0, to=1, progress_color="#1DB954", button_color="#FFFFFF", button_hover_color="#1DB954", command=self.on_volume)
        self.vol_slider.set(self.player._volume)
        self.vol_slider.pack(side="left", fill="x", expand=True, padx=10)

        # Playlist
        self.playlist_frame = ctk.CTkScrollableFrame(self, fg_color="#181818", corner_radius=10)
        
        for widget in [self.header, self.lbl_title, self.lbl_artist]:
            widget.bind("<Button-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
        
        self.withdraw()
        self.update_ui_loop()
        self.update_progress_loop()

    def start_move(self, event):
        self.x, self.y = event.x, event.y
    def do_move(self, event):
        self.geometry(f"+{self.winfo_x() + (event.x - self.x)}+{self.winfo_y() + (event.y - self.y)}")

    def toggle_play(self):
        if self.player.playing and not self.player.paused: self.player.pause()
        else: self.player.play()
        self.update_ui()

    def next(self):
        self.player.next()
        self.update_ui()

    def prev(self):
        self.player.prev()
        self.update_ui()

    def toggle_mode(self):
        mode = self.player.change_mode()
        if mode == 'seq': self.btn_mode.configure(text="🔁", text_color="#B3B3B3")
        elif mode == 'loop': self.btn_mode.configure(text="🔂", text_color="#1DB954")
        elif mode == 'random': self.btn_mode.configure(text="🔀", text_color="#1DB954")

    def toggle_playlist(self):
        curr_x = self.winfo_x()
        curr_y = self.winfo_y()

        if self.playlist_visible:
            # Ocultar lista y bajar la ventana
            self.playlist_frame.pack_forget()
            new_y = curr_y + self.height_diff
            # Evitar que se vaya más abajo del límite de la pantalla
            if new_y + self.win_h_collapsed > self.winfo_screenheight() - 40:
                new_y = self.winfo_screenheight() - 40 - self.win_h_collapsed
            self.geometry(f"{self.win_w}x{self.win_h_collapsed}+{curr_x}+{new_y}")
            self.playlist_visible = False
        else:
            # Mostrar lista y subir la ventana para que no se tape
            self.refresh_playlist()
            self.playlist_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            new_y = curr_y - self.height_diff
            # Evitar que se salga por arriba de la pantalla
            if new_y < 0:
                new_y = 0
            self.geometry(f"{self.win_w}x{self.win_h_expanded}+{curr_x}+{new_y}")
            self.playlist_visible = True

    def refresh_playlist(self):
        if len(self.playlist_buttons) != len(self.player.tracks):
            for btn in self.playlist_buttons: btn.destroy()
            self.playlist_buttons.clear()
            for i, track in enumerate(self.player.tracks):
                btn = ctk.CTkButton(self.playlist_frame, text=track.name, anchor="w", fg_color="transparent", hover_color="#282828", command=lambda idx=i: self.play_from_list(idx))
                btn.pack(fill="x", pady=2)
                self.playlist_buttons.append(btn)
        self.update_playlist_colors()

    def update_playlist_colors(self):
        for i, btn in enumerate(self.playlist_buttons):
            if i == self.player.index:
                btn.configure(text_color="#1DB954")
            else:
                btn.configure(text_color="#FFFFFF")

    def play_from_list(self, idx):
        self.player.play_index(idx)
        self.update_ui()
        if self.playlist_visible: self.update_playlist_colors()

    def on_volume(self, val):
        self.player.set_volume(val)

    def on_seek_start(self, event):
        self.is_seeking = True

    def on_seek_drag(self, val):
        if self.is_seeking:
            self.lbl_time_curr.configure(text=format_time(val))

    def on_seek_release(self, event):
        if self.is_seeking:
            self.is_seeking = False
            self.player.seek(self.progress_slider.get())

    def show(self):
        self.deiconify()
        self.update_ui()

    def hide(self):
        self.withdraw()

    def update_ui(self):
        track = self.player.current()
        if track:
            self.lbl_title.configure(text=track.name[:30] + "..." if len(track.name) > 30 else track.name)
            self.lbl_time_total.configure(text=format_time(self.player.duration))
        else:
            self.lbl_title.configure(text="Sin pistas")
            
        if self.player.paused:
            self.lbl_artist.configure(text="Pausado")
            self.btn_play.configure(text="▶")
        elif self.player.playing:
            self.lbl_artist.configure(text="Reproduciendo")
            self.btn_play.configure(text="⏸")
        else:
            self.lbl_artist.configure(text="Detenido")
            self.btn_play.configure(text="▶")

    def update_ui_loop(self):
        state = (self.player.index, self.player.playing, self.player.paused)
        if self.last_state != state:
            self.update_ui()
            if self.playlist_visible:
                self.update_playlist_colors()
            self.last_state = state
        self.after(500, self.update_ui_loop)

    def update_progress_loop(self):
        if self.player.playing and not self.player.paused and not self.is_seeking:
            pos = self.player.get_pos()
            if self.player.duration > 0:
                self.progress_slider.configure(to=self.player.duration)
                self.progress_slider.set(pos)
                self.lbl_time_curr.configure(text=format_time(pos))
        self.after(250, self.update_progress_loop)

# ============ APP PRINCIPAL ============
class TinyTuneApp:
    def __init__(self):
        self.player = Player()
        self._icon = None
        self._running = True
        self.root = MiniPlayer(self.player, self)
        threading.Thread(target=self._monitor_playback, daemon=True).start()

    def _refresh_tray_icon(self):
        if not self._icon: return
        track = self.player.current()
        state = "⏸" if self.player.paused else ("▶" if self.player.playing else "⏹")
        self._icon.title = f"{state} {track.name if track else 'Sin pistas'} — {APP_NAME}"
        self._icon.icon = make_tray_icon(self.player.playing and not self.player.paused)

    def _monitor_playback(self):
        while self._running:
            if self.player.playing and not self.player.paused:
                if not pygame.mixer.music.get_busy():
                    self.player.next(auto=True)
                    self._refresh_tray_icon()
            time.sleep(0.5)

    def _open_folder(self):
        os.startfile(str(MUSIC_FOLDER)) if sys.platform == "win32" else os.system(f'xdg-open "{MUSIC_FOLDER}"')

    def _do_reload_ui(self):
        self.root.playlist_buttons.clear()
        if self.root.playlist_visible:
            self.root.refresh_playlist()

    def _reload(self):
        self.player.stop()
        self.player.load_playlist()
        self.player.index = 0
        self.player.play()
        self._refresh_tray_icon()
        self.root.after(0, self._do_reload_ui)

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("🎵 Mostrar Reproductor", lambda: self.root.after(0, self.root.show), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("▶ Reproducir", lambda: (self.player.play(), self._refresh_tray_icon())),
            pystray.MenuItem("⏸ Pausar", lambda: (self.player.pause(), self._refresh_tray_icon())),
            pystray.MenuItem("⏭ Siguiente", lambda: (self.player.next(), self._refresh_tray_icon())),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("📂 Abrir carpeta", lambda: self._open_folder()),
            pystray.MenuItem("🔄 Recargar lista", lambda: self._reload()),
            pystray.MenuItem("❌ Salir", self._quit),
        )

    def _quit(self, icon=None, item=None):
        self._running = False
        self.player.stop()
        if self._icon: self._icon.stop()
        pygame.mixer.quit()
        self.root.after(0, self.root.quit)

    def _run_tray(self):
        self._icon = pystray.Icon(APP_NAME, icon=make_tray_icon(True), title=APP_NAME, menu=self._build_menu())
        self._refresh_tray_icon()
        self._icon.run()

    def run(self):
        self.player.play()
        threading.Thread(target=self._run_tray, daemon=True).start()
        self.root.mainloop()

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    if not pygame.mixer.get_init():
        try: TinyTuneApp().run()
        except KeyboardInterrupt: pygame.mixer.quit()
    else: TinyTuneApp().run()