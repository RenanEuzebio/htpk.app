import os
import subprocess
import sys
import re
import threading
import shutil
import zipfile
import uuid
import asyncio
import json
import http.server
import socketserver
from pathlib import Path
from typing import Annotated, AsyncGenerator
from threading import Lock

from litestar import Litestar, post, get
from litestar.config.cors import CORSConfig
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import File, Stream

# --- CONFIGURATION ---
BASE_DIR = Path(__file__).parent.absolute()
ANDROID_DIR = BASE_DIR / "android_source"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "cache"
WEB_DIR = BASE_DIR / "web_ui"
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
    env = os.environ.copy()
    env["ANDROID_PROJECT_ROOT"] = str(ANDROID_DIR)
    env["CACHE_DIR"] = str(CACHE_DIR)
    if output_target_dir: env["OUTPUT_DIR"] = str(output_target_dir)

    subprocess.run(command, cwd=cwd, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

def write_conf(app_id: str, name: str, target_path: Path) -> None:
    content = f"id = {app_id}\nname = {name}\nicon = {ICON_FILENAME}\n"
    target_path.write_text(content, encoding="utf-8")

def fix_project_structure() -> None:
    """Syncs the Android folder structure with the Gradle configuration."""
    try:
        java_files = list(ANDROID_DIR.glob("app/src/main/java/com/*/webtoapk/MainActivity.java"))
        if not java_files: return

        current_folder_id = java_files[0].parent.parent.name
        gradle_path = ANDROID_DIR / "app/build.gradle"
        if not gradle_path.exists(): return

        content = gradle_path.read_text(encoding="utf-8")
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
    """
    Updates package name and injects Mixed Content/CORS fixes
    into the existing MainActivity.java without overwriting it.
    """
    java_files = list(ANDROID_DIR.glob("app/src/main/java/**/*.java"))
    print(f"[BUILDER] Patching {len(java_files)} source files for App ID '{app_id}'...")

    for file_path in java_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            original = content

            # 1. Update Package Name
            content = re.sub(r'package\s+com\.[a-zA-Z0-9_]+\.webtoapk;', f'package com.{app_id}.webtoapk;', content)

            # 2. Inject Fixes into MainActivity.java (Idempotent)
            if file_path.name == "MainActivity.java":
                # Fix Location Permission ID
                content = content.replace('LOCATION_PERMISSION_REQUEST_CODE = "";', 'LOCATION_PERMISSION_REQUEST_CODE = 1001;')

                # The Code we want to inject
                injection_code = """
        // --- INJECTED FIXES ---
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            webSettings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
        webSettings.setMediaPlaybackRequiresUserGesture(false);
        webSettings.setAllowFileAccess(true);
        webSettings.setAllowFileAccessFromFileURLs(true);
        webSettings.setAllowUniversalAccessFromFileURLs(true);
        // ----------------------
        """
                # We find a safe anchor point to inject after
                anchor = "webSettings.setDatabaseEnabled(DatabaseEnabled);"

                # Only inject if not already present (Prevents duplication/crashes)
                if anchor in content and "setMixedContentMode" not in content:
                    content = content.replace(anchor, anchor + injection_code)

            if content != original:
                file_path.write_text(content, encoding="utf-8")

        except Exception as e:
            print(f"[BUILDER] Warning patching {file_path.name}: {e}")

def update_build_state(build_id: str, **kwargs) -> None:
    with build_states_lock:
        if build_id in build_states:
            build_states[build_id].update(kwargs)

def execute_build_async(build_id: str, data: dict) -> None:
    try:
        app_id = data.get("app_id")
        name = data.get("name")
        icon_data = data.get("icon_data")
        main_url = data.get("main_url")
        zip_data = data.get("zip_data")

        is_local_file = zip_data is not None
        app_output_dir = OUTPUT_DIR / app_id
        app_output_dir.mkdir(parents=True, exist_ok=True)

        update_build_state(build_id, stage="Initializing", progress=5, message="Restoring project structure...")
        fix_project_structure()

        update_build_state(build_id, stage="Preparing assets", progress=15, message="Saving app icon...")
        (app_output_dir / ICON_FILENAME).write_bytes(icon_data)

        if is_local_file:
            update_build_state(build_id, stage="Preparing assets", progress=20, message="Extracting uploaded assets...")
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

            # Use standard file URL (CORS is now handled by MainActivity injection)
            final_url = f"file:///android_asset/{relative_path_str}"
            print(f"[BUILDER] Local asset mode. Launch URL: {final_url}")
            update_build_state(build_id, progress=25, message="Assets extracted successfully")
        else:
            final_url = main_url
            update_build_state(build_id, progress=25, message="Using remote URL")

        update_build_state(build_id, stage="Configuring project", progress=35, message="Generating configuration...")
        conf_path = app_output_dir / CONF_FILENAME
        write_conf(app_id, name, conf_path)

        update_build_state(build_id, stage="Configuring project", progress=45, message="Applying configuration to project...")
        run_command(["bash", str(MAKE_SH_PATH), "apply_config", str(conf_path)], cwd=BASE_DIR)

        update_build_state(build_id, stage="Patching source code", progress=55, message="Injecting features...")
        # Call our safe patcher
        patch_source_code(app_id)

        update_build_state(build_id, stage="Building APK", progress=60, message="Compiling Android project...")
        print("[BUILDER] Starting APK assembly...")
        run_command(["bash", str(MAKE_SH_PATH), "apk"], cwd=BASE_DIR, output_target_dir=app_output_dir)

        update_build_state(build_id, stage="Finalizing", progress=95, message="Verifying APK file...")
        final_apk = app_output_dir / f"{app_id}.apk"
        if not final_apk.exists():
            raise FileNotFoundError(f"APK not found at {final_apk}")

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
    app_id = data.get("app_id")
    name = data.get("name")
    icon_file = data.get("icon")
    main_url = data.get("main_url")
    zip_file = data.get("zip_file")

    if not all([app_id, name, icon_file]):
        raise RuntimeError("Missing required fields (ID, Name, or Icon).")
    if not zip_file and not main_url:
        raise RuntimeError("You must provide either a Website URL or a Zip file.")

    build_id = str(uuid.uuid4())
    with build_states_lock:
        build_states[build_id] = {
            "status": "in_progress",
            "stage": "Starting",
            "progress": 0,
            "message": "Build request received..."
        }

    build_data = {
        "app_id": app_id,
        "name": name,
        "icon_data": await icon_file.read(),
        "main_url": main_url,
        "zip_data": await zip_file.read() if zip_file else None
    }

    threading.Thread(target=execute_build_async, args=(build_id, build_data), daemon=True).start()
    return {"build_id": build_id, "message": "Build started"}

@get("/build-progress/{build_id:str}")
async def stream_build_progress(build_id: str) -> Stream:
    """Stream build progress using raw SSE format to support named events."""
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
                # Standard update
                event_data = json.dumps({
                    "status": current_state.get("status", "in_progress"),
                    "stage": current_state.get("stage", "Unknown"),
                    "progress": current_state.get("progress", 0),
                    "message": current_state.get("message", "")
                })
                yield f"data: {event_data}\n\n"
                last_state = current_state

            if current_state.get("status") == "complete":
                # CRITICAL: Send specific 'complete' event for frontend
                yield f"event: complete\ndata: {json.dumps({'build_id': build_id})}\n\n"
                break

            if current_state.get("status") == "error":
                yield f"event: error\ndata: {json.dumps({'error': current_state.get('error', 'Unknown error')})}\n\n"
                break

            await asyncio.sleep(0.5)

    return Stream(event_generator(), media_type="text/event-stream")

@get("/download-apk/{build_id:str}")
async def download_apk(build_id: str) -> File:
    with build_states_lock:
        if build_id not in build_states: raise RuntimeError("Invalid build ID")
        state = build_states[build_id]
        if state.get("status") != "complete": raise RuntimeError("Build not complete")
        apk_path = state.get("apk_path")
        apk_filename = state.get("apk_filename", "app_release.apk")

    if not apk_path or not Path(apk_path).exists(): raise RuntimeError("APK file not found")
    return File(path=Path(apk_path), filename=apk_filename, media_type="application/vnd.android.package-archive")

# --- SERVER ---
cors_config = CORSConfig(allow_origins=["*"], allow_headers=["*"], allow_methods=["GET", "POST"])
app = Litestar(route_handlers=[build_apk, stream_build_progress, download_apk], cors_config=cors_config)

# Fix "Address already in use"
class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    import uvicorn
    os.chdir(WEB_DIR)

    def serve_front():
        handler = http.server.SimpleHTTPRequestHandler
        # Use Reusable Server
        with ReusableTCPServer(("", 8001), handler) as httpd:
            print(f"[FRONTEND] Server started at http://localhost:8001")
            httpd.serve_forever()

    threading.Thread(target=serve_front, daemon=True).start()
    print(f"[BACKEND] API Server started at http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")
