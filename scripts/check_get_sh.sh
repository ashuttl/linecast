#!/bin/sh
# Offline checks for get.sh.
#
#   sh scripts/check_get_sh.sh <dir holding a linecast wheel>
#
# get.sh runs with a PATH of stand-ins for linecast, uvx and pipx that
# record how they were called, so every dispatch and terminal branch can
# be asserted.  Then, with those stand-ins gone, the venv fallback runs
# against the wheel in the given directory, with pip pointed at that
# directory and no index, in a cache under a temp dir of our own.  Nothing
# reaches the network, the real cache, or /tmp/linecast.  Needs only sh,
# coreutils and python3.  Prints one line per check, TAP style, and exits
# non-zero when any check fails.
#
# GET_SH names the script under test (default: get.sh beside scripts/).
# The shell get.sh runs under is whatever `sh` on PATH resolves to.
set -u

here=$(cd "$(dirname "$0")" && pwd)
GET_SH=${GET_SH:-$here/../get.sh}
GET_SH=$(cd "$(dirname "$GET_SH")" && pwd)/$(basename "$GET_SH")
WHEEL_DIR=${1:-}
[ -n "$WHEEL_DIR" ] || { echo "usage: $0 <dir holding a linecast wheel>" >&2; exit 2; }
WHEEL_DIR=$(cd "$WHEEL_DIR" && pwd) || exit 2
for whl in "$WHEEL_DIR"/linecast-*.whl; do break; done
[ -f "$whl" ] || { echo "no linecast wheel in $WHEEL_DIR" >&2; exit 2; }
version=$(basename "$whl" | sed 's/^linecast-\([^-]*\)-.*/\1/')

work=$(mktemp -d "${TMPDIR:-/tmp}/check_get_sh.XXXXXX") || exit 2
trap 'rm -rf "$work"' EXIT
trap 'exit 1' HUP INT TERM   # dash skips the EXIT trap on a bare ^C
CALLS=$work/calls.log
fake=$work/fake      # linecast / uvx / pipx stand-ins
tools=$work/tools    # the utilities get.sh and pip need, and nothing else
mkdir -p "$fake" "$tools" "$work/tmp" "$work/home"
had_tmp_linecast=no; [ -e /tmp/linecast ] && had_tmp_linecast=yes

# ---------------------------------------------------------------- fixtures
for t in sh cat mkdir rm rmdir ls find touch mktemp id uname dirname basename \
         env grep sed wc head tail tr cut chmod ln true false sleep; do
    p=$(command -v "$t" 2>/dev/null) && ln -s "$p" "$tools/$t"
done
real_py=$(command -v python3) || { echo "python3 is required" >&2; exit 2; }
# python3 goes through a wrapper so an env var can bend `-m venv`:
# CHECK_BREAK_VENV makes it fail the way Debian without python3-venv does
# (a half-made venv and exit 1); CHECK_VENV_WITHOUT_PIP makes a venv that
# has no pip.  Anything else runs the real python.  get.sh runs python
# with -I, which the wrapper sets aside to match and hands back on exec.
cat > "$tools/python3" <<EOF
#!/bin/sh
iso=; if [ "\${1:-}" = -I ]; then iso=-I; shift; fi
if [ "\${1:-}" = -m ] && [ "\${2:-}" = venv ]; then
    if [ -n "\${CHECK_BREAK_VENV:-}" ]; then
        for d; do :; done
        mkdir -p "\$d/bin" && ln -sf "$real_py" "\$d/bin/python3" && ln -sf python3 "\$d/bin/python"
        echo "The virtual environment was not created successfully because ensurepip is not available." >&2
        exit 1
    fi
    if [ -n "\${CHECK_VENV_WITHOUT_PIP:-}" ]; then
        shift 2
        exec "$real_py" \$iso -m venv --without-pip "\$@"
    fi
fi
exec "$real_py" \$iso "\$@"
EOF
chmod +x "$tools/python3"

mkfake() {  # a stand-in that appends "name [arg] [arg] stdin=tty|notty" to CALLS
    cat > "$fake/$1" <<EOF
#!/bin/sh
{
    printf '%s' "$1"
    for a; do printf ' [%s]' "\$a"; done
    if [ -t 0 ]; then printf ' stdin=tty'; else printf ' stdin=notty'; fi
    printf '\n'
} >> "$CALLS"
EOF
    chmod +x "$fake/$1"
}

# get.sh the way curl delivers it: on stdin, arguments after -s.
cat > "$work/piped.sh" <<'EOF'
#!/bin/sh
cat "$GET_SH" | sh -s "$@"
EOF

# Run "$@" on a fresh pseudo-terminal that is its controlling terminal.
with_tty() {
    python3 - "$@" <<'EOF'
import os, pty, sys
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.argv[1], sys.argv[1:])
out = b""
while True:
    try:
        data = os.read(fd, 4096)
    except OSError:
        break
    if not data:
        break
    out += data
_, status = os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace").replace("\r", ""))
sys.exit(os.waitstatus_to_exitcode(status))
EOF
}

# Run "$@" in a new session with no controlling terminal at all (nohup is
# not enough: /dev/tty stays openable under it; setsid(1) is Linux-only).
without_tty() {
    python3 -c '
import os, sys
pid = os.fork()
if pid == 0:
    os.setsid()
    os.execvp(sys.argv[1], sys.argv[1:])
_, status = os.waitpid(pid, 0)
sys.exit(os.waitstatus_to_exitcode(status))' "$@" </dev/null
}

# ---------------------------------------------------------------- reporting
n=0 failed=0
ok()   { n=$((n+1)); printf 'ok %d - %s\n' "$n" "$1"; }
fail() { n=$((n+1)); failed=$((failed+1)); printf 'not ok %d - %s\n#   %s\n' "$n" "$1" "$2"; }
skip() { printf '# skip - %s\n' "$1"; }
is()   { if [ "$2" = "$3" ]; then ok "$1"; else fail "$1" "expected [$2] got [$3]"; fi; }
has()  { case "$3" in *"$2"*) ok "$1" ;; *) fail "$1" "expected to contain [$2] in: $3" ;; esac; }
lacks(){ case "$3" in *"$2"*) fail "$1" "did not expect [$2] in: $3" ;; *) ok "$1" ;; esac; }
exists() { if [ -e "$1" ] || [ -L "$1" ]; then echo yes; else echo no; fi; }
last_call() { tail -n 1 "$CALLS" 2>/dev/null; }
reset() { : > "$CALLS"; }

# ------------------------------------------------------------ 1. dispatch
# Every dispatch check runs without a terminal so the expected argv is the
# same everywhere: run() appends --print.
P=$fake:$tools
mkfake linecast
piped() { reset; without_tty env PATH="$P" GET_SH="$GET_SH" sh "$work/piped.sh" "$@"; }

piped; is "no arguments runs weather" "linecast [weather] [--print] stdin=notty" "$(last_call)"
piped sunshine; is "named command" "linecast [sunshine] [--print] stdin=notty" "$(last_call)"
piped -- --metric; is "bare flag maps to weather" "linecast [weather] [--metric] [--print] stdin=notty" "$(last_call)"
piped tides --station 8418150; is "arguments pass through" "linecast [tides] [--station] [8418150] [--print] stdin=notty" "$(last_call)"
piped -- --location "Westbrook, Maine"; is "arguments keep their spaces" "linecast [weather] [--location] [Westbrook, Maine] [--print] stdin=notty" "$(last_call)"
piped linecast --version; is "linecast itself takes its args bare" "linecast [--version] [--print] stdin=notty" "$(last_call)"
out=$(piped bogus 2>"$work/err"); rc=$?
is "unknown command exits 1" 1 "$rc"
is "unknown command runs nothing" "" "$(last_call)"
is "unknown command prints nothing on stdout" "" "$out"
has "unknown command explains on stderr" "nknown command: bogus" "$(cat "$work/err")"

# --------------------------------------------------------- 2. run() branches
reset; with_tty env PATH="$P" sh "$GET_SH" sunshine >/dev/null
is "stdin a tty: plain run" "linecast [sunshine] stdin=tty" "$(last_call)"
reset; with_tty env PATH="$P" GET_SH="$GET_SH" sh "$work/piped.sh" sunshine >/dev/null
is "stdin a pipe, /dev/tty available: stdin reclaimed" "linecast [sunshine] stdin=tty" "$(last_call)"
# no tty at all is what every check in section 1 exercised (--print appended)

# ------------------------------------------------------------- 3. uvx, pipx
mkfake uvx; mkfake pipx
piped sunshine; is "installed linecast wins over uvx and pipx" "linecast [sunshine] [--print] stdin=notty" "$(last_call)"
rm "$fake/linecast"
piped sunshine; is "uvx branch" "uvx [--quiet] [linecast] [sunshine] [--print] stdin=notty" "$(last_call)"
rm "$fake/uvx"
piped -- --metric; is "pipx branch" "pipx [run] [linecast] [weather] [--metric] [--print] stdin=notty" "$(last_call)"
rm "$fake/pipx"

# ----------------------------------------------------------- 4. venv fallback
cache=$work/cache; appdir=$cache/linecast; venv=$appdir/venv; stamp=$venv/.refreshed
piplog=$work/pip.log
# PATH has no linecast/uvx/pipx now; pip sees only the wheel dir and logs
# every install; the cache, home, tmp and pip config are all ours.  The
# knobs below are set around a call and put back after it.  CWD is the
# directory the piped run starts from, the harness's own by default.
P=$tools
XDG=$cache; OVERRIDE=; WHEELS=$WHEEL_DIR; BREAK=; NOPIP=; CWD=.
venv_run() {
    ( cd "$CWD" && without_tty env -i PATH="$P" GET_SH="$GET_SH" HOME="$work/home" TMPDIR="$work/tmp" \
        XDG_CACHE_HOME="$XDG" LINECAST_CACHE_DIR="$OVERRIDE" \
        PIP_NO_INDEX=1 PIP_FIND_LINKS="$WHEELS" PIP_CONFIG_FILE=/dev/null \
        PIP_CACHE_DIR="$work/pipcache" PIP_LOG="$piplog" PIP_DISABLE_PIP_VERSION_CHECK=1 \
        CHECK_BREAK_VENV="$BREAK" CHECK_VENV_WITHOUT_PIP="$NOPIP" \
        sh "$work/piped.sh" "$@" ) 2>"$work/err"
}
installs() { grep -c 'Successfully installed linecast' "$piplog" 2>/dev/null || echo 0; }
upgrades() { grep -c 'Requirement already satisfied: linecast' "$piplog" 2>/dev/null || echo 0; }
err() { cat "$work/err"; }
stale() { ! python3 -c 'import os, sys, time
sys.exit(time.time() - os.stat(sys.argv[1]).st_mtime >= 86400)' "$stamp" 2>/dev/null; }
runs() { if [ -x "$1/bin/python" ] && "$1/bin/python" -I -c 'import linecast' 2>/dev/null; then echo yes; else echo no; fi; }
# shellcheck disable=SC2012  # stat differs between GNU and BSD; ls does not
mode() { ls -ld "$1" | cut -c1-10; }

out=$(venv_run sunshine --version); rc=$?
is "first run exits 0" 0 "$rc"
has "first run prints the wheel's version" "linecast $version" "$out"
has "first run says it is installing" "nstalling" "$(err)"
is "venv lands under XDG_CACHE_HOME/linecast/venv" yes "$(runs "$venv")"
is "venv directory is private (0700)" "drwx------" "$(mode "$venv")"
is "cache dir is private (0700)" "drwx------" "$(mode "$appdir")"
is "one pip install" 1 "$(installs)"
is "refresh stamp written" yes "$(exists "$stamp")"
is "nothing left in TMPDIR" "" "$(ls -A "$work/tmp")"

size=$(wc -c < "$piplog")
out=$(venv_run moon --version)
has "second run prints the version" "linecast $version" "$out"
lacks "second run does not reinstall" "nstalling" "$(err)"
is "second run does not call pip" "$size" "$(wc -c < "$piplog")"

touch -t 202001010000 "$stamp"
out=$(venv_run sunshine --version)
has "stale stamp: still prints the version" "linecast $version" "$out"
is "stale stamp: pip upgrade attempted" 1 "$(upgrades)"
is "stale stamp: stamp refreshed" fresh "$(stale && echo stale || echo fresh)"

touch -t 202001010000 "$stamp"
mkdir "$work/badwheels"; printf 'not a wheel' > "$work/badwheels/linecast-99.0-py3-none-any.whl"
WHEELS=$work/badwheels
out=$(venv_run sunshine --version); rc=$?
WHEELS=$WHEEL_DIR
is "failed upgrade: exits 0" 0 "$rc"
has "failed upgrade: runs the installed version" "linecast $version" "$out"
has "failed upgrade: says so" "could not check" "$(err)"
is "failed upgrade: stamp refreshed anyway" fresh "$(stale && echo stale || echo fresh)"

rm -rf "${venv:?}/lib"
out=$(venv_run sunshine --version)
has "venv that cannot import linecast is rebuilt" "linecast $version" "$out"
is "rebuild ran pip install" 2 "$(installs)"

rm "$venv/bin/python3"; ln -s /nonexistent/python3 "$venv/bin/python3"
out=$(venv_run sunshine --version)
has "venv with a dangling python is rebuilt" "linecast $version" "$out"
is "dangling rebuild ran pip install" 3 "$(installs)"

# A pip install cut off before it wrote the console scripts: linecast
# imports, bin/sunshine is missing.
rm "$venv/bin/sunshine"
out=$(venv_run sunshine --version); rc=$?
is "venv without bin/sunshine: exits 0" 0 "$rc"
has "venv without bin/sunshine: rebuilt" "linecast $version" "$out"
is "venv without bin/sunshine: rebuild ran pip install" 4 "$(installs)"

# A linecast package where the user runs `curl | sh` from.  Without -I it
# makes a gutted venv pass the import probe, so the venv is never rebuilt
# and bin/sunshine fails on every run.
mkdir -p "$work/cwd/linecast"; : > "$work/cwd/linecast/__init__.py"
rm -rf "${venv:?}/lib"
CWD=$work/cwd
out=$(venv_run sunshine --version); rc=$?
is "linecast package in the cwd: gutted venv exits 0" 0 "$rc"
has "linecast package in the cwd: gutted venv is rebuilt" "nstalling" "$(err)"
has "linecast package in the cwd: prints the version" "linecast $version" "$out"
is "linecast package in the cwd: rebuild ran pip install" 5 "$(installs)"

# Stand-ins for venv, pip and ensurepip there too.  Without -I they run
# in place of the real modules.
for m in venv pip ensurepip; do
    printf 'import sys; sys.exit("PWNED: %s.py from the cwd")\n' "$m" > "$work/cwd/$m.py"
done
rm -rf "$appdir"
out=$(venv_run sunshine --version); rc=$?
CWD=.
is "python files in the cwd: exits 0" 0 "$rc"
lacks "python files in the cwd: none of them ran" "PWNED" "$(err)"
has "python files in the cwd: prints the version" "linecast $version" "$out"
is "python files in the cwd: a real venv was made" yes "$(runs "$venv")"

# An impostor venv: a symlink where the venv should be.  Nothing in it
# may run, and nothing may be written through it.
mkdir -p "$work/evil/bin"; printf '#!/bin/sh\necho PWNED\n' > "$work/evil/bin/sunshine"; chmod +x "$work/evil/bin/sunshine"
rm -rf "$venv"; ln -s "$work/evil" "$venv"
out=$(venv_run sunshine --version); rc=$?
is "symlinked venv: exits 0" 0 "$rc"
has "symlinked venv: refused" "refusing" "$(err)"
lacks "symlinked venv: impostor not run" "PWNED" "$out"
has "symlinked venv: throwaway venv used instead" "linecast $version" "$out"
is "symlinked venv: nothing written through the link" no "$(exists "$work/evil/pyvenv.cfg")"
is "symlinked venv: throwaway removed on exit" "" "$(ls -A "$work/tmp")"
rm "$venv"

rm -rf "$appdir"; ln -s "$work/evil" "$appdir"
out=$(venv_run sunshine --version)
has "symlinked cache dir: refused" "refusing" "$(err)"
lacks "symlinked cache dir: impostor not run" "PWNED" "$out"
has "symlinked cache dir: throwaway venv used" "linecast $version" "$out"
is "symlinked cache dir: nothing written through the link" no "$(exists "$work/evil/venv")"
rm "$appdir"

if [ "$(id -u)" = 0 ]; then
    mkdir -p "$venv/bin" && chown 12345 "$venv"
    out=$(venv_run sunshine --version)
    has "foreign-owned venv: refused" "refusing" "$(err)"
    has "foreign-owned venv: throwaway venv used" "linecast $version" "$out"
    is "foreign-owned venv: left alone" no "$(exists "$venv/pyvenv.cfg")"
    rm -rf "$appdir"
    mkdir -p "$appdir" && chown 12345 "$appdir"
    out=$(venv_run sunshine --version)
    has "foreign-owned cache dir: refused" "refusing" "$(err)"
    has "foreign-owned cache dir: throwaway venv used" "linecast $version" "$out"
    is "foreign-owned cache dir: left alone" no "$(exists "$venv")"
    rm -rf "$appdir"
    skip "read-only cache dir: root can write to any directory"
else
    skip "foreign-owned venv and cache dir: needs root to chown (runs in a container job)"
    rm -rf "$appdir"; mkdir "$appdir"; chmod 500 "$appdir"
    out=$(venv_run sunshine --version); rc=$?
    is "read-only cache dir: exits 0" 0 "$rc"
    has "read-only cache dir: refused" "refusing" "$(err)"
    has "read-only cache dir: throwaway venv used" "linecast $version" "$out"
    is "read-only cache dir: left alone" no "$(exists "$venv")"
    is "read-only cache dir: throwaway removed on exit" "" "$(ls -A "$work/tmp")"
    chmod 700 "$appdir"; rm -rf "$appdir"
fi

OVERRIDE=$work/override
out=$(venv_run sunshine --version)
OVERRIDE=
has "LINECAST_CACHE_DIR: prints the version" "linecast $version" "$out"
is "LINECAST_CACHE_DIR: venv lands at \$LINECAST_CACHE_DIR/venv" yes "$(runs "$work/override/venv")"
is "LINECAST_CACHE_DIR: XDG cache left alone" no "$(exists "$venv")"
is "LINECAST_CACHE_DIR: directory is private (0700)" "drwx------" "$(mode "$work/override")"

XDG=relative/path
out=$(venv_run sunshine --version)
XDG=$cache
has "relative XDG_CACHE_HOME: prints the version" "linecast $version" "$out"
is "relative XDG_CACHE_HOME: ignored, venv under HOME/.cache/linecast" yes "$(runs "$work/home/.cache/linecast/venv")"
is "relative XDG_CACHE_HOME: nothing made under the harness cwd" no "$(exists relative)"

rm -rf "$appdir"
NOPIP=1
out=$(venv_run sunshine --version); rc=$?
NOPIP=
is "venv without pip: exits 0" 0 "$rc"
has "venv without pip: prints the version" "linecast $version" "$out"
is "venv without pip: ensurepip supplied one" yes "$("$venv/bin/python" -m pip --version >/dev/null 2>&1 && echo yes || echo no)"

rm -rf "$appdir"
BREAK=1
out=$(venv_run sunshine --version); rc=$?
BREAK=
is "python3 -m venv failing exits 1" 1 "$rc"
has "python3 -m venv failing names python3-venv" "python3-venv" "$(err)"
is "python3 -m venv failing leaves no half-made venv" no "$(exists "$venv")"

if [ "$had_tmp_linecast" = yes ]; then
    skip "/tmp/linecast existed before this run"
else
    is "/tmp/linecast never created" no "$(exists /tmp/linecast)"
fi

echo "1..$n"
[ "$failed" -eq 0 ] || { echo "# $failed failed" >&2; exit 1; }
