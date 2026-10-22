#!/usr/bin/env python3
"""
Extractor de Historial de Deseos (Gacha) de Genshin Impact para Linux.

Busca automáticamente el archivo de caché web (`data_2`) en instalaciones de:
- Twintail Launcher (Nativo, Flatpak y base de datos SQLite storage.db)
- An Anime Game Launcher (Nativo y Flatpak)
- Sleepy Launcher (Nativo y Flatpak)
- Heroic Games Launcher / Lutris
- Rutas personalizadas o búsqueda rápida optimizada en $HOME

Extrae la URL autenticada (authkey), valida la sesión contra la API oficial de
HoYoverse y descarga la lista completa de deseos en formato JSON (incluyendo
compatibilidad con el estándar UIGF) y CSV.
"""

import argparse
import csv
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# Tipos de gachapón en Genshin Impact
BANNER_TYPES = {
    "301": "Promocional de Personaje ( y Promocional 2 )",
    "302": "Promocional de Arma (Encarnación Divina)",
    "200": "Permanente (Pasión por viajar)",
    "100": "Principiante (Deseos de principiante)",
    "500": "Gachapón Recopilatorio (Crónicas)",
}

# Endpoints posibles según versión global (OS) o China (CN)
API_ENDPOINTS = {
    "global": "https://public-operation-hk4e-sg.hoyoverse.com/gacha_info/api/getGachaLog",
    "cn": "https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog",
}

# Expresión regular para capturar URLs del historial en el binario data_2
URL_REGEX = re.compile(
    rb"https://[^\x00\s\"'<>]*?(?:hoyoverse|mihoyo|yuanshen)\.com[^\x00\s\"'<>]*?authkey=[^\x00\s\"'<>]+",
    re.IGNORECASE,
)


def find_data2_files(custom_path: Optional[str] = None) -> List[Path]:
    """
    Busca todos los archivos `data_2` dentro de `webCaches` para Twintail Launcher,
    An Anime Game Launcher, Sleepy Launcher, Heroic, Lutris u otras instalaciones en Linux.
    Retorna la lista ordenada desde el modificado más recientemente al más antiguo.
    """
    home = Path.home()
    candidates: List[Path] = []

    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if p.is_file():
            return [p]
        elif p.is_dir():
            candidates.extend(p.rglob("webCaches/*/Cache/Cache_Data/data_2"))
            if not candidates:
                candidates.extend(p.rglob("data_2"))
            return sorted(set(candidates), key=lambda x: x.stat().st_mtime, reverse=True)

    # 1. Variable de entorno de Twintail Launcher (si está definida)
    twintail_env = os.environ.get("TWINTAIL_GAME_DIR")
    if twintail_env and os.path.isdir(twintail_env):
        candidates.extend(Path(twintail_env).rglob("webCaches/*/Cache/Cache_Data/data_2"))

    # 2. Rutas conocidas de launchers en Linux (Twintail, AAGL, Sleepy, Heroic, Lutris)
    known_base_dirs = [
        # Twintail Launcher (Nativo y Flatpak)
        home / ".local/share/twintaillauncher/games",
        home / ".var/app/app.twintaillauncher.ttl/data/twintaillauncher/games",
        # An Anime Game Launcher (Nativo y Flatpak)
        home / ".local/share/anime-game-launcher",
        home / ".var/app/moe.launcher.an-anime-game-launcher/data/anime-game-launcher",
        # Sleepy Launcher (Nativo y Flatpak)
        home / ".local/share/sleepy-launcher",
        home / ".var/app/moe.launcher.sleepy-launcher/data/sleepy-launcher",
        # Carpetas comunes en $HOME/Games
        home / "Games/anime-game-launcher",
        home / "Games/genshin-impact",
        home / "Games/Genshin Impact",
        home / "Games/Heroic/GenshinImpact",
        home / "Games/Heroic/Genshin Impact",
        home / ".var/app/com.heroicgameslauncher.hgl/Games/Heroic/GenshinImpact",
        home / ".var/app/com.heroicgameslauncher.hgl/Games/Heroic/Genshin Impact",
    ]

    for base in known_base_dirs:
        if base.exists():
            candidates.extend(base.rglob("webCaches/*/Cache/Cache_Data/data_2"))

    # 3. Consultar SQLite `storage.db` de Twintail Launcher (por si instaló el juego en otro disco)
    twintail_dbs = [
        home / ".local/share/twintaillauncher/storage.db",
        home / ".var/app/app.twintaillauncher.ttl/data/twintaillauncher/storage.db",
    ]
    for db_path in twintail_dbs:
        if db_path.is_file():
            try:
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cur = conn.cursor()
                for (inst_dir,) in cur.execute("SELECT directory FROM install").fetchall():
                    if inst_dir and os.path.isdir(inst_dir):
                        candidates.extend(Path(inst_dir).rglob("webCaches/*/Cache/Cache_Data/data_2"))
                for (def_dir,) in cur.execute("SELECT default_game_path FROM settings").fetchall():
                    if def_dir and os.path.isdir(def_dir):
                        candidates.extend(Path(def_dir).rglob("webCaches/*/Cache/Cache_Data/data_2"))
                conn.close()
            except Exception:
                pass

    # 4. Revisar `config.json` de An Anime Game Launcher / Sleepy Launcher (por si apunta a otro disco)
    config_files = [
        home / ".local/share/anime-game-launcher/config.json",
        home / ".var/app/moe.launcher.an-anime-game-launcher/config/anime-game-launcher/config.json",
        home / ".var/app/moe.launcher.an-anime-game-launcher/data/anime-game-launcher/config.json",
        home / ".config/anime-game-launcher/config.json",
        home / ".local/share/sleepy-launcher/config.json",
        home / ".var/app/moe.launcher.sleepy-launcher/config/sleepy-launcher/config.json",
    ]
    for cfg in config_files:
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8", errors="ignore"))
                game_path = (
                    data.get("game", {}).get("path", {}).get("global")
                    or data.get("game", {}).get("path", {}).get("china")
                )
                if isinstance(game_path, str) and os.path.isdir(game_path):
                    candidates.extend(Path(game_path).rglob("webCaches/*/Cache/Cache_Data/data_2"))
            except Exception:
                pass

    # 5. Si no se encontró en las rutas estándar, hacer búsqueda rápida en $HOME excluyendo cachés pesadas
    if not candidates:
        print("[*] No se encontró en las rutas por defecto. Buscando GenshinImpact_Data en $HOME...")
        try:
            proc = subprocess.run(
                [
                    "find",
                    str(home),
                    "-maxdepth",
                    "10",
                    "(",
                    "-name",
                    ".cache",
                    "-o",
                    "-name",
                    "cache",
                    "-o",
                    "-name",
                    "mesa_shader_cache",
                    "-o",
                    "-name",
                    "WebKitCache",
                    "-o",
                    "-name",
                    "compatibility",
                    "-o",
                    "-name",
                    ".git",
                    "-o",
                    "-name",
                    "node_modules",
                    "-o",
                    "-name",
                    ".cargo",
                    "-o",
                    "-name",
                    ".rustup",
                    ")",
                    "-prune",
                    "-o",
                    "(",
                    "-name",
                    "GenshinImpact_Data",
                    "-o",
                    "-name",
                    "YuanShen_Data",
                    ")",
                    "-type",
                    "d",
                    "-print",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            for line in proc.stdout.splitlines():
                d = Path(line.strip())
                if d.is_dir():
                    candidates.extend(d.rglob("webCaches/*/Cache/Cache_Data/data_2"))
        except Exception:
            pass

    # Eliminar duplicados y ordenar por fecha de modificación (el más reciente primero)
    unique_files = list({f.resolve(): f for f in candidates if f.is_file()}.values())
    unique_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return unique_files


def extract_urls_from_data2(data2_path: Path) -> List[str]:
    """
    Copia `data_2` a un archivo temporal (para evitar bloqueos si el juego está abierto)
    y extrae todas las URLs con `authkey`, desde la más reciente hasta la más antigua.
    """
    with tempfile.NamedTemporaryFile(prefix="genshin_data2_", delete=True) as tmp:
        shutil.copy2(data2_path, tmp.name)
        raw_bytes = Path(tmp.name).read_bytes()

    matches = URL_REGEX.findall(raw_bytes)
    urls: List[str] = []
    seen = set()

    # Recorremos en reversa porque las entradas más nuevas suelen escribirse al final
    for raw_match in reversed(matches):
        try:
            url = raw_match.decode("utf-8", errors="ignore")
            # Limpiar basura binaria que pueda quedar pegada al final (ej. \x00 o fragmentos)
            url = url.split("\x00")[0].strip()
            # En el archivo data_2 las URLs a veces vienen precedidas por "1/0/"
            if "https://" in url:
                url = "https://" + url.split("https://")[-1]

            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)

            # Ignorar URLs de encuestas u otros eventos que no sean del historial de gachapón
            if qs.get("auth_appid", [""])[0] != "webview_gacha":
                continue

            if "authkey" in qs:
                authkey = qs["authkey"][0]
                if authkey not in seen:
                    seen.add(authkey)
                    # Limpiar parámetros de paginación (page, size, begin_id, end_id, gacha_type)
                    # que la caché agrega al navegar páginas, ya que begin_id rompe paimon.moe
                    if "game_biz=" in url:
                        base_part, biz_part = url.split("game_biz=", 1)
                        biz_val = biz_part.split("&")[0]
                        url = f"{base_part}game_biz={biz_val}"
                    urls.append(url)
        except Exception:
            continue

    return urls


def build_api_url(raw_url: str, gacha_type: str = "301", page: int = 1, size: int = 20, end_id: str = "0", lang: str = "es-es") -> str:
    """
    Transforma la URL de la página web del historial en la URL directa de la API `getGachaLog`.
    """
    parsed = urllib.parse.urlparse(raw_url)
    qs = urllib.parse.parse_qs(parsed.query)

    # Detectar si es servidor chino o global
    region = qs.get("region", ["os_usa"])[0]
    is_cn = region.startswith("cn_") or "mihoyo.com" in parsed.netloc or "yuanshen.com" in parsed.netloc
    base_endpoint = API_ENDPOINTS["cn"] if is_cn else API_ENDPOINTS["global"]

    # Conservar los parámetros de autenticación necesarios
    keep_keys = [
        "authkey_ver",
        "sign_type",
        "auth_appid",
        "init_type",
        "gacha_id",
        "timestamp",
        "device_type",
        "ext",
        "game_version",
        "plat_type",
        "region",
        "authkey",
        "game_biz",
    ]

    api_params = {}
    for k in keep_keys:
        if k in qs and qs[k]:
            api_params[k] = qs[k][0]

    api_params["lang"] = lang
    api_params["gacha_type"] = gacha_type
    api_params["page"] = str(page)
    api_params["size"] = str(size)
    api_params["end_id"] = str(end_id)

    return f"{base_endpoint}?{urllib.parse.urlencode(api_params)}"


def request_gacha_page(api_url: str) -> dict:
    """Realiza la petición GET a la API de HoYoverse."""
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_valid_url(candidate_urls: List[str], lang: str = "es-es") -> Optional[str]:
    """
    Prueba las URLs encontradas en `data_2` hasta dar con una cuyo `authkey` no haya expirado.
    """
    for idx, url in enumerate(candidate_urls, 1):
        test_api = build_api_url(url, gacha_type="301", page=1, size=5, end_id="0", lang=lang)
        try:
            res = request_gacha_page(test_api)
            retcode = res.get("retcode")
            if retcode == 0:
                return url
            else:
                msg = res.get("message", "Error desconocido")
                print(f"    [-] URL candidata #{idx} expirada o inválida (retcode {retcode}: {msg})")
        except Exception as e:
            print(f"    [-] Error de red al probar URL #{idx}: {e}")
    return None


def fetch_all_wishes(valid_url: str, lang: str = "es-es", delay: float = 0.4) -> Tuple[Optional[str], Dict[str, List[dict]]]:
    """
    Descarga todas las páginas de todos los banners (301, 302, 200, 100, 500).
    Retorna `(uid, wishes_by_banner)`.
    """
    all_wishes: Dict[str, List[dict]] = {}
    uid: Optional[str] = None

    for banner_code, banner_name in BANNER_TYPES.items():
        print(f"\n[*] Consultando banner [{banner_code}]: {banner_name}...")
        banner_list: List[dict] = []
        page = 1
        end_id = "0"

        while True:
            api_url = build_api_url(
                valid_url,
                gacha_type=banner_code,
                page=page,
                size=20,
                end_id=end_id,
                lang=lang,
            )
            try:
                res = request_gacha_page(api_url)
            except Exception as e:
                print(f"  [!] Error en página {page}: {e}. Reintentando en 2s...")
                time.sleep(2)
                continue

            if res.get("retcode") != 0:
                # Si da error de rate-limit (-110), esperar un poco más
                if res.get("retcode") == -110:
                    print("  [!] Demasiadas peticiones, esperando 2 segundos...")
                    time.sleep(2)
                    continue
                print(f"  [!] Respuesta de API inesperada: {res.get('message')} (retcode {res.get('retcode')})")
                break

            items = res.get("data", {}).get("list", [])
            if not items:
                break

            for item in items:
                if not uid and item.get("uid"):
                    uid = item["uid"]
                banner_list.append(item)

            print(f"  -> Página {page}: +{len(items)} deseos (Total acumulado: {len(banner_list)})", end="\r")
            end_id = items[-1]["id"]
            page += 1
            time.sleep(delay)

        # Ordenar cronológicamente (del más antiguo al más reciente por ID)
        banner_list.sort(key=lambda x: int(x.get("id", 0)))
        all_wishes[banner_code] = banner_list
        print(f"  [OK] Total en {banner_name}: {len(banner_list)} deseos.                    ")

    return uid, all_wishes


def compute_pity_and_summary(wishes_by_banner: Dict[str, List[dict]]) -> None:
    """
    Calcula el número de tirada (pity) de cada deseo y muestra un resumen en consola
    (incluyendo el pity actual y los 5★ obtenidos).
    """
    print("\n" + "=" * 65)
    print("                 RESUMEN DE TU HISTORIAL DE DESEOS")
    print("=" * 65)

    for code, name in BANNER_TYPES.items():
        items = wishes_by_banner.get(code, [])
        if not items:
            continue

        pity_5 = 0
        pity_4 = 0
        five_stars = []

        for item in items:
            pity_5 += 1
            pity_4 += 1
            rank = str(item.get("rank_type", "3"))
            item["pity_5"] = pity_5

            if rank == "5":
                five_stars.append((item.get("name"), pity_5, item.get("time")))
                pity_5 = 0
                pity_4 = 0
            elif rank == "4":
                pity_4 = 0

        print(f"\n📌 {name} (Código {code})")
        print(f"   • Total de deseos registrados : {len(items)}")
        print(f"   • Pity 5★ actual              : {pity_5} deseos desde el último 5★")
        print(f"   • Pity 4★ actual              : {pity_4} deseos desde el último 4★")
        if five_stars:
            print(f"   • Historial de 5★ ({len(five_stars)}):")
            for item_name, pull_num, pull_time in five_stars:
                print(f"       ★ {item_name:<28} (Tirada #{pull_num:>2})  [{pull_time}]")
        else:
            print("   • Historial de 5★             : Ninguno en los últimos meses")

    print("\n" + "=" * 65)


def export_results(uid: Optional[str], wishes_by_banner: Dict[str, List[dict]], output_dir: Path, lang: str) -> None:
    """
    Guarda los deseos en archivos JSON (compatible con UIGF v3.0) y CSV.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    uid_str = uid or "unknown_uid"
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Flatten para UIGF y CSV
    flat_list = []
    for code, items in wishes_by_banner.items():
        for item in items:
            entry = dict(item)
            # UIGF requiere uigf_gacha_type (donde 400 se agrupa en 301)
            g_type = str(entry.get("gacha_type", code))
            entry["uigf_gacha_type"] = "301" if g_type == "400" else g_type
            flat_list.append(entry)

    flat_list.sort(key=lambda x: int(x.get("id", 0)))

    # 1. Guardar JSON en formato UIGF (compatible con Paimon.moe, Genshin Optimizer, etc.)
    json_path = output_dir / f"genshin_wishes_{uid_str}_{timestamp_str}.json"
    uigf_payload = {
        "info": {
            "uid": uid_str,
            "lang": lang,
            "export_timestamp": int(time.time()),
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "export_app": "genshin-wishes-linux-py",
            "export_app_version": "1.0.0",
            "uigf_version": "v3.0",
        },
        "list": flat_list,
    }
    json_path.write_text(json.dumps(uigf_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. Guardar CSV legible para Excel / LibreOffice Calc
    csv_path = output_dir / f"genshin_wishes_{uid_str}_{timestamp_str}.csv"
    fieldnames = ["id", "time", "banner_code", "banner_name", "name", "item_type", "rank_type", "pity_5"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for code, items in wishes_by_banner.items():
            b_name = BANNER_TYPES.get(code, code)
            for item in items:
                writer.writerow(
                    {
                        "id": item.get("id", ""),
                        "time": item.get("time", ""),
                        "banner_code": item.get("gacha_type", code),
                        "banner_name": b_name,
                        "name": item.get("name", ""),
                        "item_type": item.get("item_type", ""),
                        "rank_type": item.get("rank_type", ""),
                        "pity_5": item.get("pity_5", ""),
                    }
                )

    print(f"[+] Archivo JSON (UIGF) guardado en : {json_path}")
    print(f"[+] Archivo CSV guardado en         : {csv_path}")


def copy_to_clipboard(text: str) -> bool:
    """Intenta copiar la URL al portapapeles de Linux (Wayland o X11)."""
    commands = [
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ]
    for cmd in commands:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=3)
                return True
            except Exception:
                continue
    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae la URL y descarga el historial de deseos de Genshin Impact en Linux."
    )
    parser.add_argument(
        "--path",
        "-p",
        help="Ruta personalizada a la carpeta del juego (GenshinImpact_Data) o directamente al archivo data_2",
        default=None,
    )
    parser.add_argument(
        "--url-only",
        "-u",
        action="store_true",
        help="Solo extraer y mostrar la URL (para pegarla en paimon.moe) sin descargar los deseos",
    )
    parser.add_argument(
        "--lang",
        "-l",
        default="es-es",
        help="Idioma para la API de HoYoverse (por defecto: es-es, ej: en-us)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=".",
        help="Directorio donde guardar los archivos JSON y CSV (por defecto: carpeta actual)",
    )
    args = parser.parse_args()

    print("=== Extractor de Deseos de Genshin Impact (Linux) ===")
    data2_files = find_data2_files(args.path)

    if not data2_files:
        print("\n[!] No se encontró ningún archivo `data_2` automáticamente.")
        print("    Asegúrate de:")
        print("    1. Haber abierto el 'Historial' de deseos dentro del juego recientemente.")
        print("    2. Si instalaste el juego en otro disco/ruta, pásala con --path:")
        print("       python3 genshin_wishes.py --path '/ruta/a/GenshinImpact_Data'")
        sys.exit(1)

    print(f"[*] Archivos de caché encontrados ({len(data2_files)}):")
    candidate_urls: List[str] = []
    for f in data2_files:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"    -> {f} (Modificado: {mtime})")
        urls = extract_urls_from_data2(f)
        for u in urls:
            if u not in candidate_urls:
                candidate_urls.append(u)

    if not candidate_urls:
        print("\n[!] Se encontró el archivo `data_2`, pero no contiene ninguna URL de deseos.")
        print("    Abre Genshin Impact, entra al menú de Gachapón -> Historial, y vuelve a ejecutar el script.")
        sys.exit(1)

    print(f"\n[*] Se extrajeron {len(candidate_urls)} URL(s) candidata(s). Verificando validez con la API...")
    valid_url = find_valid_url(candidate_urls, lang=args.lang)

    if not valid_url:
        print("\n[!] Todas las URLs en caché han expirado (caducan tras unas horas).")
        print("    Por favor, abre el Historial de deseos dentro del juego para generar una clave nueva.")
        print("\n    Última URL encontrada en caché (expirada):")
        print(f"    {candidate_urls[0]}")
        sys.exit(1)

    print("\n[+] ¡URL válida encontrada!")
    print("-" * 70)
    print(valid_url)
    print("-" * 70)

    if copy_to_clipboard(valid_url):
        print("[+] La URL también se ha copiado automáticamente a tu portapapeles (lista para paimon.moe).")

    if args.url_only:
        return

    uid, wishes = fetch_all_wishes(valid_url, lang=args.lang)
    compute_pity_and_summary(wishes)
    export_results(uid, wishes, Path(args.output), args.lang)


if __name__ == "__main__":
    main()
