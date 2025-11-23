# HTPK (Online Static Site to APK Converter)

A minimal, high-speed tool to convert any website into an Android APK. It uses a **Litestar** backend to orchestrate the build process and a simple HTML frontend for input.

## Features

* **Minimalist:** Stripped down logic for maximum build speed.
* **Fast API:** Powered by [Litestar](https://litestar.dev/).
* **Automatic Dependency Handling:** Automatically downloads Java 17 and Android SDK command-line tools if they are missing.
* **Native Fixes:** Includes automatic patching for common permission bugs in the generated Android source.

## Prerequisites

* **OS:** Linux or WSL2 (Windows Subsystem for Linux).
* **Python:** 3.12+
* **Package Manager:** [uv](https://github.com/astral-sh/uv) (Recommended) or pip.

## Installation

1.  **Clone the repository** and enter the directory:
    ```bash
    git clone <your-repo-url>
    cd website-to-apk
    ```

2.  **Initialize environment and install dependencies using `uv`:**
    ```bash
    uv venv
    source .venv/bin/activate
    uv pip install litestar uvicorn python-multipart
    ```

3.  **Verify Permissions:**
    Ensure the build script is executable:
    ```bash
    chmod +x make.sh
    ```

## Usage

You need to run two separate terminal processes.

### Terminal 1: The Backend
This starts the API server on port **8000**.
```bash
source .venv/bin/activate
litestar run
