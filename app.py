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

# Directory Definitions
ANDROID_DIR = BASE_DIR / "android_source"
SCRIPTS_DIR = BASE_DIR / "build_scripts"
WEB_DIR = BASE_DIR / "web_interface"
OUTPUT_DIR = BASE_DIR / "output_apks"

# File Paths
MAKE_SH_PATH = SCRIPTS_DIR / "make.sh"
CONFIG_FILE = ANDROID_DIR / "webapk.conf" # Config now lives inside android_source
ICON_FILENAME = "icon.png"

# Ensure output directory exists
OUTPUT_DIR.mkdir(exist_ok=True)

# --- HELPERS ---

def run_command(command: list[str], cwd: Path) -> None:
    try:
        if str(MAKE_SH_PATH) in command:
             os.chmod(MAKE_SH_PATH, 0o755)

        # Add the android source path to the environment so make.sh knows where it is
        env = os.environ.copy()
        env["ANDROID_PROJECT_ROOT"] = str(ANDROID_DIR)
        env["OUTPUT_DIR"] = str(OUTPUT_DIR)

        print(f"[BUILDER] Executing: {' '.join(command)}")
        
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
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

def write_conf(app_id: str, name: str, main_url: str) -> None:
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
    CONFIG_FILE.write_text(content, encoding="utf-8")

def fix_project_structure() -> None:
    """Syncs build.gradle applicationId with the actual directory structure."""
    try:
        java_files = list(ANDROID_DIR.glob("app/src/main/java/com/*/webtoapk/MainActivity.java"))
        if not java_files:
            print("[BUILDER] Warning: MainActivity.java not found. Auto-fix might fail.")
            return

        current_folder_id = java_files[0].parent.parent.name
        gradle_path = ANDROID_DIR / "app/build.gradle"
        
        if not gradle_path.exists(): return
        
        content = gradle_path.read_text(encoding="utf-8")
        match = re.search(r'applicationId "com\.([a-zA-Z0-9_]+)\.webtoapk"', content)
        if match:
            configured_id = match.group(1)
            if configured_id != current_folder_id:
                print(f"[BUILDER] REPAIRING: Syncing Gradle ID '{configured_id}' to Folder '{current_folder_id}'")
                new_content = content.replace(
                    f'applicationId "com.{configured_id}.webtoapk"', 
                    f'applicationId "com.{current_folder_id}.webtoapk"'
                )
                gradle_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        print(f"[BUILDER] Auto-fix warning: {e}")

def patch_source_code(app_id: str) -> None:
    java_files = list(ANDROID_DIR.glob("app/src/main/java/**/*.java"))
    print(f"[BUILDER] Patching {len(java_files)} source files for App ID '{app_id}'...")

    for file_path in java_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            original_content = content

            content = re.sub(
                r'package\s+com\.[a-zA-Z0-9_]+\.webtoapk;', 
                f'package com.{app_id}.webtoapk;', 
                content
            )

            if file_path.name == "MainActivity.java":
                broken_code = 'LOCATION_PERMISSION_REQUEST_CODE = "";'
                fixed_code = 'LOCATION_PERMISSION_REQUEST_CODE = 1001;'
                if broken_code in content:
                    content = content.replace(broken_code, fixed_code)

            if content != original_content:
                file_path.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"[BUILDER] Warning: Could not patch {file_path.name}: {e}")

# --- HANDLERS ---

@post("/build-app")
async def build_apk(
    data: Annotated[dict, Body(media_type=RequestEncodingType.MULTI_PART)],
) -> File:
    
    app_id = data.get("app_id")
    name = data.get("name")
    main_url = data.get("main_url")
    icon_file: UploadFile = data.get("icon")

    if not all([app_id, name, main_url, icon_file]):
        raise RuntimeError("Missing required fields.")

    try:
        # 1. Run Self-Healing
        fix_project_structure()

        # 2. Save Icon & Config to Android Dir
        icon_data = await icon_file.read()
        (ANDROID_DIR / ICON_FILENAME).write_bytes(icon_data)
        write_conf(app_id, name, main_url)

        # 3. Apply Config (Execute make.sh from SCRIPTS_DIR)
        run_command(["bash", str(MAKE_SH_PATH), "apply_config"], cwd=SCRIPTS_DIR)

        # 4. Patch Source
        patch_source_code(app_id)

        # 5. Build
        print("[BUILDER] Starting APK assembly...")
        run_command(["bash", str(MAKE_SH_PATH), "apk"], cwd=SCRIPTS_DIR)

        # 6. Return Result from OUTPUT_DIR
        final_apk = OUTPUT_DIR / f"{app_id}.apk"
        if not final_apk.exists():
            raise FileNotFoundError(f"Build succeeded but {final_apk.name} not found in output folder.")

        return File(
            path=final_apk,
            filename=f"{app_id}_release.apk",
            media_type="application/vnd.android.package-archive"
        )

    except Exception as e:
        print(f"Server Error: {e}")
        raise RuntimeError(f"Build Failed: {str(e)}")

# --- APP SETUP ---

cors_config = CORSConfig(allow_origins=["http://localhost:8001"]) 

app = Litestar(
    route_handlers=[build_apk],
    cors_config=cors_config
)

def run_frontend_server():
    PORT = 8001
    # Change directory to web_interface so index.html is served at root
    os.chdir(WEB_DIR)
    
    Handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            print(f"[FRONTEND] UI Server started at http://localhost:{PORT}")
            httpd.serve_forever()
    except OSError as e:
        print(f"[FRONTEND] Error: Port {PORT} is busy. ({e})")

if __name__ == "__main__":
    import uvicorn
    frontend_thread = threading.Thread(target=run_frontend_server, daemon=True)
    frontend_thread.start()

    print(f"[BACKEND] API Server started at http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")