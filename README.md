## HTPK - Website-to-APK Builder

A minimal, high-speed web interface tool to convert any static HTML into an Android APK. It runs from the press of a button.

-----

## Quick Start

Follow these three steps to get your build server and web interface running:

### 1\. Installation

First, clone your repository and install the Python dependencies using `uv` (recommended):

```bash
# Clone and enter the directory
git clone <your-repo-url>
cd htpk.app/

# Create environment and install Litestar/Uvicorn
uv venv
source .venv/bin/activate
uv pip install litestar uvicorn python-multipart
```

### 2\. Project Setup (One-Time Run)

Run the dedicated setup script once. **This step downloads large build dependencies** (Java 17 JDK and Android Command Line Tools) and generates your signing key.

```bash
python setup.py
```

### 3\. Run the Builder

This single command starts both the **Backend API** (on port 8000) and the **Frontend UI** (on port 8001).

```bash
python app.py
```

-----

## Usage

1.  Open your web browser and go to: **[http://localhost:8001](https://www.google.com/search?q=http://localhost:8001)**.
2.  Fill in the App ID, App Name, Website URL, and upload your icon.
3.  Click **Build APK**.
4.  The build status and logs will appear in the terminal, and the final APK will download automatically. The first run always takes a couple minutes, subsequent builds will be much faster (between 5 and 25 seconds).

-----

## Project Components

  * `app.py`: The main script that runs the web interface and the build API.
  * `setup.py`: Used once to check and download required Java/Android tools and generate the keystore.
  * `make.sh`: Handles the low-level Android build execution via Gradle.
  * `index.html`: The standalone web interface.
