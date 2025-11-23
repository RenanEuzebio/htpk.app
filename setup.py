import subprocess
import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()
SCRIPTS_DIR = BASE_DIR / "build_scripts"
ANDROID_DIR = BASE_DIR / "android_source"
MAKE_SH_PATH = SCRIPTS_DIR / "make.sh"

def run_command(command: list[str], cwd: Path) -> None:
    try:
        if str(MAKE_SH_PATH) in command:
             subprocess.run(["chmod", "+x", str(MAKE_SH_PATH)])

        # Inject path for make.sh to find the android project
        env = os.environ.copy()
        env["ANDROID_PROJECT_ROOT"] = str(ANDROID_DIR)

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
    
    if not ANDROID_DIR.exists():
        print("Error: 'android_source' directory not found. Please organize your files first.")
        return

    # 1. Download Dependencies
    run_command(["bash", str(MAKE_SH_PATH), "install_deps"], cwd=SCRIPTS_DIR)
    
    # 2. Generate Keystore
    run_command(["bash", str(MAKE_SH_PATH), "keygen"], cwd=SCRIPTS_DIR)
    
    print("\n=== SETUP COMPLETE ===")
    print("You can now run 'python app.py'")

if __name__ == "__main__":
    main()