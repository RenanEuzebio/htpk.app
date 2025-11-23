import os
import subprocess
import sys
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
    """Runs a shell command and streams output in real-time."""
    try:
        # Ensure make.sh is executable
        if str(MAKE_SH_PATH) in command:
             os.chmod(MAKE_SH_PATH, 0o755)

        print(f"[BUILDER] Executing: {' '.join(command)}")
        
        # Use Popen to stream output line by line
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr into stdout
            text=True,
            bufsize=1, # Line buffered
            # Ensure the script doesn't hang on prompts by simulating "yes" if needed
            # (though for 'read' commands in bash without a pipe, it might still be tricky, 
            # but usually they default or fail fast without TTY)
        )

        # Print output as it happens
        if process.stdout:
            for line in process.stdout:
                print(line, end="") # Line already has newline
                sys.stdout.flush()  # Force write to terminal immediately

        # Wait for completion
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

def apply_java_bug_fix() -> None:
    java_files = list(BASE_DIR.glob("app/src/main/java/**/MainActivity.java"))
    
    if not java_files:
        raise FileNotFoundError("MainActivity.java not found. 'apply_config' likely failed.")
    
    target_file = java_files[0]
    content = target_file.read_text(encoding="utf-8")
    
    broken_code = 'LOCATION_PERMISSION_REQUEST_CODE = "";'
    fixed_code = 'LOCATION_PERMISSION_REQUEST_CODE = 1001;'
    
    if broken_code in content:
        new_content = content.replace(broken_code, fixed_code)
        target_file.write_text(new_content, encoding="utf-8")
        print("[BUILDER] Bug fix applied.")

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
            # The 'yes' command pipes 'y' into make.sh in case it asks for confirmation
            # However, since we run run_command directly, we rely on make.sh logic.
            # If make.sh prompts for input, it might still hang. 
            # For purely automated environments, prompts should be removed from .sh
            run_command(["bash", str(MAKE_SH_PATH), "keygen"], cwd=BASE_DIR)

        # 4. Clean & Apply Config
        run_command(["bash", str(MAKE_SH_PATH), "clean"], cwd=BASE_DIR)
        run_command(["bash", str(MAKE_SH_PATH), "apply_config"], cwd=BASE_DIR)

        # 5. Apply Code Fix
        apply_java_bug_fix()

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
