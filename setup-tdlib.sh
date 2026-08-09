#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME="$ROOT/.runtime"
INSTALL="$RUNTIME/tdlib"
SOURCE="$INSTALL/source"
JDK="$INSTALL/jdk"
LIB="$INSTALL/lib"
OPENSSL11="$INSTALL/openssl11"
JAR="$INSTALL/telegram-files.jar"
ENV_FILE="$RUNTIME/tdlib.env"
LIBS_ARCHIVE="$RUNTIME/tdlib-libs-1.15.0.zip"
OPENSSL11_DEB="$RUNTIME/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb"

mkdir -p "$INSTALL" "$LIB"
for command_name in git curl unzip tar dpkg-deb strings; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Missing command: $command_name" >&2
        exit 2
    fi
done

if [ ! -d "$SOURCE/.git" ]; then
    git clone --depth 1 --branch 0.1.15 https://github.com/jarvis2f/telegram-files.git "$SOURCE"
fi

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64)
        ZULU_ARCH="x64"
        LIB_ARCH="linux_x64"
        ;;
    aarch64|arm64)
        ZULU_ARCH="aarch64"
        LIB_ARCH="linux_arm64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH" >&2
        exit 2
        ;;
esac

if [ ! -x "$JDK/bin/java" ]; then
    JDK_ARCHIVE="$RUNTIME/zulu-jdk23-linux-${ZULU_ARCH}.tar.gz"
    if [ ! -f "$JDK_ARCHIVE" ]; then
        curl -fL "https://cdn.azul.com/zulu/bin/zulu23.32.11-ca-jdk23.0.2-linux_${ZULU_ARCH}.tar.gz" -o "$JDK_ARCHIVE"
    fi
    rm -rf "$JDK"
    mkdir -p "$JDK"
    tar -xzf "$JDK_ARCHIVE" --strip-components=1 -C "$JDK"
fi

if [ ! -f "$LIB/libtdjni.so" ]; then
    if [ ! -f "$LIBS_ARCHIVE" ]; then
        curl -fL "https://github.com/p-vorobyev/spring-boot-starter-telegram/releases/download/1.15.0/libs.zip" -o "$LIBS_ARCHIVE"
    fi
    EXTRACT="$RUNTIME/tdlib-libs-extract"
    rm -rf "$EXTRACT"
    mkdir -p "$EXTRACT"
    unzip -q "$LIBS_ARCHIVE" -d "$EXTRACT"
    FOUND="$(find "$EXTRACT" -type f -path "*/${LIB_ARCH}/libtdjni.so" -print -quit)"
    if [ -z "$FOUND" ]; then
        echo "libtdjni.so for $LIB_ARCH was not found." >&2
        exit 2
    fi
    cp "$FOUND" "$LIB/libtdjni.so"
    rm -rf "$EXTRACT"
fi

# TDLib 1.15 Linux binaries require the OpenSSL 1.1.1 ABI. Keep it isolated
# from the host OpenSSL instead of downgrading system libraries.
if [ ! -f "$OPENSSL11/usr/lib/x86_64-linux-gnu/libcrypto.so.1.1" ]; then
    if [ "$LIB_ARCH" != "linux_x64" ]; then
        echo "Portable OpenSSL 1.1.1 is currently packaged only for linux_x64." >&2
        exit 2
    fi
    if [ ! -f "$OPENSSL11_DEB" ]; then
        curl -fL \
            "https://security.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb" \
            -o "$OPENSSL11_DEB"
    fi
    mkdir -p "$OPENSSL11"
    dpkg-deb -x "$OPENSSL11_DEB" "$OPENSSL11"
fi
OPENSSL11_LIB="$OPENSSL11/usr/lib/x86_64-linux-gnu"
if ! strings "$OPENSSL11_LIB/libcrypto.so.1.1" | grep -q '^OPENSSL_1_1_1'; then
    echo "Portable libcrypto does not provide OPENSSL_1_1_1." >&2
    exit 2
fi

if [ ! -f "$JAR" ]; then
    export JAVA_HOME="$JDK"
    export PATH="$JDK/bin:$PATH"
    chmod +x "$SOURCE/api/gradlew"
    "$SOURCE/api/gradlew" -p "$SOURCE/api" shadowJar
    cp "$SOURCE/api/build/libs/telegram-files.jar" "$JAR"
fi

if [ ! -f "$ENV_FILE" ]; then
    API_ID="$(sed -n 's/^[[:space:]]*TELEGRAM_API_ID=\([0-9][0-9]*\)[[:space:]]*$/\1/p' "$SOURCE/.github/workflows/ci.yml" | head -1)"
    API_HASH="$(sed -n 's/^[[:space:]]*TELEGRAM_API_HASH=\([0-9a-fA-F]*\)[[:space:]]*$/\1/p' "$SOURCE/.github/workflows/ci.yml" | head -1)"
    if [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
        echo "Could not resolve Telegram API credentials from upstream CI." >&2
        exit 2
    fi
    umask 077
    printf 'TELEGRAM_API_ID=%s\nTELEGRAM_API_HASH=%s\nTDLIB_JAVA=%s\nTDLIB_JAR_PATH=%s\nTDLIB_LIBRARY_PATH=%s\nTDLIB_DATA_ROOT=%s\nLD_LIBRARY_PATH=%s\n' \
        "$API_ID" "$API_HASH" "$JDK/bin/java" "$JAR" "$LIB" "$INSTALL/data" "$OPENSSL11_LIB" > "$ENV_FILE"
elif ! grep -q '^LD_LIBRARY_PATH=' "$ENV_FILE"; then
    printf 'LD_LIBRARY_PATH=%s\n' "$OPENSSL11_LIB" >> "$ENV_FILE"
fi

"$JDK/bin/java" -version
echo "TDLib backend artifacts are ready in $INSTALL"
echo "Start: python3 tdlib_backend.py start"
