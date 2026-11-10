"""Avisa a Windows de la canción que suena (título, artista, álbum, portada y si está sonando o en pausa), igual que
Spotify o el navegador. Con eso la muestran el panel multimedia de Windows, la pantalla de bloqueo, Wallpaper Engine,
Rainmeter, etc., y funcionan las teclas multimedia del teclado. Usa los «controles multimedia del sistema» (SMTC).
Todo va en un hilo aparte; si en esta PC no está disponible, simplemente no hace nada."""
import sys
import queue
import threading
from PyQt6.QtCore import QObject, pyqtSignal


class MediaSession(QObject):
    pressed = pyqtSignal(str)   # "play", "pause", "next", "prev", "stop" (pulsado en Windows o en el teclado)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.q = queue.Queue()
        self.ok = None          # None: arrancando · True: funcionando · False: no disponible
        self.error = ""
        self.th = None
        if sys.platform == "win32":
            self.th = threading.Thread(target=self.run, name="smtc", daemon=True)
            self.th.start()
        else:
            self.ok = False

    # ---- lo que llama el programa (desde la ventana)
    def set_track(self, title, artist, album, cover):
        self.q.put(("meta", (title or "", artist or "", album or "", cover or b"")))

    def set_state(self, state):   # "playing" | "paused" | "stopped"
        self.q.put(("state", state))

    def close(self):
        self.q.put(None)

    # ---- hilo propio
    def run(self):
        try:
            import asyncio
            from winrt.windows.media.playback import MediaPlayer
            from winrt.windows.media import (MediaPlaybackType, MediaPlaybackStatus,
                                             SystemMediaTransportControlsButton as B)
            from winrt.windows.storage.streams import InMemoryRandomAccessStream, DataWriter, RandomAccessStreamReference
            mp = MediaPlayer()
            mp.command_manager.is_enabled = False
            smtc = mp.system_media_transport_controls
            smtc.is_enabled = True
            smtc.is_play_enabled = smtc.is_pause_enabled = True
            smtc.is_next_enabled = smtc.is_previous_enabled = True
            smtc.is_stop_enabled = True
            names = {B.PLAY: "play", B.PAUSE: "pause", B.NEXT: "next", B.PREVIOUS: "prev", B.STOP: "stop"}

            def on_button(_sender, args):
                nm = names.get(args.button)
                if nm:
                    self.pressed.emit(nm)
            smtc.add_button_pressed(on_button)
            status = {"playing": MediaPlaybackStatus.PLAYING, "paused": MediaPlaybackStatus.PAUSED,
                      "stopped": MediaPlaybackStatus.STOPPED}

            async def to_stream(data):
                stream = InMemoryRandomAccessStream()
                w = DataWriter(stream)
                w.write_bytes(data)
                await w.store_async()
                await w.flush_async()
                w.detach_stream()
                stream.seek(0)
                return stream
            self.ok = True
        except Exception as e:
            self.ok, self.error = False, f"{type(e).__name__}: {e}"
            return
        keep = None
        while True:
            item = self.q.get()
            if item is None:
                break
            try:
                kind, data = item
                if kind == "state":
                    smtc.playback_status = status.get(data, MediaPlaybackStatus.STOPPED)
                else:
                    while not self.q.empty():   # si llegaron varias canciones seguidas, solo importa la última
                        nxt = self.q.queue[0]
                        if nxt is None or nxt[0] != "meta":
                            break
                        data = self.q.get()[1]
                    title, artist, album, cover = data
                    upd = smtc.display_updater
                    upd.type = MediaPlaybackType.MUSIC
                    props = upd.music_properties
                    props.title, props.artist, props.album_title = title, artist, album
                    props.album_artist = artist
                    if cover:
                        try:
                            keep = asyncio.run(to_stream(cover))
                            upd.thumbnail = RandomAccessStreamReference.create_from_stream(keep)
                        except Exception as e:
                            self.error = f"portada: {type(e).__name__}: {e}"
                            upd.thumbnail = None
                    else:
                        upd.thumbnail = None
                    upd.update()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
        try:
            smtc.is_enabled = False
            mp.close()
        except Exception:
            pass
