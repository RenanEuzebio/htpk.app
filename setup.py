import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()
MAKE_SH_PATH = BASE_DIR / "make.sh"

def run_command(command: list[str], cwd: Path) -> None:
    """Runs a shell command and streams output."""
    try:
        if str(MAKE_SH_PATH) in command:
             subprocess.run(["chmod", "+x", str(MAKE_SH_PATH)])

        print(f"[SETUP] Executing: {' '.join(command)}")
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
    except subprocess.CalledProcessError:
        print(f"\n[SETUP] Error occurred during setup.")
        sys.exit(1)

def main():
    print("=== INITIALIZING PROJECT SETUP ===")
    
    # 1. Download Dependencies (Java, SDK)
    run_command(["bash", str(MAKE_SH_PATH), "install_deps"], cwd=BASE_DIR)
    
    # 2. Generate Keystore
    run_command(["bash", str(MAKE_SH_PATH), "keygen"], cwd=BASE_DIR)
    
    print("\n=== SETUP COMPLETE ===")
    print("You can now run 'litestar run' to start the app builder.")

if __name__ == "__main__":
    main()
