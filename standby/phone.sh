#!/data/data/com.termux/files/usr/bin/bash
# ================================================================
#  نظام الجدول المدرسي (4.iajaward.org) من الهاتف (Termux) — احتياط عند انقطاع الكمبيوتر
#  يعمل بجانب الأنظمة الأخرى دون تعارض: المنفذ 8004، وقاعدة PostgreSQL خاصة به على المنفذ 5440،
#  ونفق مستقل «timetable-standby». المولّد التلقائي لا يعمل على الهاتف، وبقية النظام يعمل.
#
#   bash ~/timetable/standby/phone.sh setup        # مرة واحدة: المتطلبات + قاعدة البيانات
#   bash ~/timetable/standby/phone.sh configure    # مرة واحدة: الرموز (من إعدادات IAJ تلقائياً) + أزرار TT
#   bash ~/timetable/standby/phone.sh update-code  # آخر نسخة من GitHub (أو من Drive)
#   bash ~/timetable/standby/phone.sh takeover     # ★ الطوارئ: أحدث بيانات + تشغيل + تحويل 4.iajaward.org للهاتف
#   bash ~/timetable/standby/phone.sh stop         # إنهاء الطوارئ: إرجاع للكمبيوتر أو رفع بيانات الهاتف
#   bash ~/timetable/standby/phone.sh server       # إرجاع 4.iajaward.org للكمبيوتر فوراً (بدون نقل بيانات)
#   bash ~/timetable/standby/phone.sh status       # أين يعمل الآن
#   bash ~/timetable/standby/phone.sh backup       # رفع بيانات الهاتف إلى Drive
#   bash ~/timetable/standby/phone.sh try          # تجربة على الهاتف فقط: http://127.0.0.1:8004
#
#  القفل واللغة مشتركان مع أزرار IAJ (IAJ 0 / IAJ 9).
# ================================================================
set -e
SITE="$HOME/timetable"
LOCAL_BK="$HOME/timetable-backups"
REMOTE="gdrive:IAJ-backups"
[ -f "$HOME/.iaj_standby" ] && . "$HOME/.iaj_standby"
TT_REMOTE="${TT_REMOTE:-$REMOTE/timetable}"
[ -f "$HOME/.timetable_standby" ] && . "$HOME/.timetable_standby"
TOKEN_FILE="$HOME/.timetable_tunnel_token"
PGDATA_DIR="$HOME/timetable-pg"
PG_PORT=5440
APP_PORT=8004
export PYTHONUTF8=1
LANG_UI="${LANG_UI:-ar}"
export IAJ_LANG="$LANG_UI"
T() { if [ "$LANG_UI" = "en" ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
say() { printf '\n\033[1;36m» %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✖ %s\033[0m\n' "$*"; exit 1; }
guard() {
  if [ -f "$HOME/.iaj_lock" ] && [ -z "$IAJ_NOGUARD" ]; then
    die "$(T "🔒 الأزرار الحساسة مقفلة — اضغط «IAJ 0 - قفل أو فتح الأزرار» لفتحها" "🔒 Sensitive buttons are locked - press IAJ 0 to unlock")"
  fi
}
need_code() { [ -f "$SITE/serve.py" ] || die "$(T "الكود غير موجود — شغّل: bash phone.sh update-code" "Code not found - run: bash phone.sh update-code")"; }
# قاعدة PostgreSQL الخاصة بهذا النظام على الهاتف
pg_up() {
  [ -d "$PGDATA_DIR" ] || die "$(T "قاعدة البيانات غير مهيّأة — شغّل: bash phone.sh setup" "The database is not set up - run: bash phone.sh setup")"
  pg_ctl -D "$PGDATA_DIR" status >/dev/null 2>&1 && return 0
  rm -f "$PGDATA_DIR/postmaster.pid" 2>/dev/null || true   # بقايا إيقاف مفاجئ للهاتف
  pg_ctl -D "$PGDATA_DIR" -l "$HOME/timetable-pg.log" -o "-p $PG_PORT -c listen_addresses=127.0.0.1 -k ${TMPDIR:-$HOME}" -w start >/dev/null \
    || { tail -15 "$HOME/timetable-pg.log"; die "$(T "تعذّر تشغيل PostgreSQL على الهاتف" "Could not start PostgreSQL on the phone")"; }
}
pg_down() { pg_ctl -D "$PGDATA_DIR" -m fast stop >/dev/null 2>&1 || true; }
# إيقاف نفق هذا النظام فقط (لا يلمس أنفاق الأنظمة الأخرى)
kill_my_tunnel() {
  [ -s "$TOKEN_FILE" ] || return 0
  local key; key=$(head -c 40 "$TOKEN_FILE")
  for p in $(pgrep -x cloudflared 2>/dev/null); do
    tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -qF "$key" && kill "$p" 2>/dev/null || true
  done
}
neon_on() { grep -q '^NEON_BACKUP_URL=.' "$SITE/.env" 2>/dev/null; }
other_takeover() { pgrep -f "(iaj|rastkt|venues|attendance)/standby/phone.sh takeover" >/dev/null 2>&1; }
ask_mail() {   # البريد (Microsoft 365) — بدونه يعمل النظام لكن لا يُرسل بريداً
  echo "$(T "  إعدادات البريد من .env على الكمبيوتر (أو Render ← Environment):" "  Email settings from the PC's .env (or Render > Environment):")"
  read -r -p "  MS_TENANT_ID: " A; read -r -p "  MS_CLIENT_ID: " B
  read -r -s -p "  MS_CLIENT_SECRET: " C; echo; read -r -p "  MS_MAIL_SENDER: " D
  [ -n "$A" ] && [ -n "$B" ] && [ -n "$C" ] && [ -n "$D" ] || { echo "$(T "  تم التخطي" "  Skipped")"; return 0; }
  sed -i '/^MS_TENANT_ID=/d;/^MS_CLIENT_ID=/d;/^MS_CLIENT_SECRET=/d;/^MS_MAIL_SENDER=/d' "$SITE/.env"
  printf 'MS_TENANT_ID=%s\nMS_CLIENT_ID=%s\nMS_CLIENT_SECRET=%s\nMS_MAIL_SENDER=%s\n' "$A" "$B" "$C" "$D" >> "$SITE/.env"
  rm -f "$SITE/.mail_skip"
  echo "$(T "  ✓ حُفظت إعدادات البريد (تسري عند التشغيل التالي)" "  ✓ Email settings saved (used from the next start)")"
}

ensure_env() {
  if [ ! -f "$SITE/.env" ]; then
    KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
    printf 'SECRET_KEY=%s\nBASE_URL=https://4.iajaward.org\nPORT=%s\nTHREADS=4\nAPP_TIMEZONE=Asia/Amman\nSESSION_COOKIE_SECURE=1\nDATABASE_URL=postgresql+pg8000://postgres@127.0.0.1:%s/timetable\n' \
      "$KEY" "$APP_PORT" "$PG_PORT" > "$SITE/.env"
  fi
  # رمز Cloudflare: نفسه في موقع الجائزة أو الأنظمة الأخرى على هذا الهاتف
  if ! grep -q '^CF_API_TOKEN=.' "$SITE/.env"; then
    for f in "$HOME/iaj/.env" "$HOME/rastkt/.env" "$HOME/venues/.env" "$HOME/attendance/.env"; do
      if grep -q '^CF_API_TOKEN=.' "$f" 2>/dev/null; then grep '^CF_API_TOKEN=' "$f" | head -1 >> "$SITE/.env"; break; fi
    done
  fi
  chmod 600 "$SITE/.env" 2>/dev/null || true
}

case "$1" in
  setup)
    say "$(T "تثبيت المتطلبات (قد يستغرق دقائق)" "Installing requirements (may take minutes)")"
    pkg install -y python postgresql rclone cloudflared unzip python-cryptography python-pillow >/dev/null \
      || pkg install -y python postgresql rclone cloudflared unzip python-cryptography python-pillow
    need_code
    DISABLE_SQLALCHEMY_CEXT=1 pip install -r "$SITE/standby/requirements-phone.txt"
    if [ ! -d "$PGDATA_DIR" ]; then
      say "$(T "إنشاء قاعدة PostgreSQL خاصة بالنظام على الهاتف" "Creating the system's own PostgreSQL database on the phone")"
      initdb -D "$PGDATA_DIR" -U postgres --auth=trust -E UTF8 --locale=C >/dev/null
    fi
    pg_up
    ensure_env
    (cd "$SITE" && python -c "import sys;sys.path.insert(0,'ops');from common import load_env;load_env();import pgtools;pgtools.ensure_database(pgtools.db_url())")
    pg_down
    say "$(T "تم. الخطوة التالية: bash ~/timetable/standby/phone.sh configure" "Done. Next: bash ~/timetable/standby/phone.sh configure")"
    ;;

  update-code)
    if [ -s "$HOME/.iaj_github_token" ] && [ -f "$SITE/standby/gh_update.py" ]; then
      say "$(T "تنزيل الكود من GitHub" "Downloading code from GitHub")"
      if python "$SITE/standby/gh_update.py"; then
        say "$(T "تم تحديث الكود" "Code updated")"; exit 0
      fi
      say "$(T "تعذّر GitHub (تأكد أن رمز GitHub يشمل مستودع Timetable) — أحاول من Drive" "GitHub failed (make sure the GitHub token includes the Timetable repo) - trying Drive")"
    fi
    mkdir -p "$LOCAL_BK/code"
    rclone copy "$TT_REMOTE/code" "$LOCAL_BK/code" --progress
    [ -f "$LOCAL_BK/code/timetable-code.zip" ] || die "$(T "لم أجد timetable-code.zip في Drive — شغّل backup_now.bat على الكمبيوتر" "timetable-code.zip not in Drive - run backup_now.bat on the PC")"
    unzip -oq "$LOCAL_BK/code/timetable-code.zip" -d "$HOME"
    sed -i 's/\r$//' "$SITE"/standby/*.sh 2>/dev/null || true
    say "$(T "تم تحديث الكود من Drive" "Code updated from Drive")"
    ;;

  restore)
    need_code; ensure_env; pg_up
    say "$(T "تنزيل أحدث بيانات الجدول من Drive" "Downloading the latest timetable data from Drive")"
    mkdir -p "$LOCAL_BK/db"
    rclone copy "$TT_REMOTE/db" "$LOCAL_BK/db" --include "*.sql.gz" --max-age 30d --progress
    if neon_on; then
      say "$(T "جلب أحدث نسخة من Neon أيضاً (تُستخدم الأحدث بين Drive وNeon)" "Also fetching the latest copy from Neon (the newer of Drive/Neon is used)")"
      (cd "$SITE" && python ops/neon_store.py pull "$LOCAL_BK/db") || say "$(T "تعذّر Neon — أكمل بنسخة Drive" "Neon failed - continuing with the Drive copy")"
    fi
    cd "$SITE" && python ops/restore.py --latest "$LOCAL_BK" --yes
    ;;

  mail)
    need_code; ensure_env; ask_mail
    ;;

  neon)
    guard; need_code; ensure_env
    neon_on || die "$(T "لا يوجد رابط Neon — شغّل configure وألصقه عند الطلب" "No Neon link - run configure and paste it when asked")"
    pg_up
    say "$(T "تنزيل أحدث نسخة من Neon وتثبيتها على الهاتف" "Downloading the latest copy from Neon onto the phone")"
    mkdir -p "$LOCAL_BK/neon"
    (cd "$SITE" && python ops/neon_store.py pull "$LOCAL_BK/neon" | tail -1)
    N=$(ls -t "$LOCAL_BK/neon"/*.sql.gz 2>/dev/null | head -1)
    [ -n "$N" ] || die "$(T "لم يُنزَّل شيء" "Nothing was downloaded")"
    pkill -f "$SITE/serve.py" 2>/dev/null || true
    cd "$SITE" && python ops/restore.py --file "$N" --yes
    say "$(T "تم. بيانات Neon على الهاتف الآن — للتشغيل للعامة: زر TT 1" "Done. Neon data is on the phone - to serve it publicly: TT 1")"
    ;;

  try)
    need_code; ensure_env; pg_up
    say "$(T "النظام يعمل على الهاتف فقط: http://127.0.0.1:8004 — للإيقاف Ctrl+C" "Running on the phone only: http://127.0.0.1:8004 - Ctrl+C to stop")"
    cd "$SITE" && python "$SITE/serve.py"
    ;;

  configure)
    need_code; ensure_env
    grep -q '^CF_API_TOKEN=.' "$SITE/.env" || {
      read -r -s -p "$(T "  الصق رمز Cloudflare API ثم Enter: " "  Paste the Cloudflare API token, then Enter: ")" TK; echo
      [ -n "$TK" ] && echo "CF_API_TOKEN=$TK" >> "$SITE/.env"; }
    say "$(T "جلب رمز نفق الهاتف timetable-standby من Cloudflare (يُحفظ ولا يظهر)" "Fetching the phone tunnel token from Cloudflare (saved, not shown)")"
    (cd "$SITE" && python ops/cf.py token > "$TOKEN_FILE.tmp") && [ -s "$TOKEN_FILE.tmp" ] && mv "$TOKEN_FILE.tmp" "$TOKEN_FILE" && chmod 600 "$TOKEN_FILE" \
      || { rm -f "$TOKEN_FILE.tmp"; die "$(T "تعذّر — شغّل أولاً على الكمبيوتر 1_setup.bat (ينشئ النفق)" "Failed - run 1_setup.bat on the PC first (it creates the tunnel)")"; }
    if ! grep -q '^MS_CLIENT_SECRET=.' "$SITE/.env" && [ ! -f "$SITE/.mail_skip" ]; then
      ask_mail; grep -q '^MS_CLIENT_SECRET=.' "$SITE/.env" || touch "$SITE/.mail_skip"
    fi
    if ! neon_on && [ ! -f "$SITE/.neon_skip" ]; then
      read -r -s -p "$(T "  (اختياري) الصق رابط Neon لهذا النظام — أو Enter للتخطي: " "  (optional) Paste this system's Neon link - or Enter to skip: ")" NU; echo
      if [ -n "$NU" ]; then echo "NEON_BACKUP_URL=$NU" >> "$SITE/.env"; (cd "$SITE" && python ops/neon_store.py info) || true
      else touch "$SITE/.neon_skip"; fi
    fi
    mkdir -p "$HOME/.shortcuts"
    mk() { printf '#!/data/data/com.termux/files/usr/bin/bash\n%s\necho; read -r -p "Enter ↵" _\n' "$2" > "$HOME/.shortcuts/$1"; chmod +x "$HOME/.shortcuts/$1"; }
    mk "TT 1 - تشغيل طوارئ الجدول"  "bash ~/timetable/standby/phone.sh takeover"
    mk "TT 1 - إنهاء طوارئ الجدول"  "bash ~/timetable/standby/phone.sh stop"
    mk "TT 2 - إرجاع الجدول للكمبيوتر" "bash ~/timetable/standby/phone.sh server"
    mk "TT 3 - أين يعمل نظام الجدول" "bash ~/timetable/standby/phone.sh status"
    mk "TT 4 - تحديث كود الجدول" "bash ~/timetable/standby/phone.sh update-code && bash ~/timetable/standby/phone.sh configure"
    mk "TT 5 - نسخ بيانات الجدول إلى Drive" "bash ~/timetable/standby/phone.sh backup"
    mk "TT 6 - استرجاع من Neon إلى الهاتف" "bash ~/timetable/standby/phone.sh neon"
    say "$(T "تم. حدّث أداة Termux:Widget لتظهر أزرار TT" "Done. Refresh the Termux:Widget to see the TT buttons")"
    cd "$SITE" && python ops/cf.py status || true
    ;;

  backup)
    guard; need_code; pg_up
    cd "$SITE"
    say "$(T "رفع بيانات الهاتف إلى Drive" "Uploading the phone data to Drive")"
    python ops/backup.py --dir "$LOCAL_BK" --tag phone --no-code
    rclone copy "$LOCAL_BK/db" "$TT_REMOTE/db" --include "*-phone.sql.gz" --max-age 1d --progress
    say "$(T "تم. على الكمبيوتر: back_to_server.bat" "Done. On the PC: back_to_server.bat")"
    ;;

  takeover)
    guard; need_code; ensure_env
    grep -q '^CF_API_TOKEN=.' "$SITE/.env" || die "$(T "شغّل configure أولاً" "Run configure first")"
    [ -s "$TOKEN_FILE" ] || die "$(T "شغّل configure أولاً (رمز النفق)" "Run configure first (tunnel token)")"
    if (cd "$SITE" && python ops/cf.py server-up 2>/dev/null); then
      echo
      echo "$(T "  ✋ الكمبيوتر يعمل ونظام الجدول سليم — لا حاجة للطوارئ." "  ✋ The PC is up and the timetable system is fine - no need for emergency mode.")"
      read -r -p "$(T "  للتشغيل رغم ذلك اكتب FORCE، أو Enter للإلغاء: " "  To run anyway type FORCE, or Enter to cancel: ")" ANS
      [ "$ANS" = "FORCE" ] || die "$(T "تم الإلغاء" "Cancelled")"
    fi
    grep -q '^MS_CLIENT_SECRET=.' "$SITE/.env" || say "$(T "⚠ لا توجد إعدادات بريد على الهاتف — لن يُرسل النظام رسائل. لإضافتها: bash $0 mail" "⚠ No email settings on the phone - no emails will be sent. To add them: bash $0 mail")"
    pkill -f "$SITE/serve.py" 2>/dev/null || true
    kill_my_tunnel; sleep 1
    bash "$0" restore
    cd "$SITE"
    termux-wake-lock 2>/dev/null || true
    say "$(T "تشغيل نظام الجدول (المولّد التلقائي لا يعمل على الهاتف)" "Starting the timetable system (the automatic generator does not run on the phone)")"
    python "$SITE/serve.py" > "$HOME/timetable-serve.log" 2>&1 &
    WEB=$!
    OK=0
    for i in $(seq 1 60); do
      kill -0 $WEB 2>/dev/null || break
      python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$APP_PORT/healthz',timeout=2)" 2>/dev/null && { OK=1; break; }
      sleep 2
    done
    if [ $OK != 1 ]; then
      kill $WEB 2>/dev/null; tail -20 "$HOME/timetable-serve.log"
      die "$(T "لم يعمل على الهاتف — لم يُحوَّل شيء" "Did not start on the phone - nothing was switched")"
    fi
    say "$(T "تشغيل نفق الهاتف" "Starting the phone tunnel")"
    cloudflared tunnel --no-autoupdate run --token "$(cat "$TOKEN_FILE")" > "$HOME/timetable-cloudflared.log" 2>&1 &
    CF=$!
    FP0=$(python ops/fingerprint.py 2>/dev/null | tail -1)
    DONE=0
    finish() {
      [ $DONE = 1 ] && return; DONE=1
      kill $WEB $CF 2>/dev/null
      say "$(T "إيقاف نظام الجدول على الهاتف" "Stopping the timetable system on the phone")"
      FP1=$(python ops/fingerprint.py 2>/dev/null | tail -1)
      if [ "$FP0" = "$FP1" ]; then
        if python ops/cf.py server; then
          python -c "import sys;sys.path.insert(0,'ops');from common import stamp;print('server',stamp())" > "$LOCAL_BK/db/ACTIVE_SITE.txt"
          rclone copyto "$LOCAL_BK/db/ACTIVE_SITE.txt" "$TT_REMOTE/db/ACTIVE_SITE.txt" 2>/dev/null || true
        else
          say "$(T "الكمبيوتر غير متصل — 4.iajaward.org سيبقى متوقفاً حتى يعود" "The PC is offline - 4.iajaward.org stays down until it is back")"
        fi
      else
        IAJ_NOGUARD=1 bash "$0" backup || true
        echo
        echo "$(T "  ⚠ عُدّلت بيانات على الهاتف — على الكمبيوتر شغّل: back_to_server.bat" "  ⚠ Data was changed on the phone - on the PC run: back_to_server.bat")"
      fi
      pg_down
      other_takeover || termux-wake-unlock 2>/dev/null || true
    }
    trap finish EXIT INT TERM
    say "$(T "تحويل 4.iajaward.org إلى الهاتف" "Switching 4.iajaward.org to the phone")"
    if python ops/cf.py phone; then
      python -c "import sys;sys.path.insert(0,'ops');from common import stamp;print('phone',stamp())" > "$LOCAL_BK/db/ACTIVE_SITE.txt"
      rclone copyto "$LOCAL_BK/db/ACTIVE_SITE.txt" "$TT_REMOTE/db/ACTIVE_SITE.txt" 2>/dev/null || true
    else
      die "$(T "لم يتم التحويل" "Switch failed")"
    fi
    say "$(T "✅ الهاتف يشغّل 4.iajaward.org — لا تغلق النافذة. للإنهاء: زر «TT 1 - إنهاء» أو Ctrl+C" "✅ The phone serves 4.iajaward.org - keep this window. To finish: TT 1 - Stop, or Ctrl+C")"
    while kill -0 $WEB 2>/dev/null && kill -0 $CF 2>/dev/null; do sleep 5; done
    say "$(T "توقف النظام أو النفق على الهاتف" "The system or tunnel stopped on the phone")"
    exit 0
    ;;

  stop)
    PID=$(pgrep -f "timetable/standby/phone.sh takeover" | grep -v "^$$\$" | head -1)
    if [ -z "$PID" ]; then
      say "$(T "طوارئ الجدول ليست قيد التشغيل" "Timetable emergency mode is not running")"
    else
      say "$(T "إنهاء الطوارئ… (قد يستغرق دقيقة)" "Stopping emergency mode... (may take a minute)")"
      kill -INT "$PID" 2>/dev/null || true
      for i in $(seq 1 45); do kill -0 "$PID" 2>/dev/null || break; sleep 2; done
    fi
    need_code; cd "$SITE" && python ops/cf.py status 2>/dev/null || true
    ;;

  server)
    guard; need_code
    read -r -p "$(T "  إرجاع 4.iajaward.org للكمبيوتر بدون نقل بيانات — اكتب YES: " "  Move 4.iajaward.org back to the PC without moving data - type YES: ")" OK
    [ "$OK" = "YES" ] || die "$(T "تم الإلغاء" "Cancelled")"
    cd "$SITE" && python ops/cf.py server
    ;;

  status)
    need_code; cd "$SITE" && python ops/cf.py status
    ;;

  *)
    sed -n '2,19p' "$0"
    ;;
esac
