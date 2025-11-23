# HTPK - Website-to-APK Builder

A minimal, high-speed tool to convert any website into an Android APK. It runs a local web interface and a high-performance API backend from a single command.

## Features

* **Zero-Config:** One command starts both the UI and the build server.
* **Fast:** Powered by [Litestar](https://litestar.dev/) and highly optimized build scripts.
* **Smart:** Auto-patches Android source code to fix package names and permissions instantly.
* **Resilient:** Automatically downloads Java 17, Android SDK, and dependencies if missing.

## Prerequisites

* **OS:** Linux or WSL2 (Windows Subsystem for Linux).
* **Python:** 3.12+
* **Package Manager:** `uv` (Recommended) or `pip`.

## Quick Start

### 1. Installation
Clone the repository and install dependencies:

```bash
# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install litestar uvicorn python-multipart
