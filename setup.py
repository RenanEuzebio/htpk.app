import subprocess
import sys
import os
from pathlib import Path

# Configuration
BASE_DIR = Path(__file__).parent.absolute()
ANDROID_DIR = BASE_DIR / "android_source"
DEPENDENCIES_DIR = BASE_DIR / "dependencies"
MAKE_SH_PATH = BASE_DIR / "make.sh"

def run_command(command: list[str], cwd: Path) -> None:
    try:
        if str(MAKE_SH_PATH) in command:
             subprocess.run(["chmod", "+x", str(MAKE_SH_PATH)])

        env = os.environ.copy()
        # Tell make.sh where the source is and where to put dependencies
        env["ANDROID_PROJECT_ROOT"] = str(ANDROID_DIR)
        env["DEPENDENCIES_ROOT"] = str(DEPENDENCIES_DIR)

        print(f"[SETUP] Executing: {' '.join(command)}")
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
    except subprocess.CalledProcessError:
        print(f"\n[SETUP] Error occurred during setup.")
        sys.exit(1)

def main():
    print("=== HTPK INITIALIZATION ===")
    
    # Create directories
    DEPENDENCIES_DIR.mkdir(exist_ok=True)
    
    if not ANDROID_DIR.exists():
        print(f"Error: 'android_source' folder missing at {ANDROID_DIR}")
        return

    # 1. Download Dependencies (Runs in root, pointing to deps folder)
    run_command(["bash", str(MAKE_SH_PATH), "install_deps"], cwd=BASE_DIR)
    
    # 2. Generate Keystore (Runs in android_source because it needs to see app/)
    run_command(["bash", str(MAKE_SH_PATH), "keygen"], cwd=ANDROID_DIR)
    
    print("\n=== SETUP COMPLETE ===")
    print("You can now run 'python app.py'")

if __name__ == "__main__":
    main()
