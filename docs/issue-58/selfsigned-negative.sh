#!/bin/bash
# Issue #58 r2 (Knox P2) negative control on macOS: a copy of the official buzz CLI re-signed
# with a SELF-SIGNED code-signing certificate whose subject OU is EYF346PHUG (so `codesign -dv`
# may self-assert TeamIdentifier=EYF346PHUG) must be refused by bin/buzz (exit 3, no exec) and
# must fail bin/buzz-health (exit 2) and official_signature_ok (apply precheck).
#
# Everything lives in <workdir> (under $HOME, must not exist): a temporary keychain FILE with a
# random password, the throwaway key/cert, and the re-signed copy. The keychain is never added
# to the search list by this script (no `security list-keychains -s`), no trust settings are
# changed (no add-trusted-cert), the live instance and the official binary are only read.
# The keychain is deleted and <workdir> removed at the end. Evidence (no secrets) -> stdout.
#
# If codesign on this Mac cannot use the temp-keychain identity (observed on macOS 26.6.2:
# "no identity found" by name and by SHA-1 while the keychain is outside the search list),
# SELFSIGNED_PRESIGNED=<file> may name a copy of the same official binary that was re-signed
# elsewhere with an equivalent throwaway self-signed OU=EYF346PHUG certificate (e.g. rcodesign
# on Linux, see evidence/18); the gates then run on that copy. Without a re-signed copy the
# gate section is skipped (never run against an unmodified copy).
#
# Usage: selfsigned-negative.sh <workdir under $HOME> [pre-r2 bin/buzz to show the old gate]
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
W="${1:?workdir}"; OLD_BUZZ="${2:-}"
case "$W" in "$HOME"/*) ;; *) die "workdir must be under \$HOME" ;; esac
[ ! -e "$W" ] || die "$W exists"
case "$W" in "$LIVE_INSTANCE"*) die "workdir inside live instance" ;; esac
unset ISSUE58_I_UNDERSTAND_LIVE ISSUE58_TEST_SKIP_SIGNATURE BUZZ58_TEST_OFFICIAL_BUZZ BUZZ58_TEST_PS_FIXTURE BUZZ58_TEST_DOCTOR_FIXTURE
OPENSSL=/usr/bin/openssl; SEC=/usr/bin/security; CS=/usr/bin/codesign; PY3=/usr/bin/python3
HEALTH="$ISSUE58_DIR/bin/buzz-health"
mkdir -p "$W/copy"; W="$(cd "$W" && pwd -P)"
KC="$W/buzz58-r2-selfsigned.keychain-db"
CN="buzz58 r2 self-signed test (not Apple)"
COPY="$W/copy/buzz"
cleanup() { [ -e "$KC" ] && "$SEC" delete-keychain "$KC" 2>/dev/null; rm -rf "$W"; }
trap cleanup EXIT
# run with a timeout so a keychain UI prompt can never hang the script
run_to() { local t="$1"; shift; "$@" & local p=$!; ( sleep "$t"; kill -9 "$p" 2>/dev/null ) & local k=$!
  wait "$p"; local rc=$?; kill "$k" 2>/dev/null; wait "$k" 2>/dev/null; return "$rc"; }
kc_state() { echo "list-keychains:"; "$SEC" list-keychains | sed 's/^/  /'; echo "default-keychain: $("$SEC" default-keychain | tr -d ' ')"
  echo "user trust settings sha256: $("$SEC" dump-trust-settings 2>&1 | shasum -a 256 | awk '{print $1}')"; }

echo "# $(date '+%Y-%m-%d %H:%M:%S %Z')  workdir=$W"
echo "requirement: $ISSUE58_REQUIREMENT"
echo "openssl: $("$OPENSSL" version)"
echo "## keychain state BEFORE"; kc_state | tee "$W/kc-before.txt"

echo "## 1. throwaway self-signed code-signing cert (subject OU=EYF346PHUG)"
cat > "$W/cert.cnf" <<CNF
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3
[dn]
CN = $CN
OU = EYF346PHUG
O = buzz58-r2-test
[v3]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF
"$OPENSSL" req -x509 -newkey rsa:2048 -nodes -sha256 -days 1 -config "$W/cert.cnf" \
  -keyout "$W/key.pem" -out "$W/cert.pem" >/dev/null 2>&1; echo "openssl req rc=$?"
"$OPENSSL" x509 -in "$W/cert.pem" -noout -subject -issuer 2>&1 | sed 's/^/  /'
"$OPENSSL" x509 -in "$W/cert.pem" -noout -text 2>/dev/null | grep -A1 'Extended Key Usage' | sed 's/^/  /'
SHA1=$("$OPENSSL" x509 -in "$W/cert.pem" -noout -fingerprint -sha1 | sed 's/.*=//; s/://g')
echo "  cert sha1=$SHA1"
KCPW=$("$OPENSSL" rand -hex 24); P12PW=$("$OPENSSL" rand -hex 24)
P12PW="$P12PW" "$OPENSSL" pkcs12 -export -inkey "$W/key.pem" -in "$W/cert.pem" -name "$CN" \
  -out "$W/id.p12" -passout env:P12PW >/dev/null 2>&1; echo "openssl pkcs12 rc=$?"

echo "## 2. temporary keychain file (random password; not added to the search list by this script)"
"$SEC" create-keychain -p "$KCPW" "$KC"; echo "security create-keychain <tmp> rc=$?"
echo "list-keychains right after create-keychain:"; "$SEC" list-keychains | sed 's/^/  /'
"$SEC" unlock-keychain -p "$KCPW" "$KC"; echo "security unlock-keychain rc=$?"
"$SEC" import "$W/id.p12" -k "$KC" -f pkcs12 -P "$P12PW" -T "$CS" >/dev/null 2>&1; echo "security import p12 -> tmp keychain only rc=$?"
"$SEC" set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KCPW" "$KC" >/dev/null 2>&1; echo "security set-key-partition-list (tmp keychain) rc=$?"
echo "find-identity -p codesigning <tmp keychain> (all, incl. untrusted):"; "$SEC" find-identity -p codesigning "$KC" 2>&1 | sed 's/^/  /'
unset KCPW P12PW
rm -f "$W/key.pem" "$W/id.p12"

echo "## 3. sign a COPY of the official binary"
cp "$OFFICIAL_BUZZ" "$COPY"
SIGNED_BY=none
run_to 60 "$CS" -f -s "$CN" -i buzz --keychain "$KC" "$COPY" > "$W/sign-name.log" 2>&1; rc=$?
echo "codesign -f -s '<CN>' -i buzz --keychain <tmp> <copy>: rc=$rc"; sed 's/^/  /' "$W/sign-name.log"
if [ "$rc" = 0 ]; then SIGNED_BY=name; else
  run_to 60 "$CS" -f -s "$SHA1" -i buzz --keychain "$KC" "$COPY" > "$W/sign-sha1.log" 2>&1; rc=$?
  echo "codesign -f -s <cert sha1> -i buzz --keychain <tmp> <copy>: rc=$rc"; sed 's/^/  /' "$W/sign-sha1.log"
  [ "$rc" = 0 ] && SIGNED_BY=sha1
fi
if [ "$SIGNED_BY" = none ] && [ -n "${SELFSIGNED_PRESIGNED:-}" ]; then
  cp "$SELFSIGNED_PRESIGNED" "$COPY" && chmod 755 "$COPY" && SIGNED_BY=presigned
  echo "codesign could not sign here; using SELFSIGNED_PRESIGNED (re-signed elsewhere with a throwaway self-signed OU=EYF346PHUG cert)"
fi
echo "signed_by=$SIGNED_BY"
echo "copy sha256=$(sha256_of "$COPY") official sha256=$(sha256_of "$OFFICIAL_BUZZ")"
if cmp -s "$COPY" "$OFFICIAL_BUZZ"; then
  echo "copy is byte-identical to the official binary (not re-signed): SKIPPING sections 4-5"
  SIGNED_BY=none
fi

if [ "$SIGNED_BY" != none ]; then
echo "## 4. what the copy asserts (codesign -dv / -d -r-; self-asserted, record only)"
"$CS" -dvv "$COPY" 2>&1 | grep -E '^(Identifier|TeamIdentifier|Signature|Authority|Format)=' | sed 's/^/  /'
"$CS" -d -r- "$COPY" 2>&1 | grep -E 'designated' | sed 's/^/  /'
"$CS" --verify --strict "$COPY" >/dev/null 2>&1; echo "codesign --verify --strict (no -R, pre-r2 first step): rc=$?"
"$CS" --verify --strict -R "$ISSUE58_REQUIREMENT" "$COPY" > "$W/req.log" 2>&1; echo "codesign --verify --strict -R <requirement> (r2 decision): rc=$?"; sed 's/^/  /' "$W/req.log"

echo "## 5. gates"
if [ -n "$OLD_BUZZ" ]; then
  BUZZ58_TEST_OFFICIAL_BUZZ="$COPY" bash "$OLD_BUZZ" --help > "$W/old.out" 2> "$W/old.err"; rc=$?
  echo "pre-r2 bin/buzz (9802f52) --help: rc=$rc stdout_bytes=$(wc -c < "$W/old.out" | tr -d ' ') stderr=$(head -c 300 "$W/old.err" | tr '\n' ' ')"
fi
BUZZ58_TEST_OFFICIAL_BUZZ="$COPY" "$ISSUE58_DIR/bin/buzz" --help > "$W/new.out" 2> "$W/new.err"; rc=$?
echo "r2 bin/buzz --help: rc=$rc stdout_bytes=$(wc -c < "$W/new.out" | tr -d ' ') stderr=$(tr '\n' ' ' < "$W/new.err")"
( BUZZ58_TEST_OFFICIAL_BUZZ="$COPY"; official_signature_ok ); echo "r2 common.sh official_signature_ok (apply precheck): rc=$?"
BUZZ58_TEST_OFFICIAL_BUZZ="$COPY" "$PY3" "$HEALTH" > "$W/health.json"; hrc=$?
"$PY3" - "$W/health.json" "$hrc" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); s = r["official_buzz"]
print(f"r2 buzz-health: exit={sys.argv[2]} ok={r['ok']} failures={r['failures']} test_hooks={r['test_hooks']}")
print(f"  official_buzz: verify={s['codesign_verify']} recorded team={s['team_identifier']} id={s['identifier']} problems={s['problems']}")
PY
fi

echo "## 6. cleanup"
"$SEC" delete-keychain "$KC"; echo "security delete-keychain <tmp> rc=$?"
[ ! -e "$KC" ] && echo "tmp keychain file gone: yes" || echo "tmp keychain file gone: NO"
echo "## keychain state AFTER"; kc_state > "$W/kc-after.txt"; cat "$W/kc-after.txt"
cmp -s "$W/kc-before.txt" "$W/kc-after.txt" && echo "keychain state before == after: IDENTICAL" || { echo "keychain state before vs after: DIFFERS"; diff "$W/kc-before.txt" "$W/kc-after.txt"; }
rm -rf "$W"; [ ! -e "$W" ] && echo "workdir removed: yes"
