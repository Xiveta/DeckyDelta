import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any

import decky_plugin
from vdf import binary_dump, binary_load
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────
# Usamos DECKY_USER_HOME para que funcione con cualquier nombre de usuario,
# igual que hace OpenGOAL (no hardcodeamos /home/deck).
def _base_dir():
    return os.path.join(decky_plugin.DECKY_USER_HOME, "DeltaOnline")

def _game_dir():
    return os.path.join(_base_dir(), "Game")

def _deon_dir():
    return os.path.join(_base_dir(), "deon")

def _packs_dir():
    return os.path.join(_game_dir(), "GearGame", "ContentPacks")

def _steam_dir():
    return os.path.join(decky_plugin.DECKY_USER_HOME, ".local", "share", "Steam")

def _steam_userdata():
    return os.path.join(_steam_dir(), "userdata")

def _userdata_config(steam32: str):
    return os.path.join(_steam_userdata(), steam32, "config")

PLUGIN_DIR  = os.path.dirname(__file__)
AUTH_URL    = "https://getdeltaonline.net/deong3/backend/deonauthenticate.php"

# Ejecutable correcto del launcher de Delta Online
def _exe_path() -> str:
    return os.path.join(_game_dir(), "Binaries", "Win64", "deonupdater.exe")

# AppID calculado por SHA-256 del ejecutable, igual que OpenGOAL.
# Se recalcula en tiempo de ejecución para que sea siempre consistente.
def _compute_app_id() -> int:
    return (
        int(hashlib.sha256(_exe_path().encode()).hexdigest(), 16) % 1_000_000_000
    ) * -1

# Proton Experimental AppID en Steam
PROTON_EXPERIMENTAL_APPID = "1493710"

SETTINGS_FILE = os.path.join(PLUGIN_DIR, "settings.json")

# Remote JSON endpoints
_BASE_JSON        = "https://www.getdeltaonline.net/deong3/backend/json/m2q4/m3-ascension-public"
JSON_GAMECLIENT   = f"{_BASE_JSON}/deong3_backend_updates_gameclient.json"
JSON_CONTENTPACKS = f"{_BASE_JSON}/deong3_backend_contentpacks.json"
JSON_MOTD         = f"{_BASE_JSON}/deong3_backend_motd.json"

SCAN_FREQUENCIES = {"manual": 0, "daily": 1, "15days": 15, "30days": 30}

SPECIAL_CASES = {
    "PACK_GEARS2VOL3_V260404": "https://nx87798.your-storageshare.de/s/7Y3s4jgcLmZ4ttM/download",
}

# ─── State ────────────────────────────────────────────────────────────────────
_state: dict[str, Any] = {
    "status":         "idle",
    "logs":           [],
    "progress":       {},
    "queue":          [],
    "remote":         [],
    "motd":           [],
    "scan_frequency": "manual",
    "last_scan":      None,
}

_queue: asyncio.Queue = asyncio.Queue()


# ─── Settings persistence ─────────────────────────────────────────────────────

def _load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            _state["scan_frequency"] = data.get("scan_frequency", "manual")
            _state["last_scan"]      = data.get("last_scan", None)
    except Exception:
        pass


def _save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "scan_frequency": _state["scan_frequency"],
                "last_scan":      _state["last_scan"],
            }, f)
    except Exception:
        pass


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _log(msg: str):
    decky_plugin.logger.info(msg)
    _state["logs"].append(msg)
    if len(_state["logs"]) > 30:
        _state["logs"] = _state["logs"][-30:]


def _clean_env() -> dict:
    env = os.environ.copy()
    for v in ["LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONPATH", "SSL_CERT_FILE"]:
        env.pop(v, None)
    return env


def _fetch_json(url: str) -> Any:
    try:
        r = subprocess.run(
            ["curl", "-k", "-s", "--max-time", "15", url],
            capture_output=True, text=True, env=_clean_env()
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception as e:
        _log(f"❌ Error fetching {url}: {e}")
    return None


# ─── Local version detection ──────────────────────────────────────────────────

def _get_local_version_gamedata() -> str:
    path = os.path.join(_game_dir(), "Binaries", "Win64", "deonversion.xml")
    if not os.path.exists(path):
        return "0"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"<LauncherVersion>\s*(\d+)\s*</LauncherVersion>", content, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception as e:
        _log(f"❌ Error leyendo deonversion.xml: {e}")
    return "0"


def _parse_pack_xml(xml_path: str) -> str:
    try:
        with open(xml_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        m = re.search(r"<PackVersion>\s*(\d+)\s*</PackVersion>", content, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "0"


def _get_local_version_pack(pack_name: str) -> str:
    if not os.path.exists(_packs_dir()):
        return "0"
    direct = os.path.join(_packs_dir(), pack_name, "ContentPack.xml")
    if os.path.exists(direct):
        return _parse_pack_xml(direct)
    clean = pack_name.lower().replace("_", "").replace("-", "")
    try:
        for entry in os.listdir(_packs_dir()):
            ep = os.path.join(_packs_dir(), entry)
            if not os.path.isdir(ep):
                continue
            xml_path = os.path.join(ep, "ContentPack.xml")
            if not os.path.exists(xml_path):
                continue
            with open(xml_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            nm = re.search(r"<PackName>(.*?)</PackName>", content, re.IGNORECASE)
            if nm:
                xml_clean = nm.group(1).lower().replace("_", "").replace("-", "").replace(" ", "")
                if clean in xml_clean or xml_clean in clean:
                    return _parse_pack_xml(xml_path)
    except Exception as e:
        _log(f"❌ Error buscando pack {pack_name}: {e}")
    return "0"


def _refresh_local_version(pack_name: str) -> str:
    if pack_name == "GAMEDATA":
        return _get_local_version_gamedata()
    return _get_local_version_pack(pack_name)


# ─── Remote metadata ──────────────────────────────────────────────────────────

def _build_remote_list() -> list:
    entries = []
    gc_list = _fetch_json(JSON_GAMECLIENT)
    if gc_list:
        latest = gc_list[0]
        rv = str(latest.get("version", "0"))
        lv = _get_local_version_gamedata()
        entries.append({
            "key":            "gamedata",
            "pack_name":      "GAMEDATA",
            "friendly_name":  "Game Data",
            "description":    "\n".join(latest.get("patch_notes", [])),
            "file_name":      latest.get("file_name", ""),
            "url":            latest.get("url_game", ""),
            "file_size":      latest.get("file_size", 0),
            "md5":            latest.get("md5_game", ""),
            "remote_version": rv,
            "local_version":  lv,
            "needs_update":   int(rv) > int(lv),
        })
    else:
        _log("⚠ No se pudo obtener datos de gamedata")

    cp_list = _fetch_json(JSON_CONTENTPACKS)
    if cp_list:
        for pack in cp_list:
            rv    = str(pack.get("version", "0"))
            pname = pack.get("pack_name", "")
            lv    = _get_local_version_pack(pname)
            entries.append({
                "key":            pname.lower().replace("_", "-"),
                "pack_name":      pname,
                "friendly_name":  pack.get("pack_name_friendly", pname),
                "description":    pack.get("pack_description", ""),
                "file_name":      pack.get("file_name", ""),
                "url":            pack.get("url", ""),
                "file_size":      pack.get("file_size", 0),
                "md5":            pack.get("md5", ""),
                "remote_version": rv,
                "local_version":  lv,
                "needs_update":   int(rv) > int(lv),
            })
    else:
        _log("⚠ No se pudo obtener lista de content packs")

    return entries


def _fetch_motd() -> list:
    data = _fetch_json(JSON_MOTD)
    return data if isinstance(data, list) else []


async def _motd_loop():
    while True:
        try:
            motd = await asyncio.get_event_loop().run_in_executor(None, _fetch_motd)
            _state["motd"] = motd
            if not motd:
                _log("⚠ MOTD vacío")
            else:
                _log(f"📰 MOTD actualizado ({len(motd)} noticias)")
        except Exception as e:
            _log(f"❌ Error MOTD: {e}")
        await asyncio.sleep(60)


# ─── Download ─────────────────────────────────────────────────────────────────

def _download_real_deon(url: str, filename: str, output_path: str) -> bool:
    clean_name = os.path.splitext(filename)[0]
    if clean_name in SPECIAL_CASES:
        direct_url = SPECIAL_CASES[clean_name]
        _log(f"⬇ Descarga directa (special case): {filename}")
        try:
            result = subprocess.run(
                ["curl", "-L", "-k", "-o", output_path, direct_url],
                env=_clean_env()
            )
            if result.returncode != 0:
                _log("❌ curl falló en descarga directa")
                return False
            if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
                _log("❌ Archivo directo inválido o vacío")
                return False
            _log(f"✅ Descarga directa completada: {filename}")
            return True
        except Exception as e:
            _log(f"❌ Error en descarga directa: {e}")
            return False

    try:
        r_res = subprocess.run(
            ["curl", "-k", "-Ls",
             "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
             "-o", "/dev/null", "-w", "%{url_effective}", url],
            capture_output=True, text=True, env=_clean_env()
        )
        final_url = r_res.stdout.strip()

        if "your-storageshare" not in final_url:
            _log(f"❌ No se pudo resolver Nextcloud para: {url}")
            return False

        token    = final_url.split('/s/')[-1].split('?')[0].strip('/')
        real_url = f"https://nx87798.your-storageshare.de/public.php/webdav/{filename}"

        _log(f"⬇ Descargando: {filename}")
        result = subprocess.run(
            ["curl", "-L", "-k", "-u", f"{token}:", "-o", output_path, real_url],
            env=_clean_env()
        )

        if result.returncode != 0:
            _log("❌ curl falló durante la descarga")
            return False

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            _log("❌ Archivo descargado inválido o vacío")
            return False

        _log(f"✅ Descarga completada: {filename}")
        return True

    except Exception as e:
        _log(f"❌ Error descargando .deon: {e}")
        return False


# ─── Auth ─────────────────────────────────────────────────────────────────────

def _get_auth_password(clean_name: str, steam64: str) -> str:
    try:
        sid = int(str(steam64).strip()) - 76561197960265728
        url = (
            f"{AUTH_URL}"
            f"?BuildID=m3-ascension-public"
            f"&ActionToPerform=FileReq"
            f"&FileName={clean_name}"
            f"&SteamID=0x1100001{sid:08X}"
        )
        _log(f"🔑 Autenticando: {clean_name}")
        auth = subprocess.run(
            ["curl", "-k", "-s", "--max-time", "10", url],
            capture_output=True, text=True, env=_clean_env()
        )
        if auth.returncode != 0 or "auth_success:" not in auth.stdout:
            _log("❌ Auth fallida — cancelando extracción")
            return ""
        pw = auth.stdout.split("auth_success:")[1].split("<")[0].split(" ")[0].strip()
        _log("✅ Contraseña recibida")
        return pw
    except Exception as e:
        _log(f"❌ Error en autenticación: {e}")
        return ""


# ─── Install ──────────────────────────────────────────────────────────────────

async def _download_and_install(entry: dict, steam64: str) -> bool:
    filename  = entry.get("file_name", "")
    url       = entry.get("url", "")
    pack_name = entry.get("pack_name", "")

    if not filename or not url:
        _log(f"❌ Entrada inválida para pack {pack_name}")
        return False

    env = _clean_env()
    os.makedirs(_deon_dir(), exist_ok=True)
    os.makedirs(_game_dir(), exist_ok=True)

    deon_path  = os.path.join(_deon_dir(), filename)
    clean_name = os.path.splitext(filename)[0]

    if os.path.exists(deon_path):
        _log(f"📦 Usando caché local: {filename}")
    else:
        ok = await asyncio.get_event_loop().run_in_executor(
            None, _download_real_deon, url, filename, deon_path
        )
        if not ok:
            _log(f"❌ Descarga fallida: {filename}")
            return False

    pw = await asyncio.get_event_loop().run_in_executor(
        None, _get_auth_password, clean_name, steam64
    )
    if not pw:
        _log(f"❌ Sin contraseña — abortando: {filename}")
        return False

    _log(f"🚀 Extrayendo {filename} → {_game_dir()}")
    cmd  = ["7z", "x", deon_path, f"-o{_game_dir()}", "-y", "-aoa", f"-p{pw}"]
    proc = await asyncio.create_subprocess_exec(*cmd, env=env)
    await proc.wait()

    _state["progress"].pop(filename, None)

    if proc.returncode != 0:
        _log(f"❌ 7z falló para {filename}")
        return False

    _log(f"✅ {filename} instalado correctamente")

    new_lv = await asyncio.get_event_loop().run_in_executor(
        None, _refresh_local_version, pack_name
    )
    for e in _state["remote"]:
        if e["pack_name"] == pack_name:
            e["local_version"] = new_lv
            e["needs_update"]  = int(e["remote_version"]) > int(new_lv)
            _log(f"🔄 {pack_name}: local actualizado → v{new_lv}")
            break

    return True


# ─── Queue worker ─────────────────────────────────────────────────────────────

async def _queue_worker(steam64: str):
    while True:
        try:
            entry = await asyncio.wait_for(_queue.get(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            break
        try:
            fn = entry.get("file_name", "")
            if fn in _state["queue"]:
                _state["queue"].remove(fn)
            await _download_and_install(entry, steam64)
        finally:
            _queue.task_done()


# ─── XACT fix ────────────────────────────────────────────────────────────────

def _ensure_compatdata(appid: int) -> str:
    path = os.path.join(_steam_dir(), "steamapps", "compatdata", str(appid))
    os.makedirs(os.path.join(path, "pfx"), exist_ok=True)
    return path


def _apply_xact_fix(appid: int) -> bool:
    assets_dir = os.path.join(PLUGIN_DIR, "assets", "xact_redist")
    if not os.path.exists(assets_dir):
        _log("⚠ XACT assets no encontrados — fix omitido")
        return False
    compat_path = _ensure_compatdata(appid)
    dst = os.path.join(compat_path, "pfx", "drive_c", "windows", "system32")
    os.makedirs(dst, exist_ok=True)
    try:
        for fname in os.listdir(assets_dir):
            shutil.copy2(os.path.join(assets_dir, fname), os.path.join(dst, fname))
        _log("✅ XACT audio fix aplicado")
        return True
    except Exception as e:
        _log(f"❌ XACT fix error: {e}")
        return False


# ─── Steam shortcut (OpenGOAL-style) ─────────────────────────────────────────

def _shortcut_already_exists(shortcuts: dict, name: str) -> bool:
    for key, sc in shortcuts.items():
        if "AppName" in sc and sc["AppName"] == name:
            decky_plugin.logger.info(f"Shortcut '{name}' ya existe")
            return True
    return False


def _set_proton_experimental(steam32: str, app_id: int) -> bool:
    """
    Escribe en localconfig.vdf para que Steam use Proton Experimental
    automáticamente al lanzar el acceso directo — igual que si el usuario
    lo hubiera seleccionado manualmente en la pestaña Compatibilidad.
    """
    try:
        lc_file = Path(_userdata_config(steam32)) / "localconfig.vdf"
        import vdf as vdf_mod

        if lc_file.exists():
            with open(lc_file, "r", encoding="utf-8", errors="replace") as f:
                lc = vdf_mod.load(f)
        else:
            lc = {}

        # Ruta: UserLocalConfigStore → Software → Valve → Steam → CompatToolMapping
        ucs = lc.setdefault("UserLocalConfigStore", {})
        sw  = ucs.setdefault("Software", {})
        val = sw.setdefault("Valve", {})
        stm = val.setdefault("Steam", {})
        ctm = stm.setdefault("CompatToolMapping", {})

        # El app_id en VDF texto es string con el número positivo del shortcut
        # Steam usa el appId tal como aparece en shortcuts.vdf (negativo en binario,
        # pero en localconfig.vdf se escribe el mismo valor en decimal)
        ctm[str(app_id)] = {
            "name":    "proton_experimental",
            "config":  "",
            "Priority": "250",
        }

        with open(lc_file, "w", encoding="utf-8") as f:
            vdf_mod.dump(lc, f, pretty=True)

        _log(f"✅ Proton Experimental configurado para AppID {app_id}")
        return True
    except Exception as e:
        _log(f"⚠ No se pudo configurar Proton Experimental: {e}")
        return False


def _create_steam_shortcut(steam32: str) -> int | None:
    """
    Crea el acceso directo de Delta Online en shortcuts.vdf usando la librería vdf,
    igual que OpenGOAL. Configura automáticamente Proton Experimental y aplica
    el XACT fix. Devuelve el appId generado, o None si ya existía o hubo error.
    """
    try:
        sc_dir  = Path(_userdata_config(steam32))
        sc_dir.mkdir(parents=True, exist_ok=True)
        sc_file = sc_dir / "shortcuts.vdf"

        if sc_file.exists():
            d = binary_load(open(sc_file, "rb"))
        else:
            d = {"shortcuts": {}}

        if _shortcut_already_exists(d["shortcuts"], "Delta Online"):
            _log("ℹ Shortcut de Delta Online ya existe")
            return None

        app_id = _compute_app_id()
        exe    = _exe_path()   # deonupdater.exe — launcher oficial de Delta Online
        icon   = os.path.join(PLUGIN_DIR, "decky.png")

        d["shortcuts"]["delta-online"] = {
            "appid":              app_id,
            "AppName":            "Delta Online",
            "Exe":                exe,
            "StartDir":           os.path.join(_game_dir(), "Binaries", "Win64"),
            "icon":               icon,
            "LaunchOptions":      "",
            "IsHidden":           0,
            "AllowDesktopConfig": 1,
            "AllowOverlay":       1,
            "OpenVR":             0,
            "ShortcutPath":       "",
            "tags":               {},
        }

        binary_dump(d, open(sc_file, "wb"))
        _log(f"✅ Steam shortcut creado (AppID {app_id})")

        # Configurar Proton Experimental automáticamente
        _set_proton_experimental(steam32, app_id)

        # Aplicar XACT fix automáticamente al crear el shortcut
        _log("🔊 Aplicando XACT audio fix…")
        _apply_xact_fix(app_id)

        return app_id

    except Exception as e:
        _log(f"❌ Shortcut error: {e}")
        return None


# ─── Artwork helpers (igual que OpenGOAL) ────────────────────────────────────
# logo.png actúa como icono (campo icon del shortcut) Y como imagen de logo en Big Picture.
# Para los demás slots usamos también logo.png si no hay imágenes específicas.

def _read_image_as_base64(filename: str) -> str | None:
    path = os.path.join(PLUGIN_DIR, filename)
    if not os.path.exists(path):
        _log(f"⚠ Imagen no encontrada: {path}")
        return None
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        _log(f"❌ Error leyendo imagen {filename}: {e}")
        return None


# ─── Background auto-scan ─────────────────────────────────────────────────────

async def _background_scan_loop():
    while True:
        await asyncio.sleep(60)
        freq = _state["scan_frequency"]
        days = SCAN_FREQUENCIES.get(freq, 0)
        if days == 0:
            continue
        last = _state["last_scan"]
        if last:
            try:
                if datetime.now() < datetime.fromisoformat(last) + timedelta(days=days):
                    continue
            except Exception:
                pass
        if _state["status"] == "idle":
            _log(f"🕐 Auto-scan ({freq}) iniciado")
            await _do_scan()


async def _do_scan() -> list:
    _state["status"] = "scanning"
    _state["remote"] = []
    _log("🔍 Comprobando versiones (JSON)…")
    results = await asyncio.get_event_loop().run_in_executor(None, _build_remote_list)
    _state["remote"]    = results
    _state["status"]    = "idle"
    _state["last_scan"] = datetime.now().isoformat()
    _save_settings()
    outdated = sum(1 for e in results if e["needs_update"])
    _log(f"✅ Scan listo — {outdated} actualización(es) pendiente(s)")
    return results


# ─── Plugin class ─────────────────────────────────────────────────────────────

class Plugin:

    async def _main(self):
        decky_plugin.logger.info("DeckyDelta cargado!")
        _load_settings()
        asyncio.ensure_future(_motd_loop())
        asyncio.ensure_future(_background_scan_loop())

    async def _unload(self):
        decky_plugin.logger.info("DeckyDelta descargado!")

    async def _migration(self):
        """Crea las carpetas necesarias al instalar/actualizar el plugin."""
        decky_plugin.logger.info("Asegurando rutas de DeckyDelta…")
        os.makedirs(_deon_dir(), exist_ok=True)
        os.makedirs(_game_dir(), exist_ok=True)

    # ── State ─────────────────────────────────────────────────────────────────

    async def get_state(self) -> dict:
        return {
            "status":         _state["status"],
            "logs":           list(_state["logs"]),
            "progress":       dict(_state["progress"]),
            "queue":          list(_state["queue"]),
            "remote":         list(_state["remote"]),
            "motd":           list(_state["motd"]),
            "scan_frequency": _state["scan_frequency"],
            "last_scan":      _state["last_scan"],
        }

    async def clear_logs(self) -> bool:
        _state["logs"] = []
        return True

    # ── Scan ──────────────────────────────────────────────────────────────────

    async def scan_mirrors(self) -> list:
        return await _do_scan()

    # ── Settings ──────────────────────────────────────────────────────────────

    async def set_scan_frequency(self, frequency: str) -> bool:
        if frequency not in SCAN_FREQUENCIES:
            return False
        _state["scan_frequency"] = frequency
        _save_settings()
        _log(f"⚙ Auto-scan: {frequency}")
        return True

    # ── Install ───────────────────────────────────────────────────────────────

    async def install_auto(self, steam64: str) -> bool:
        to_install = [e for e in _state["remote"] if e["needs_update"]]
        if not to_install:
            _log("✅ Todo está actualizado")
            _state["status"] = "completed"
            return True
        _state["status"] = "downloading"
        for entry in to_install:
            _state["queue"].append(entry.get("file_name", ""))
            await _queue.put(entry)
        worker = asyncio.ensure_future(_queue_worker(steam64))
        await _queue.join()
        worker.cancel()
        _state["status"] = "completed"
        _log("🎉 Instalación completada")
        return True

    async def install_manual(self, pack_name: str, steam64: str) -> bool:
        entry = next((e for e in _state["remote"] if e["pack_name"] == pack_name), None)
        if not entry:
            _log(f"❌ Pack no encontrado: {pack_name}")
            return False
        _state["status"] = "downloading"
        ok = await _download_and_install(entry, steam64)
        _state["status"] = "completed" if ok else "error"
        if ok:
            _log("🎉 Instalación completada")
        return ok

    # ── Shortcut + Artwork + XACT ─────────────────────────────────────────────

    async def create_shortcut(self, steam32: str) -> int | None:
        """
        Crea el acceso directo en shortcuts.vdf.
        Devuelve el appId generado para que el frontend pueda asignarle las imágenes,
        o None si ya existía o falló.
        """
        return await asyncio.get_event_loop().run_in_executor(
            None, _create_steam_shortcut, steam32
        )

    async def shortcut_already_created(self, steam32: str) -> bool:
        try:
            sc_file = Path(_userdata_config(steam32)) / "shortcuts.vdf"
            if not sc_file.exists():
                return False
            d = binary_load(open(sc_file, "rb"))
            return _shortcut_already_exists(d["shortcuts"], "Delta Online")
        except Exception as e:
            _log(f"❌ shortcut_already_created error: {e}")
            return False

    async def read_logo_image_as_base64(self) -> str | None:
        """logo.png — se usa como logo en Big Picture y también como icono del plugin."""
        return await asyncio.get_event_loop().run_in_executor(
            None, _read_image_as_base64, "decky.png"
        )

    async def read_icon_image_as_base64(self) -> str | None:
        """Icono del shortcut (icon.png si existe, si no usa logo.png)."""
        icon = "icon.png" if os.path.exists(os.path.join(PLUGIN_DIR, "icon.png")) else "decky.png"
        return await asyncio.get_event_loop().run_in_executor(
            None, _read_image_as_base64, icon
        )

    async def read_small_image_as_base64(self) -> str | None:
        """Cápsula pequeña (portrait) en la biblioteca de Steam."""
        img = "img/small.png" if os.path.exists(os.path.join(PLUGIN_DIR, "img", "small.png")) else "decky.png"
        return await asyncio.get_event_loop().run_in_executor(
            None, _read_image_as_base64, img
        )

    async def read_wide_image_as_base64(self) -> str | None:
        """Cápsula ancha (horizontal) en la biblioteca de Steam."""
        img = "img/wide.png" if os.path.exists(os.path.join(PLUGIN_DIR, "img", "wide.png")) else "decky.png"
        return await asyncio.get_event_loop().run_in_executor(
            None, _read_image_as_base64, img
        )

    async def read_hero_image_as_base64(self) -> str | None:
        """Banner hero (parte superior de la página del juego)."""
        img = "img/hero.png" if os.path.exists(os.path.join(PLUGIN_DIR, "img", "hero.png")) else "decky.png"
        return await asyncio.get_event_loop().run_in_executor(
            None, _read_image_as_base64, img
        )

    async def apply_xact(self) -> bool:
        app_id = _compute_app_id()
        return await asyncio.get_event_loop().run_in_executor(None, _apply_xact_fix, app_id)

    async def apply_shortcut_and_xact(self, steam32: str) -> bool:
        """
        Compatibilidad: crea shortcut (que ya incluye XACT y Proton Experimental).
        El frontend asigna las imágenes por separado.
        """
        result = await asyncio.get_event_loop().run_in_executor(
            None, _create_steam_shortcut, steam32
        )
        return result is not None
