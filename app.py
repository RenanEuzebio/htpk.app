import os
import subprocess
import sys
import re
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
    """Runs a shell command and streams output in real-time to the terminal."""
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

        if process.stdout:
            for line in process.stdout:
                print(line, end="")
                sys.stdout.flush()

        return_code = process.wait()

        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)

    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed with return code {e.returncode}"
        print(f"\n[BUILDER] ERROR: {error_msg}")
        raise RuntimeError(error_msg)

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

def patch_source_code(app_id: str) -> None:
    """
    Scans all Java files and enforces the correct package name and bug fixes.
    This fixes errors where manual copy-pasting reverts the package to 'com.myexample'.
    """
    java_files = list(BASE_DIR.glob("app/src/main/java/**/*.java"))
    
    print(f"[BUILDER] Enforcing package 'com.{app_id}.webtoapk' on {len(java_files)} source files...")

    for file_path in java_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            original_content = content

            # 1. Force Package Name to match App ID
            # Replaces 'package com.ANYTHING.webtoapk;' with 'package com.{app_id}.webtoapk;'
            content = re.sub(
                r'package\s+com\.[a-zA-Z0-9_]+\.webtoapk;', 
                f'package com.{app_id}.webtoapk;', 
                content
            )

            # 2. Fix 'MainActivity.java' specific bugs
            if file_path.name == "MainActivity.java":
                # Fix the LOCATION_PERMISSION_REQUEST_CODE bug
                broken_code = 'LOCATION_PERMISSION_REQUEST_CODE = "";'
                fixed_code = 'LOCATION_PERMISSION_REQUEST_CODE = 1001;'
                if broken_code in content:
                    content = content.replace(broken_code, fixed_code)

            # Only write to disk if changes were made to save IO
            if content != original_content:
                file_path.write_text(content, encoding="utf-8")
                
        except Exception as e:
            print(f"[BUILDER] Warning: Failed to patch {file_path.name}: {e}")

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
        # 1. Save Icon
        icon_data = await icon_file.read()
        (BASE_DIR / ICON_FILENAME).write_bytes(icon_data)

        # 2. Write Config
        write_conf(app_id, name, main_url)

        # 3. Generate Key (if missing)
        if not (BASE_DIR / "app/my-release-key.jks").exists():
            print("[BUILDER] Generating Keystore...")
            run_command(["bash", str(MAKE_SH_PATH), "keygen"], cwd=BASE_DIR)

        # 4. Clean & Apply Config
        run_command(["bash", str(MAKE_SH_PATH), "clean"], cwd=BASE_DIR)
        run_command(["bash", str(MAKE_SH_PATH), "apply_config"], cwd=BASE_DIR)

        # 5. Auto-Patch Source Code (Fixes Package Name & Bugs)
        patch_source_code(app_id)

        # 6. Build APK
        print("[BUILDER] Building APK...")
        run_command(["bash", str(MAKE_SH_PATH), "apk"], cwd=BASE_DIR)

        # 7. Locate Result
        expected_apk = BASE_DIR / f"{app_id}.apk"
        if not expected_apk.exists():
            raise FileNotFoundError(f"Build finished but {expected_apk.name} was not found.")

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
