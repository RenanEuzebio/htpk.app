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

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).parent.absolute()
MAKE_SH_PATH = BASE_DIR / "make.sh"
CONFIG_FILE = BASE_DIR / "webapk.conf"
ICON_FILENAME = "icon.png"

# --- HELPERS ---

def run_command(command: list[str], cwd: Path) -> None:
    try:
        if str(MAKE_SH_PATH) in command:
             os.chmod(MAKE_SH_PATH, 0o755)

        print(f"[BUILDER] Executing: {' '.join(command)}")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        # Stream logs in real-time
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
    """
    Self-Healing: Syncs build.gradle applicationId with the actual directory structure on disk.
    This recovers from interrupted builds where folders moved but config wasn't updated.
    """
    try:
        # 1. Find where MainActivity.java actually lives
        # It looks for app/src/main/java/com/{SOMETHING}/webtoapk/MainActivity.java
        java_files = list(BASE_DIR.glob("app/src/main/java/com/*/webtoapk/MainActivity.java"))
        
        if not java_files:
            print("[BUILDER] Warning: MainActivity.java not found in expected structure. Auto-fix might fail.")
            return

        # The parent folder of 'webtoapk' is the current App ID on disk
        current_folder_id = java_files[0].parent.parent.name
        
        # 2. Read what Gradle thinks the ID is
        gradle_path = BASE_DIR / "app/build.gradle"
        if not gradle_path.exists(): return
        
        content = gradle_path.read_text(encoding="utf-8")
        
        # 3. Compare and Fix
        match = re.search(r'applicationId "com\.([a-zA-Z0-9_]+)\.webtoapk"', content)
        if match:
            configured_id = match.group(1)
            
            if configured_id != current_folder_id:
                print(f"[BUILDER] REPAIRING: Gradle ID '{configured_id}' mismatch with Folder '{current_folder_id}'. Syncing...")
                # Force Gradle to match the folder structure
                new_content = content.replace(
                    f'applicationId "com.{configured_id}.webtoapk"', 
                    f'applicationId "com.{current_folder_id}.webtoapk"'
                )
                gradle_path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        print(f"[BUILDER] Auto-fix warning: {e}")

def patch_source_code(app_id: str) -> None:
    java_files = list(BASE_DIR.glob("app/src/main/java/**/*.java"))
    print(f"[BUILDER] Patching {len(java_files)} source files for App ID '{app_id}'...")

    for file_path in java_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            original_content = content

            # 1. Fix Package Name
            content = re.sub(
                r'package\s+com\.[a-zA-Z0-9_]+\.webtoapk;', 
                f'package com.{app_id}.webtoapk;', 
                content
            )

            # 2. Fix MainActivity Bugs
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
        # 1. Run Self-Healing (Fixes interrupted builds)
        fix_project_structure()

        # 2. Save Icon & Config
        icon_data = await icon_file.read()
        (BASE_DIR / ICON_FILENAME).write_bytes(icon_data)
        write_conf(app_id, name, main_url)

        # 3. Apply Config
        # Optimization: We skipped 'clean' to make it fast.
        run_command(["bash", str(MAKE_SH_PATH), "apply_config"], cwd=BASE_DIR)

        # 4. Patch Source
        patch_source_code(app_id)

        # 5. Build
        print("[BUILDER] Starting APK assembly...")
        run_command(["bash", str(MAKE_SH_PATH), "apk"], cwd=BASE_DIR)

        # 6. Return Result
        expected_apk = BASE_DIR / f"{app_id}.apk"
        if not expected_apk.exists():
            raise FileNotFoundError(f"Build succeeded but {expected_apk.name} not found.")

        return File(
            path=expected_apk,
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
    """Starts a simple HTTP server for the frontend on port 8001."""
    PORT = 8001
    Handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            print(f"[FRONTEND] UI Server started at http://localhost:{PORT}")
            httpd.serve_forever()
    except OSError as e:
        print(f"[FRONTEND] Error: Port {PORT} is busy. Is the server already running? ({e})")

if __name__ == "__main__":
    import uvicorn
    
    # 1. Start Frontend (Daemon thread)
    frontend_thread = threading.Thread(target=run_frontend_server, daemon=True)
    frontend_thread.start()

    # 2. Start Backend (Blocking)
    print(f"[BACKEND] API Server started at http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
