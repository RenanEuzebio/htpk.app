import os
import subprocess
import sys
import re
import threading
import http.server
import socketserver
from pathlib import Path
from typing import Annotated

from litestar import Litestar, post
from litestar.config.cors import CORSConfig
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import File

# --- CONFIGURATION & PATHS ---
BASE_DIR = Path(__file__).parent.absolute()
ANDROID_DIR = BASE_DIR / "android_source"
DEPENDENCIES_DIR = BASE_DIR / "dependencies"
WEB_DIR = BASE_DIR / "web_interface"
OUTPUT_DIR = BASE_DIR / "output_apks"
MAKE_SH_PATH = BASE_DIR / "make.sh"
ICON_FILENAME = "icon.png"
CONF_FILENAME = "webapk.conf"

OUTPUT_DIR.mkdir(exist_ok=True)

# --- HELPERS ---

def run_command(command: list[str], cwd: Path, output_target_dir: Path = None) -> None:
    try:
        if str(MAKE_SH_PATH) in command:
             os.chmod(MAKE_SH_PATH, 0o755)

        env = os.environ.copy()
        env["ANDROID_PROJECT_ROOT"] = str(ANDROID_DIR)
        env["DEPENDENCIES_ROOT"] = str(DEPENDENCIES_DIR)
        
        if output_target_dir:
            env["OUTPUT_DIR"] = str(output_target_dir)
        else:
            env["OUTPUT_DIR"] = str(OUTPUT_DIR)

        print(f"[BUILDER] Executing: {' '.join(command)}")
        process = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env
        )
        
        if process.stdout:
            for line in process.stdout:
                print(line, end="")
                sys.stdout.flush()
        return_code = process.wait()
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Build command failed with code {e.returncode}")

def write_conf(app_id: str, name: str, main_url: str, target_path: Path) -> None:
    content = f"""
id = {app_id}
name = {name}
mainURL = {main_url}
icon = {ICON_FILENAME}
allowSubdomains = true
requireDoubleBackToExit = true
enableExternalLinks = true
openExternalLinksInBrowser = true
confirmOpenInBrowser = true
allowOpenMobileApp = false
geolocationEnabled = false
"""
    target_path.write_text(content, encoding="utf-8")

def fix_project_structure() -> None:
    try:
        java_files = list(ANDROID_DIR.glob("app/src/main/java/com/*/webtoapk/MainActivity.java"))
        if not java_files: return

        current_folder_id = java_files[0].parent.parent.name
        gradle_path = ANDROID_DIR / "app/build.gradle"
        if not gradle_path.exists(): return
        
        content = gradle_path.read_text(encoding="utf-8")

        if 'applicationId "com.$1.webtoapk"' in content:
            print(f"[BUILDER] REPAIRING: Found corruption '$1' in build.gradle. Fixing to '{current_folder_id}'")
            content = content.replace('applicationId "com.$1.webtoapk"', f'applicationId "com.{current_folder_id}.webtoapk"')
            gradle_path.write_text(content, encoding="utf-8")
            return

        match = re.search(r'applicationId "com\.([a-zA-Z0-9_]+)\.webtoapk"', content)
        if match:
            configured_id = match.group(1)
            if configured_id != current_folder_id:
                print(f"[BUILDER] Syncing Gradle ID '{configured_id}' to Folder '{current_folder_id}'")
                new_content = content.replace(f'applicationId "com.{configured_id}.webtoapk"', f'applicationId "com.{current_folder_id}.webtoapk"')
                gradle_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        print(f"[BUILDER] Auto-fix warning: {e}")

def patch_source_code(app_id: str) -> None:
    java_files = list(ANDROID_DIR.glob("app/src/main/java/**/*.java"))
    print(f"[BUILDER] Patching {len(java_files)} source files for App ID '{app_id}'...")
    for file_path in java_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            original = content
            content = re.sub(r'package\s+com\.[a-zA-Z0-9_]+\.webtoapk;', f'package com.{app_id}.webtoapk;', content)
            if file_path.name == "MainActivity.java":
                content = content.replace('LOCATION_PERMISSION_REQUEST_CODE = "";', 'LOCATION_PERMISSION_REQUEST_CODE = 1001;')
            if content != original: file_path.write_text(content, encoding="utf-8")
        except Exception as e: print(f"[BUILDER] Warning: Could not patch {file_path.name}: {e}")

# --- HANDLERS ---

@post("/build-app")
async def build_apk(data: Annotated[dict, Body(media_type=RequestEncodingType.MULTI_PART)]) -> File:
    app_id, name, main_url, icon_file = data.get("app_id"), data.get("name"), data.get("main_url"), data.get("icon")
    if not all([app_id, name, main_url, icon_file]): raise RuntimeError("Missing required fields.")

    app_output_dir = OUTPUT_DIR / app_id
    app_output_dir.mkdir(parents=True, exist_ok=True)

    try:
        fix_project_structure()
        icon_path = app_output_dir / ICON_FILENAME
        conf_path = app_output_dir / CONF_FILENAME
        icon_path.write_bytes(await icon_file.read())
        write_conf(app_id, name, main_url, conf_path)

        run_command(["bash", str(MAKE_SH_PATH), "apply_config", str(conf_path)], cwd=BASE_DIR)
        patch_source_code(app_id)
        print("[BUILDER] Starting APK assembly...")
        run_command(["bash", str(MAKE_SH_PATH), "apk"], cwd=BASE_DIR, output_target_dir=app_output_dir)

        final_apk = app_output_dir / f"{app_id}.apk"
        if not final_apk.exists(): raise FileNotFoundError(f"APK not found at {final_apk}")
        return File(path=final_apk, filename=f"{app_id}_release.apk", media_type="application/vnd.android.package-archive")
    except Exception as e:
        print(f"Server Error: {e}")
        raise RuntimeError(f"Build Failed: {str(e)}")

# --- SERVER ---

cors_config = CORSConfig(allow_origins=["http://localhost:8001"]) 
app = Litestar(route_handlers=[build_apk], cors_config=cors_config)

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        if "favicon.ico" in args[0]: return
        super().log_message(format, *args)

class QuietServer(socketserver.TCPServer):
    def handle_error(self, request, client_address): pass

def run_frontend():
    os.chdir(WEB_DIR)
    QuietServer.allow_reuse_address = True
    try:
        with QuietServer(("", 8001), QuietHandler) as httpd:
            print(f"[FRONTEND] Server started at http://localhost:8001")
            httpd.serve_forever()
    except OSError as e: print(f"[FRONTEND] Error: {e}")

if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=run_frontend, daemon=True).start()
    print(f"[BACKEND] API Server started at http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
