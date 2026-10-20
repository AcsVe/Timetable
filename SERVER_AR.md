# تشغيل نظام الجدول على الكمبيوتر (4.iajaward.org) + الهاتف احتياطاً

نفس طريقة الأنظمة الأخرى: الكمبيوتر يشغّل النظام، Cloudflare ينشره على `https://4.iajaward.org`،
نسخة احتياطية كل ساعة إلى Google Drive، والهاتف يتولّى عند انقطاع الكمبيوتر.

| | |
|---|---|
| المنفذ المحلي | `8004` (الجائزة 8000، التذاكر 8001، القاعات 8002، الحضور 8003) |
| القاعدة | PostgreSQL على الكمبيوتر — القاعدة `timetable` (رابطها `DATABASE_URL` في `.env`) |
| النسخ | `BACKUP_DIR\db` (داخل مجلد Drive: `IAJ-backups\timetable`) |
| نفق الكمبيوتر | نفس نفق الجائزة `iajaward` |
| نفق الهاتف | `timetable-standby` (يُنشأ تلقائياً) |

## الكمبيوتر (مرة واحدة)

المتطلبات: Python 3.12 (64-bit) مع «Add to PATH»، وPostgreSQL (مثبّت مسبقاً على الكمبيوتر)، وGit.

```bat
git clone https://github.com/AcsVe/Timetable.git C:\TT\Timetable
cd C:\TT\Timetable
1_setup.bat            :: الإعدادات + القاعدة + نقل البيانات من Neon (اختياري) + ربط 4.iajaward.org
3_autostart.bat        :: كمسؤول: تشغيل مع Windows + نسخ كل ساعة + الحارس
```

يسأل `1_setup.bat` عن كلمة مرور PostgreSQL، ويأخذ مجلد Drive ورمز Cloudflare من موقع الجائزة أو من
الأنظمة الأخرى على الجهاز نفسه. وإن لم يوجد مدير نظام في القاعدة يطلب بريده وكلمة مروره.

| الملف | العمل |
|---|---|
| `update.bat` | تحديث الكود من GitHub وإعادة التشغيل (ترحيلات القاعدة تُطبَّق تلقائياً) |
| `site_where.bat` | أين يعمل 4.iajaward.org + تشخيص + حالة الحارس |
| `switch_to_server.bat` | إرجاع 4.iajaward.org للكمبيوتر فوراً |
| `back_to_server.bat` | بعد الطوارئ: أخذ بيانات الهاتف + إرجاع الموقع |
| `backup_now.bat` / `restore_backup.bat` | نسخ / استرجاع يدوي |
| `tt_on.bat` / `tt_off.bat` | تشغيل / إيقاف النظام (كمسؤول) |

## الهاتف (Termux — بجانب الأنظمة الأخرى)

```bash
cd ~ && curl -sL -H "Authorization: Bearer $(cat ~/.iaj_github_token)" \
  https://api.github.com/repos/AcsVe/Timetable/zipball/main -o tt.zip && \
  unzip -q tt.zip -d tttmp && mv tttmp/* timetable && rm -rf tttmp tt.zip && \
  bash ~/timetable/standby/phone.sh setup && bash ~/timetable/standby/phone.sh configure
```

رمز GitHub يجب أن يشمل مستودع Timetable. الأزرار: `TT 1` تشغيل/إنهاء الطوارئ، `TT 2` إرجاع للكمبيوتر،
`TT 3` الحالة، `TT 4` تحديث الكود، `TT 5` رفع بيانات الهاتف، `TT 6` استرجاع من Neon. القفل واللغة من أزرار `IAJ 0` و`IAJ 9`.

على الهاتف قاعدة PostgreSQL خاصة بالنظام (المنفذ 5440، المجلد `~/timetable-pg`) تُعبّأ من أحدث نسخة عند كل
تشغيل طوارئ. **المولّد التلقائي لا يعمل على الهاتف** (مكتبة OR-Tools لا تتوفر لأندرويد)؛ بقية النظام يعمل:
الجداول والشبكة والتقارير والغياب والإشغال والامتحانات والمناوبة.
