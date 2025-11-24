#!/usr/bin/env bash
set -eu

# --- PATH CONFIGURATION ---
PROJECT_ROOT="${ANDROID_PROJECT_ROOT:-$PWD/android_source}"
DEPS_ROOT="${DEPENDENCIES_ROOT:-$PWD/dependencies}"
OUTPUT_DEST="${OUTPUT_DIR:-$PWD/output_apks}"

# --- ENV SETUP ---
# 1. Android SDK
export ANDROID_HOME="$DEPS_ROOT/cmdline-tools"

# 2. Java
export JAVA_HOME="$DEPS_ROOT/jvm/jdk-17.0.2"

# 3. Gradle (Local Installation)
export GRADLE_HOME="$DEPS_ROOT/gradle/gradle-7.4"

# 4. Gradle Global Cache (Redirected to dependencies)
export GRADLE_USER_HOME="$DEPS_ROOT/.gradle-cache"

# 5. Update PATH
export PATH="$JAVA_HOME/bin:$GRADLE_HOME/bin:$PATH"

# Color definitions
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

INFO="CN=Developer, OU=Organization, O=Company, L=City, S=State, C=US"

log() { echo -e "${GREEN}[+]${NC} $1"; }
info() { echo -e "${BLUE}[*]${NC} $1"; }
error() { echo -e "${RED}[!]${NC} $1"; exit 1; }

# Ensure we operate in the project root for build context
if [ ! -d "$PROJECT_ROOT" ]; then
    if [[ "$1" != "install_deps" ]]; then
         error "Android Source directory not found at: $PROJECT_ROOT"
    fi
else
    cd "$PROJECT_ROOT"
fi

try() {
    if ! "$@"; then
        error "Command failed: $*"
    fi
}

# --- DEPENDENCY MANAGEMENT ---

get_tools() {
    info "Downloading Android Command Line Tools..."
    case "$(uname -s)" in
        Linux*)     os_type="linux";;
        Darwin*)    os_type="mac";;
        *)          error "Unsupported OS";;
    esac
    
    mkdir -p "$ANDROID_HOME"
    
    local tmp_dir=$(mktemp -d)
    pushd "$tmp_dir" > /dev/null
    
    wget -q --show-progress "https://dl.google.com/android/repository/commandlinetools-${os_type}-11076708_latest.zip" -O cmdline-tools.zip
    unzip -q cmdline-tools.zip
    
    mkdir -p "$ANDROID_HOME/latest"
    mv cmdline-tools/* "$ANDROID_HOME/latest/"
    
    popd > /dev/null
    rm -rf "$tmp_dir"

    info "Accepting licenses..."
    yes | "$ANDROID_HOME/latest/bin/sdkmanager" --sdk_root="$ANDROID_HOME" --licenses > /dev/null 2>&1 || true
    
    info "Installing build tools..."
    "$ANDROID_HOME/latest/bin/sdkmanager" --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-33" "build-tools;33.0.2" "build-tools;30.0.3"
}

get_java() {
    local install_dir="$DEPS_ROOT/jvm"
    local jdk_url="https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz"

    if [ -d "$install_dir/jdk-17.0.2" ]; then return 0; fi

    local tmp_dir=$(mktemp -d)
    pushd "$tmp_dir" > /dev/null
    
    info "Downloading Java 17..."
    wget -q --show-progress "$jdk_url" -O openjdk.tar.gz
    
    info "Unpacking Java..."
    mkdir -p "$install_dir"
    tar xf openjdk.tar.gz
    mv jdk-17.0.2 "$install_dir/"
    
    popd > /dev/null
    rm -rf "$tmp_dir"
}

get_gradle() {
    local install_dir="$DEPS_ROOT/gradle"
    local gradle_url="https://services.gradle.org/distributions/gradle-7.4-bin.zip"

    if [ -d "$install_dir/gradle-7.4" ]; then return 0; fi

    local tmp_dir=$(mktemp -d)
    pushd "$tmp_dir" > /dev/null
    
    info "Downloading Gradle 7.4..."
    wget -q --show-progress "$gradle_url" -O gradle.zip
    
    info "Unpacking Gradle..."
    mkdir -p "$install_dir"
    unzip -q gradle.zip
    mv gradle-7.4 "$install_dir/"
    
    popd > /dev/null
    rm -rf "$tmp_dir"
}

install_deps() {
    mkdir -p "$DEPS_ROOT"
    mkdir -p "$DEPS_ROOT/.gradle-cache" # Ensure global cache dir exists
    mkdir -p "$DEPS_ROOT/.gradle"       # Ensure project cache dir exists
    
    get_java
    get_gradle
    
    if [ ! -f "$ANDROID_HOME/latest/bin/sdkmanager" ]; then
        get_tools
    fi
    
    log "All dependencies installed locally."
}

# --- BUILD COMMANDS ---

ensure_deps() {
    if [ ! -x "$JAVA_HOME/bin/java" ]; then error "Java 17 not found in dependencies. Run 'python setup.py' first."; fi
    if [ ! -x "$GRADLE_HOME/bin/gradle" ]; then error "Gradle not found in dependencies. Run 'python setup.py' first."; fi
    [ -d "$ANDROID_HOME" ] || error "Android SDK not found. Run 'python setup.py' first."
}

apk() {
    ensure_deps
    [ ! -f "app/my-release-key.jks" ] && error "Keystore not found."
    rm -f app/build/outputs/apk/release/app-release.apk
    
    info "Building APK..."
    
    # Force project-specific cache to dependencies/.gradle
    try gradle assembleRelease --quiet --project-cache-dir "$DEPS_ROOT/.gradle"
    
    if [ -f "app/build/outputs/apk/release/app-release.apk" ]; then
        log "APK Built Successfully!"
        cp "app/build/outputs/apk/release/app-release.apk" "$OUTPUT_DEST/$appname.apk"
        log "Saved to $OUTPUT_DEST/$appname.apk"
    else
        error "Build failed"
    fi
}

apply_config() {
    local config_file="${1:-webapk.conf}"
    [ ! -f "$config_file" ] && return
    
    export CONFIG_DIR="$(dirname "$config_file")"
    info "Applying config..."
    
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        
        case "$key" in
            "id") chid "$value" ;;
            "name") rename "$value" ;;
            "icon") set_icon "$value" ;;
            "scripts") ;; 
            *) set_var "$key = $value" ;;
        esac
    done < "$config_file"
}

set_var() {
    local java_file="app/src/main/java/com/$appname/webtoapk/MainActivity.java"
    if [ ! -f "$java_file" ]; then
        java_file=$(find app/src/main/java -name MainActivity.java | head -n 1)
    fi
    
    local pattern="$@"
    local var_name="${pattern%% =*}"
    local new_value="${pattern#*= }"

    if [ -z "$java_file" ] || [ ! -f "$java_file" ]; then return; fi
    if ! grep -q "$var_name *= *.*;" "$java_file"; then return; fi
    if [[ ! "$new_value" =~ ^(true|false)$ ]]; then new_value="\"$new_value\""; fi
    
    local tmp_file=$(mktemp)
    awk -v var="$var_name" -v val="$new_value" '
    {
        if (!found && $0 ~ var " *= *.*;" ) {
            match($0, "^.*" var " *=")
            before = substr($0, RSTART, RLENGTH)
            print before " " val ";"
            found = 1
        } else {
            print $0
        }
    }' "$java_file" > "$tmp_file"
    mv "$tmp_file" "$java_file"
}

keygen() {
    if [ ! -f "app/my-release-key.jks" ]; then
        info "Generating keystore..."
        try keytool -genkey -v -keystore app/my-release-key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias my -storepass '123456' -keypass '123456' -dname '$INFO'
    fi
}

clean() {
    ensure_deps
    info "Cleaning build files..."
    # Clean build output
    try rm -rf app/build
    # Clean project cache in dependencies
    try rm -rf "$DEPS_ROOT/.gradle"
}

chid() {
    [ -z "$1" ] && return
    [[ ! $1 =~ ^[a-zA-Z][a-zA-Z0-9_]*$ ]] && error "Invalid App ID"
    [ "$1" = "$appname" ] && return
    
    try find . -type f \( -name '*.gradle' -o -name '*.java' -o -name '*.xml' \) -exec sed -i "s/com\.\([a-zA-Z0-9_]*\)\.webtoapk/com.$1.webtoapk/g" {} +
    
    local current_dir=$(find app/src/main/java/com -maxdepth 1 -mindepth 1 -type d -not -name "$1" | head -n 1)
    if [ -n "$current_dir" ] && [ -d "$current_dir" ]; then
        if [ "$current_dir" != "app/src/main/java/com/$1" ]; then
            try mv "$current_dir" "app/src/main/java/com/$1"
        fi
    fi
    appname=$1
}

rename() {
    local new_name="$*"
    find app/src/main/res/values* -name "strings.xml" | while read xml_file; do
        escaped_name=$(echo "$new_name" | sed 's/[\/&]/\\&/g')
        try sed -i "s|<string name=\"app_name\">[^<]*</string>|<string name=\"app_name\">$escaped_name</string>|" "$xml_file"
    done
}

set_icon() {
    local icon_path="$@"
    local dest_file="app/src/main/res/mipmap/ic_launcher.png"
    [ -z "$icon_path" ] && return
    if [ -n "${CONFIG_DIR:-}" ] && [[ "$icon_path" != /* ]]; then icon_path="$CONFIG_DIR/$icon_path"; fi
    if [ -f "$icon_path" ]; then try cp "$icon_path" "$dest_file"; fi
}

get_tools() { return 0; } 
get_java() { return 0; }
install_deps() { return 0; }

appname=$(grep -Po '(?<=applicationId "com\.)[^.]*' app/build.gradle || echo "unknown")

if [ $# -eq 0 ]; then exit 1; fi
eval $@