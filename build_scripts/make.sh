#!/usr/bin/env bash
set -eu

# --- PATH CONFIGURATION ---
# Defaults to current directory if env var not set (fallback)
PROJECT_ROOT="${ANDROID_PROJECT_ROOT:-$PWD/../android_source}"
OUTPUT_DEST="${OUTPUT_DIR:-$PWD/../output_apks}"

# Color definitions
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m'

# Info for keystore generation
INFO="CN=Developer, OU=Organization, O=Company, L=City, S=State, C=US"

log() { echo -e "${GREEN}[+]${NC} $1"; }
info() { echo -e "${BLUE}[*]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[!]${NC} $1"; exit 1; }

# Ensure we are operating in the project root for Gradle commands
cd "$PROJECT_ROOT" || error "Could not find Android Project Root at $PROJECT_ROOT"

try() {
    local log_file=$(mktemp)
    if [ $# -eq 1 ]; then
        if ! eval "$1" &> "$log_file"; then
            echo -e "${RED}[!]${NC} Failed: $1"
            cat "$log_file"
            rm -f "$log_file"
            exit 1
        fi
    else
        if ! "$@" &> "$log_file"; then
            echo -e "${RED}[!]${NC} Failed: $*"
            cat "$log_file"
            rm -f "$log_file"
            exit 1
        fi
    fi
    rm -f "$log_file"
}

set_var() {
    local java_file="app/src/main/java/com/$appname/webtoapk/MainActivity.java"
    [ ! -f "$java_file" ] && error "MainActivity.java not found"
    
    local pattern="$@"
    local var_name="${pattern%% =*}"
    local new_value="${pattern#*= }"

    if ! grep -q "$var_name *= *.*;" "$java_file"; then
        return 
    fi

    if [[ ! "$new_value" =~ ^(true|false)$ ]]; then
        new_value="\"$new_value\""
    fi
    
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
    log "Updated $var_name"
}

apply_config() {
    local config_file="${1:-webapk.conf}"
    [ ! -f "$config_file" ] && return
    
    export CONFIG_DIR="$(dirname "$config_file")"
    info "Applying config: $config_file"
    
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

apk() {
    ensure_deps
    [ ! -f "app/my-release-key.jks" ] && error "Keystore not found."
    rm -f app/build/outputs/apk/release/app-release.apk
    
    info "Building APK..."
    try "./gradlew assembleRelease --quiet"
    
    if [ -f "app/build/outputs/apk/release/app-release.apk" ]; then
        log "APK Built Successfully!"
        # Copy to the output folder defined by Python
        cp "app/build/outputs/apk/release/app-release.apk" "$OUTPUT_DEST/$appname.apk"
        log "Saved to $OUTPUT_DEST/$appname.apk"
    else
        error "Build failed"
    fi
}

keygen() {
    if [ ! -f "app/my-release-key.jks" ]; then
        info "Generating keystore..."
        try "keytool -genkey -v -keystore app/my-release-key.jks -keyalg RSA -keysize 2048 -validity 10000 -alias my -storepass '123456' -keypass '123456' -dname '$INFO'"
    else
        log "Keystore already exists."
    fi
}

clean() {
    ensure_deps
    info "Cleaning build files..."
    try rm -rf app/build .gradle
    log "Clean completed"
}

chid() {
    [ -z "$1" ] && return
    [[ ! $1 =~ ^[a-zA-Z][a-zA-Z0-9_]*$ ]] && error "Invalid App ID"
    [ "$1" = "$appname" ] && return
    
    try "find . -type f \( -name '*.gradle' -o -name '*.java' -o -name '*.xml' \) -exec sed -i 's/com\.\([a-zA-Z0-9_]*\)\.webtoapk/com.$1.webtoapk/g' {} +"
    try "mv app/src/main/java/com/$appname app/src/main/java/com/$1"
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
    
    if [ -n "${CONFIG_DIR:-}" ] && [[ "$icon_path" != /* ]]; then
        icon_path="$CONFIG_DIR/$icon_path"
    fi
    
    if [ -f "$icon_path" ]; then
        try "cp \"$icon_path\" \"$dest_file\""
    fi
}

# --- DEPENDENCIES ---

export ANDROID_HOME="$PROJECT_ROOT/cmdline-tools"
export GRADLE_USER_HOME="$PROJECT_ROOT/.gradle-cache"

get_tools() {
    info "Downloading Android Command Line Tools..."
    case "$(uname -s)" in
        Linux*)     os_type="linux";;
        *)         error "Unsupported OS";;
    esac
    
    tmp_dir=$(mktemp -d)
    cd "$tmp_dir"
    try "wget -q --show-progress 'https://dl.google.com/android/repository/commandlinetools-${os_type}-11076708_latest.zip' -O cmdline-tools.zip"
    info "Extracting tools..."
    try "unzip -q cmdline-tools.zip"
    try "mkdir -p '$ANDROID_HOME/latest'"
    try "mv cmdline-tools/* '$ANDROID_HOME/latest/'"
    cd "$OLDPWD"
    rm -rf "$tmp_dir"

    info "Accepting licenses..."
    try "yes | '$ANDROID_HOME/latest/bin/sdkmanager' --sdk_root=$ANDROID_HOME --licenses"
    info "Installing components..."
    try "'$ANDROID_HOME/latest/bin/sdkmanager' --sdk_root=$ANDROID_HOME 'platform-tools' 'platforms;android-33' 'build-tools;33.0.2'" 
}

get_java() {
    local install_dir="$PROJECT_ROOT/jvm"
    local jdk_url="https://download.java.net/java/GA/jdk17.0.2/dfd4a8d0985749f896bed50d7138ee7f/8/GPL/openjdk-17.0.2_linux-x64_bin.tar.gz"

    if [ -d "$install_dir/jdk-17.0.2" ]; then return 0; fi

    local tmp_dir=$(mktemp -d)
    cd "$tmp_dir"
    info "Downloading Java 17..."
    try "wget -q --show-progress '$jdk_url' -O openjdk.tar.gz"
    info "Unpacking..."
    try "mkdir -p '$install_dir'"
    try "tar xf openjdk.tar.gz"
    try "mv jdk-17.0.2 '$install_dir/'"
    cd "$OLDPWD"
    rm -rf "$tmp_dir"
    export JAVA_HOME="$install_dir/jdk-17.0.2"
    export PATH="$JAVA_HOME/bin:$PATH"
}

check_and_find_java() {
    if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
        return 0
    fi
    if [ -d "$PROJECT_ROOT/jvm/jdk-17.0.2" ]; then
        export JAVA_HOME="$PROJECT_ROOT/jvm/jdk-17.0.2"
        export PATH="$JAVA_HOME/bin:$PATH"
        return 0
    fi
    return 1
}

install_deps() {
    if ! check_and_find_java; then get_java; fi
    if [ ! -d "$ANDROID_HOME" ]; then get_tools; fi
}

ensure_deps() {
    check_and_find_java || error "Java missing."
    [ -d "$ANDROID_HOME" ] || error "SDK missing."
}

# --- ENTRY ---
appname=$(grep -Po '(?<=applicationId "com\.)[^.]*' app/build.gradle)

if [ $# -eq 0 ]; then
    echo "Usage: $0 [install_deps|keygen|build|clean|apk|apply_config]"
    exit 1
fi

eval $@