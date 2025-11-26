import os
import subprocess
import sys
import re
import threading
import shutil
import zipfile
import http.server
import socketserver
import uuid
import asyncio
import json
from pathlib import Path
from typing import Annotated
from threading import Lock

from litestar import Litestar, post, get
from litestar.config.cors import CORSConfig
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import File, Stream

# --- CONFIGURATION & PATHS ---
BASE_DIR = Path(__file__).parent.absolute()
ANDROID_DIR = BASE_DIR / "android_source"
DEPENDENCIES_DIR = BASE_DIR / "lib"
WEB_DIR = BASE_DIR / "web_ui"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "cache"

MAKE_SH_PATH = BASE_DIR / "make.sh"
ICON_FILENAME = "icon.png"
CONF_FILENAME = "webapk.conf"

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# --- BUILD STATE MANAGEMENT ---
build_states = {}
build_states_lock = Lock()

# --- HELPERS ---

def run_command(command: list[str], cwd: Path, output_target_dir: Path = None) -> None:
    try:
        if str(MAKE_SH_PATH) in command:
             os.chmod(MAKE_SH_PATH, 0o755)

        env = os.environ.copy()
        env["ANDROID_PROJECT_ROOT"] = str(ANDROID_DIR)
        env["DEPENDENCIES_ROOT"] = str(DEPENDENCIES_DIR)
        env["CACHE_DIR"] = str(CACHE_DIR)

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
    # We explicitly enable Universal Access here to fix CORS on local file:// loads
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
AllowFileAccess = true
AllowFileAccessFromFileURLs = true
AllowUniversalAccessFromFileURLs = true
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

def update_build_state(build_id: str, **kwargs) -> None:
    """Thread-safe update of build state."""
    with build_states_lock:
        if build_id in build_states:
            build_states[build_id].update(kwargs)

def execute_build_async(build_id: str, data: dict) -> None:
    """Execute build in background thread with progress tracking."""
    try:
        # Extract fields
        app_id = data.get("app_id")
        name = data.get("name")
        icon_data = data.get("icon_data")
        main_url = data.get("main_url")
        zip_data = data.get("zip_data")

        is_local_file = zip_data is not None
        app_output_dir = OUTPUT_DIR / app_id
        app_output_dir.mkdir(parents=True, exist_ok=True)

        # Stage 1: Initialize (5%)
        update_build_state(
            build_id,
            stage="Initializing",
            progress=5,
            message="Fixing project structure..."
        )
        fix_project_structure()

        # Stage 2: Save Icon (15%)
        update_build_state(
            build_id,
            stage="Preparing assets",
            progress=15,
            message="Saving app icon..."
        )
        icon_path = app_output_dir / ICON_FILENAME
        icon_path.write_bytes(icon_data)

        # Stage 3: Handle Content Source
        if is_local_file:
            update_build_state(
                build_id,
                stage="Preparing assets",
                progress=20,
                message="Extracting uploaded assets..."
            )
            assets_dir = ANDROID_DIR / "app/src/main/assets"

            if assets_dir.exists():
                shutil.rmtree(assets_dir)
            assets_dir.mkdir(parents=True, exist_ok=True)

            temp_zip = app_output_dir / "assets.zip"
            temp_zip.write_bytes(zip_data)

            try:
                with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                    zip_ref.extractall(assets_dir)
            except zipfile.BadZipFile:
                raise RuntimeError("Uploaded file is not a valid zip archive.")
            finally:
                temp_zip.unlink()

            found_index = list(assets_dir.rglob("index.html"))
            if not found_index:
                found_index = list(assets_dir.rglob("index.htm"))
            if not found_index:
                raise RuntimeError("Could not find 'index.html' inside the uploaded zip.")

            relative_path = found_index[0].relative_to(assets_dir)
            relative_path_str = str(relative_path).replace("\\", "/")
            final_url = f"file:///android_asset/{relative_path_str}"
            print(f"[BUILDER] Local asset mode. Launch URL: {final_url}")

            update_build_state(
                build_id,
                progress=25,
                message="Assets extracted successfully"
            )
        else:
            final_url = main_url
            update_build_state(
                build_id,
                progress=25,
                message="Using remote URL"
            )

        # Stage 4: Generate Config (35%)
        update_build_state(
            build_id,
            stage="Configuring project",
            progress=35,
            message="Generating configuration..."
        )
        conf_path = app_output_dir / CONF_FILENAME
        write_conf(app_id, name, final_url, conf_path)

        # Stage 5: Apply Config (45%)
        update_build_state(
            build_id,
            stage="Configuring project",
            progress=45,
            message="Applying configuration to project..."
        )
        run_command(["bash", str(MAKE_SH_PATH), "apply_config", str(conf_path)], cwd=BASE_DIR)

        # Stage 6: Patch Source Code (55%)
        update_build_state(
            build_id,
            stage="Patching source code",
            progress=55,
            message="Updating Java source files..."
        )
        patch_source_code(app_id)

        # Stage 7: Build APK (60%) - LONGEST STAGE
        update_build_state(
            build_id,
            stage="Building APK",
            progress=60,
            message="Compiling Android project (this may take 1-2 minutes)..."
        )
        print("[BUILDER] Starting APK assembly...")
        run_command(["bash", str(MAKE_SH_PATH), "apk"], cwd=BASE_DIR, output_target_dir=app_output_dir)

        # Stage 8: Verify (95%)
        update_build_state(
            build_id,
            stage="Finalizing",
            progress=95,
            message="Verifying APK file..."
        )
        final_apk = app_output_dir / f"{app_id}.apk"
        if not final_apk.exists():
            raise FileNotFoundError(f"APK not found at {final_apk}")

        # Stage 9: Complete (100%)
        update_build_state(
            build_id,
            status="complete",
            stage="Complete",
            progress=100,
            message="APK ready for download!",
            apk_path=str(final_apk),
            apk_filename=f"{app_id}_release.apk"
        )

    except Exception as e:
        print(f"[BUILDER] Build failed: {str(e)}")
        update_build_state(
            build_id,
            status="error",
            stage="Error",
            message=f"Build failed: {str(e)}",
            error=str(e)
        )

# --- HANDLERS ---

@post("/build-app")
async def build_apk(data: Annotated[dict, Body(media_type=RequestEncodingType.MULTI_PART)]) -> dict:
    """Initiate APK build and return build ID for progress tracking."""
    app_id = data.get("app_id")
    name = data.get("name")
    icon_file = data.get("icon")
    main_url = data.get("main_url")
    zip_file = data.get("zip_file")

    if not all([app_id, name, icon_file]):
        raise RuntimeError("Missing required fields (ID, Name, or Icon).")

    if not zip_file and not main_url:
        raise RuntimeError("You must provide either a Website URL or a Zip file.")

    if zip_file:
        print(f"[BUILDER] User uploaded assets zip: {zip_file.filename}")

    # Generate unique build ID
    build_id = str(uuid.uuid4())

    # Initialize build state
    with build_states_lock:
        build_states[build_id] = {
            "status": "in_progress",
            "stage": "Starting",
            "progress": 0,
            "message": "Build request received..."
        }

    # Prepare data for background thread
    build_data = {
        "app_id": app_id,
        "name": name,
        "icon_data": await icon_file.read(),
        "main_url": main_url,
        "zip_data": await zip_file.read() if zip_file else None
    }

    # Start background build thread
    build_thread = threading.Thread(
        target=execute_build_async,
        args=(build_id, build_data),
        daemon=True
    )
    build_thread.start()

    return {"build_id": build_id, "message": "Build started"}

@get("/build-progress/{build_id:str}")
async def stream_build_progress(build_id: str) -> Stream:
    """Stream build progress updates via Server-Sent Events."""
    from typing import AsyncGenerator

    async def event_generator() -> AsyncGenerator[str, None]:
        if build_id not in build_states:
            yield f"event: error\ndata: {json.dumps({'error': 'Invalid build ID'})}\n\n"
            return

        last_state = None
        while True:
            with build_states_lock:
                if build_id not in build_states:
                    yield f"event: error\ndata: {json.dumps({'error': 'Build state lost'})}\n\n"
                    break

                current_state = build_states[build_id].copy()

            if current_state != last_state:
                event_data = json.dumps({
                    "status": current_state.get("status", "in_progress"),
                    "stage": current_state.get("stage", "Unknown"),
                    "progress": current_state.get("progress", 0),
                    "message": current_state.get("message", "")
                })
                yield f"data: {event_data}\n\n"
                last_state = current_state

            if current_state.get("status") in ["complete", "error"]:
                break

            await asyncio.sleep(0.3)

        if current_state.get("status") == "complete":
            yield f"event: complete\ndata: {json.dumps({'build_id': build_id})}\n\n"
        elif current_state.get("status") == "error":
            yield f"event: error\ndata: {json.dumps({'error': current_state.get('error', 'Unknown error')})}\n\n"

    return Stream(event_generator(), media_type="text/event-stream")

@get("/download-apk/{build_id:str}")
async def download_apk(build_id: str) -> File:
    """Download the completed APK file."""
    with build_states_lock:
        if build_id not in build_states:
            raise RuntimeError("Invalid build ID")

        state = build_states[build_id]

        if state.get("status") != "complete":
            raise RuntimeError("Build not complete")

        apk_path = state.get("apk_path")
        apk_filename = state.get("apk_filename", "app_release.apk")

    if not apk_path or not Path(apk_path).exists():
        raise RuntimeError("APK file not found")

    return File(
        path=Path(apk_path),
        filename=apk_filename,
        media_type="application/vnd.android.package-archive"
    )

# --- SERVER ---

cors_config = CORSConfig(
    allow_origins=["http://localhost:8001"],
    allow_headers=["*"],
    allow_methods=["GET", "POST"]
)
app = Litestar(
    route_handlers=[build_apk, stream_build_progress, download_apk],
    cors_config=cors_config
)

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
