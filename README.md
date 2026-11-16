# 🎵 TinyTune - El reproductor de audio definitivo ultraligero

![TinyTune Banner](https://img.shields.io/badge/TinyTune-Audio_Player-1DB954?style=for-the-badge&logo=spotify&logoColor=white)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=for-the-badge&logo=windows&logoColor=white)

**TinyTune** es un reproductor de música local que redefine lo que significa ser "ligero". Olvídate de aplicaciones pesadas que consumen gigabytes de RAM o de tener que abrir el navegador solo para escuchar tus MP3. 

Inspirado en la estética premium de Spotify, TinyTune vive oculto en tu bandeja del sistema (junto al reloj de Windows) y despliega un mini-reproductor flotante, moderno y elegante cuando lo necesitas. 

---

## ⚡ El secreto: Un consumo ridículamente bajo
Mientras que Spotify o YouTube Music pueden consumir entre **300 MB y 1 GB de RAM**, TinyTune está construido sobre Python y librerías nativas optimizadas. 
* **Consumo de RAM:** Apenas **20 - 30 MB**.
* **Consumo de CPU:** Casi inapreciable cuando está en segundo plano.
* **Arranque:** Instantáneo. Sin pantallas de carga, sin anuncios, sin necesidad de internet.

---

## ✨ Características (Una navaja suiza musical)

* 🎨 **Interfaz estilo Spotify:** Modo oscuro (`#121212`), acentos en verde neón (`#1DB954`), botones redondeados y transiciones fluidas gracias a `CustomTkinter`.
* 🪟 **Mini-Reproductor Flotante:** Sin bordes, siempre visible sobre otras ventanas (Topmost) y arrastrable a cualquier parte de tu pantalla.
* 📂 **Gestión de Carpeta Automática:** Al iniciar por primera vez, crea automáticamente la carpeta `Documents/TinyTune Music`.
* 📋 **Lista de Reproducción Integrada:** Visualiza todas tus canciones sin salir de la app. Haz clic en cualquiera para reproducirla al instante.
* 🎧 **Soporte Multi-formato:** Reproduce `.mp3`, `.ogg`, `.wav`, `.flac`, `.opus`, `.mod`, `.mid` y `.midi`.
* ⏱️ **Barra de Progreso Real:** Gracias a la librería `mutagen`, el reproductor lee la duración exacta de la pista. Puedes adelantar o retroceder arrastrando el control (Seek).
* 🔊 **Control de Volumen Visual:** Deslizador dedicado para ajustar el volumen de 0% a 100%.
* 🔀 **3 Modos de Reproducción:**
  * 🔁 **Secuencial:** Reproduce toda la carpeta en orden.
  * 🔂 **Bucle (Repetir 1):** Reproduce la misma canción indefinidamente.
  * 🔀 **Aleatorio:** Salta a cualquier canción al azar.
* 🛡️ **Multihilo (Thread-Safe):** El motor de audio, la bandeja del sistema y la interfaz gráfica corren en hilos separados. Cero bloqueos, cero lag.
* 🖱️ **Bandeja del Sistema (System Tray):** Controla la reproducción (Play, Pause, Next) directamente desde el icono de la bandeja con un clic derecho.
* 🖼️ **Icono Personalizado:** Soporta un archivo `icon.ico` propio tanto para el ejecutable como para la ventana.

---

## 📁 ¿Dónde pongo mi música?

Por defecto, TinyTune escanea la carpeta: 
`C:\Users\TuUsuario\Documents\TinyTune Music` (o `Documentos` en español).

Puedes crear subcarpetas dentro (por ejemplo, `Rock`, `Pop`, `Juegos`) y el reproductor encontrará todos los archivos de audio válidos de forma recursiva. 
*Si agregas música nueva mientras la app está abierta, haz clic derecho en el icono de la bandeja y selecciona **"🔄 Recargar lista"**.*

---

## 🚀 Instalación y Uso

### Opción 1: Usar el Ejecutable (Recomendado)
Si ya tienes el archivo `TinyTune.exe`:
1. Haz doble clic para abrirlo (no verás ventana, se irá directo a la bandeja del sistema).
2. **Clic izquierdo** en el icono de la nota musical para abrir el mini-reproductor.
3. Asegúrate de tener canciones en tu carpeta de documentos.
4. *Tip:* Puedes crear un acceso directo en `shell:startup` para que se abra automáticamente con Windows.

### Opción 2: Ejecutar desde el código fuente
Si tienes Python instalado, clona el repositorio y ejecuta:

```bash
pip install -r requirements.txt
python tinytune.py
