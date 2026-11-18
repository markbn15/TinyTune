# 🎵 TinyTune - El reproductor de audio definitivo ultraligero

![TinyTune Banner](https://img.shields.io/badge/TinyTune-Audio_Player-1DB954?style=for-the-badge&logo=spotify&logoColor=white)
![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?style=for-the-badge&logo=windows&logoColor=white)

**TinyTune** es un reproductor de música local que redefine lo que significa ser "ligero". Olvídate de aplicaciones pesadas que consumen gigabytes de RAM o de tener que abrir el navegador solo para escuchar tus MP3. 

Inspirado en la estética premium de Spotify, TinyTune vive oculto en tu bandeja del sistema (junto al reloj de Windows) y despliega un mini-reproductor flotante, moderno y elegante cuando lo necesitas. 

---

## ⚡ El secreto: Un consumo ridículamente bajo
Mientras que Spotify o YouTube Music pueden consumir entre **300 MB y 1 GB de RAM**, TinyTune está construido sobre Python y librerías nativas optimizadas. 
* **Consumo de RAM:** Menos de **50 MB** (incluso con la búsqueda de carátulas en línea activa).
* **Consumo de CPU:** Casi inapreciable cuando está en segundo plano.
* **Arranque:** Instantáneo. Sin pantallas de carga, sin anuncios, sin necesidad de internet.

---

## ✨ Características (Una navaja suiza musical)

* 🎨 **Interfaz estilo Spotify:** Modo oscuro (`#111214`), acentos en verde neón (`#1DB954`), botones redondeados y transiciones fluidas gracias a `CustomTkinter`.
* 🪟 **Mini-Reproductor Flotante:** Sin bordes, siempre visible sobre otras ventanas (Topmost) y arrastrable a cualquier parte de tu pantalla.
* 📂 **Gestión de Carpeta Automática:** Al iniciar por primera vez, crea automáticamente la carpeta `Documents/TinyTune Music`.
* 📋 **Lista de Reproducción Integrada con Buscador:** Visualiza todas tus canciones sin salir de la app. Filtra por título, artista o álbum y haz clic en cualquiera para reproducirla al instante.
* 🖼️ **Carátulas Reales:** Lee la portada embebida en el archivo (`APIC`, `covr`, FLAC, etc.). Si no existe, TinyTune puede buscarla en internet (Deezer, iTunes y YouTube) y cachearla localmente. Totalmente opcional y configurable.
* 🎧 **Soporte Multi-formato:** Reproduce `.mp3`, `.ogg`, `.wav`, `.flac`, `.opus`, `.aiff`, `.aif`, `.mod`, `.xm`, `.it`, `.s3m`, `.mid` y `.midi`.
* ⏱️ **Barra de Progreso Real:** Gracias a la librería `mutagen`, el reproductor lee la duración exacta de la pista. Puedes adelantar o retroceder arrastrando el control (Seek).
* 🔊 **Control de Volumen y Silencio:** Deslizador dedicado para ajustar el volumen de 0% a 100% y botón de mute rápido.
* 🔀 **4 Modos de Reproducción:**
  * 🔁 **Secuencial:** Reproduce toda la carpeta en orden.
  * 🔂 **Repetir Todo:** Al terminar la última pista, vuelve a empezar.
  * 🔂 **Repetir Pista:** Reproduce la misma canción indefinidamente.
  * 🔀 **Aleatorio:** Salta a cualquier canción al azar.
* 🎹 **Atajos Multimedia de Windows:** Controla la reproducción desde los botones multimedia del teclado (Play/Pausa, Siguiente, Anterior, Detener).
* ⌨️ **Atajos de Teclado:**
  * `Espacio` → Play / Pausa
  * `←` / `→` → Retroceder / Avanzar 5 segundos
  * `↑` / `↓` → Subir / Bajar volumen
  * `N` / `P` → Siguiente / Anterior
  * `M` → Silenciar
  * `L` → Mostrar / Ocultar lista
  * `Ctrl + F` → Buscar en la biblioteca
  * `Ctrl + Q` → Salir
  * `Esc` → Ocultar ventana
* 🛡️ **Multihilo (Thread-Safe):** El motor de audio, la bandeja del sistema, la búsqueda de carátulas y la interfaz gráfica corren en hilos separados. Cero bloqueos, cero lag.
* 🖱️ **Bandeja del Sistema (System Tray):** Controla la reproducción (Play, Pausa, Next, Previous, Mute) directamente desde el icono de la bandeja con un clic derecho. También incluye opciones para recargar la biblioteca, cambiar de carpeta, abrir ajustes y salir.
* 🖼️ **Icono Personalizado:** Soporta un archivo `icon.ico` propio tanto para el ejecutable como para la ventana.
* 🔒 **Instancia Única:** Si intentas abrir TinyTune dos veces, la segunda ejecución solo muestra la ventana existente en lugar de crear un duplicado.
* 💾 **Preferencias Persistentes:** Posición de la ventana, volumen, modo de reproducción, última pista escuchada y estado de la lista se guardan automáticamente en `%APPDATA%\TinyTune`.
* 🚀 **Inicio con Windows (Opcional):** Actívalo desde Ajustes para que TinyTune arranque minimizado junto al sistema.
* ⚙️ **Panel de Ajustes:** Activa/desactiva carátulas en línea, inicio automático, restablece la posición de la ventana y vacía la caché de portadas.

---

## 📁 ¿Dónde pongo mi música?

Por defecto, TinyTune escanea la carpeta: 
`C:\Users\TuUsuario\Documents\TinyTune Music` (o `Documentos` en español).

Puedes crear subcarpetas dentro (por ejemplo, `Rock`, `Pop`, `Juegos`) y el reproductor encontrará todos los archivos de audio válidos de forma recursiva. Además, si el archivo no tiene etiqueta de artista, TinyTune usará el nombre de la subcarpeta como artista.
*Si agregas música nueva mientras la app está abierta, haz clic derecho en el icono de la bandeja y selecciona **"🔄 Recargar biblioteca"**, o simplemente cierra y vuelve a abrir la app.*

---

## 🚀 Instalación y Uso

### Opción 1: Usar el Ejecutable (Recomendado)
Si ya tienes el archivo `TinyTune.exe`:
1. Haz doble clic para abrirlo (no verás ventana, se irá directo a la bandeja del sistema).
2. **Clic izquierdo** en el icono de la nota musical para abrir el mini-reproductor.
3. Asegúrate de tener canciones en tu carpeta de documentos.
4. *Tip:* Activa **"Iniciar con Windows"** desde Ajustes ⚙️ para que se abra automáticamente al encender el equipo.

### Opción 2: Ejecutar desde el código fuente
Si tienes Python instalado, clona el repositorio y ejecuta:

```bash
pip install -r requirements.txt
python tinytune.py
```
## 🆕 Novedades de esta versión (3.2.0)

- ✨ **Búsqueda de carátulas en línea** (Deezer, iTunes y YouTube) totalmente opcional.
- 🎨 **Nueva UI rediseñada:** lista de reproducción colapsable, header más compacto y controles reorganizados.
- 🔍 **Buscador integrado** en la lista de reproducción.
- 🎹 **Atajos multimedia de Windows** y atajos de teclado completos.
- 🔒 **Instancia única** — no más ventanas duplicadas.
- 🚀 **Inicio con Windows** configurable desde Ajustes.
- 💾 **Persistencia de preferencias** (posición, volumen, modo, última pista).
- ⚙️ **Panel de Ajustes** completo con opciones de caché y portadas.
- 🎧 **Más formatos soportados:** AIFF, XM, IT, S3M.
- 🖼️ **Caché de carátulas** con limpieza automática (máx. 400 imágenes).
- 🎵 **Limpieza inteligente de metadatos:** elimina prefijos numéricos y ruido tipo "(Official Video)", "[Lyrics]", etc.
- 🐛 **Correcciones:** memoria liberada correctamente al cambiar de pista, mejor manejo de errores de audio, y detección de fin de pista más estable.

---

## ⚠️ Notas

- Requiere **Windows** para atajos multimedia, inicio automático y bloqueo de instancia (en otros SO la app funciona pero sin esas funciones).
- La búsqueda de carátulas en línea usa servicios públicos; puede fallar sin conexión o si el servicio cambia su API.
- Configuración, caché y logs en `%APPDATA%\TinyTune`.
- Para desarrollo: los archivos se pueden colocar manualmente en cualquier carpeta y seleccionar con el botón 📁.

---

## ❤️ Créditos

Desarrollado con cariño por [**@markbn115**](https://www.instagram.com/markbn115/?hl=es).

Si te gusta el proyecto, ¡deja una estrella ⭐ en el repo!

(Ayuda demasiado en mi CV)
