# ✨ Genshin Wishes Linux

Herramienta en Python (sin dependencias externas) para extraer la URL autenticada de deseos (Gacha) de **Genshin Impact en Linux** y descargar el historial completo de tiradas directamente desde la API oficial de HoYoverse.

Compatible con instalaciones nativas y Flatpak de **Twintail Launcher**, **An Anime Game Launcher**, **Sleepy Launcher**, Lutris, Heroic o cualquier prefijo de Wine/Proton.

---

## 🚀 Características

- **Detección automática en Linux**: Localiza automáticamente el archivo binario `webCaches/*/Cache/Cache_Data/data_2` en las rutas nativas y Flatpak de *Twintail Launcher* (incluyendo lectura de su base de datos SQLite `storage.db`), *An Anime Game Launcher* y *Sleepy Launcher* (incluyendo lectura de `config.json` para instalaciones en otros discos).
- **Lectura segura en caliente**: Copia el archivo `data_2` a un directorio temporal antes de analizarlo, evitando bloqueos de archivos mientras el juego está abierto.
- **Validación de sesión (`authkey`)**: Extrae todas las URLs del caché ordenadas desde la más reciente y verifica contra la API de HoYoverse cuál sigue activa.
- **Copia automática al portapapeles**: Si tienes `wl-copy` (Wayland), `xclip` o `xsel` (X11), copia la URL válida directamente al portapapeles para pegarla en sitios como [Paimon.moe](https://paimon.moe).
- **Resumen de Pity en terminal**: Calcula tu **pity actual de 5★ y 4★** en los 5 tipos de banner y muestra la lista histórica de todos tus 5★ obtenidos junto al número exacto de tirada.
- **Exportación estándar (UIGF v3.0 & CSV)**:
  - Exporta a `.json` bajo el estándar **UIGF v3.0** (*Uniformed Interchangeable GachaLog Format*), importable en *Paimon.moe*, *Genshin Optimizer*, etc.
  - Exporta a `.csv` listo para abrir en LibreOffice Calc, Excel o Google Sheets.
- **Cero dependencias (`stdlib` pura)**: Solo requiere `python3` (>= 3.8).

---

## 📋 Requisitos

- **Python 3.8+** (preinstalado en prácticamente cualquier distribución de Linux).
- *(Opcional)* `wl-clipboard` (Wayland) o `xclip` / `xsel` (X11) para copiar la URL automáticamente al portapapeles.

---

## 🛠️ Instalación

Puedes clonar el repositorio e instalarlo con `pipx` / `pip`, o ejecutar el script directamente:

```bash
git clone https://github.com/frarojas/genshin-wishes-linux.git
cd genshin-wishes-linux
chmod +x genshin_wishes.py
```

También puedes instalarlo como comando global en tu usuario:

```bash
pip install --user .
# Ahora puedes ejecutar `genshin-wishes` desde cualquier carpeta
```

---

## 📖 Uso

1. Abre **Genshin Impact**.
2. Abre el menú de **Gachapón (Deseos)** y haz clic en el botón **Historial** en la parte inferior.
3. Espera a que cargue la primera página del historial.
4. Ejecuta el script:

### 1. Descargar todo el historial, ver resumen de Pity y exportar a JSON/CSV
```bash
./genshin_wishes.py
```

### 2. Obtener únicamente la URL (para pegarla en Paimon.moe)
```bash
./genshin_wishes.py --url-only
```

### 3. Especificar una ruta manual (si tienes el juego en otro disco o partición)
```bash
./genshin_wishes.py --path "/mnt/juegos/Genshin Impact/GenshinImpact_Data"
```

### 4. Opciones disponibles
```text
usage: genshin_wishes.py [-h] [--path PATH] [--url-only] [--lang LANG] [--output OUTPUT]

Extrae la URL y descarga el historial de deseos de Genshin Impact en Linux.

options:
  -h, --help            Muestra este mensaje de ayuda y sale
  --path, -p PATH       Ruta personalizada a la carpeta del juego (GenshinImpact_Data)
                        o directamente al archivo data_2
  --url-only, -u        Solo extraer y mostrar la URL (para pegarla en paimon.moe)
                        sin descargar los deseos
  --lang, -l LANG       Idioma para la API de HoYoverse (por defecto: es-es, ej: en-us)
  --output, -o OUTPUT   Directorio donde guardar los archivos JSON y CSV
                        (por defecto: carpeta actual)
```

---

## 📄 Licencia

Distribuido bajo la licencia [MIT](LICENSE).
