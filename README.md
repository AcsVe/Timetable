# نظام جدولة الحصص وتوزيع المعلمين — Timetable

Flask + SQLAlchemy + Postgres (Neon) · واجهة عربية RTL مع الإنجليزية · مستقل عن مشروع عربة الحواسيب.

مخطط قاعدة البيانات المعتمد: [`docs/ERD.md`](docs/ERD.md).

## الحالة: المرحلة 1 — الخادم والكيانات الأساسية ✅

| الجزء | ما تم |
|---|---|
| البنية | UUIDv7 لكل سجل، `version` (قفل تفاؤلي ← 409)، `change_seq` عام للمزامنة، حذف ناعم، سجل تدقيق لكل تعديل |
| الاتصال | كل عملية تعديل تتطلب `Idempotency-Key`؛ إعادة نفس الطلب تُرجع النتيجة المخزّنة ولا تُنفَّذ مرتين |
| الحسابات | `admin` / `stage_editor` (مراحل محددة) / `viewer`، حسابات بديلة بتاريخ انتهاء `valid_until` |
| البيانات | المدرسة، السنوات، الفصول، الأيام، المراحل، الصفوف، الشعب، التقسيمات والمجموعات، المباحث، المعلمون، المباني، القاعات، قوالب التوقيت وربطها بالأيام/الصفوف دفعة واحدة |
| الجدولة | الدروس ← البطاقات تلقائياً (5 حصص مزدوجة = 2+2+1)، وضع/نقل/قفل البطاقات، دروس مشتركة، مجموعات بنفس الحصة (رياضة أولاد/بنات، موسيقى/دراما) |
| منع التعارض | محرّك قواعد واحد (معلم، قاعة، شعبة/مجموعة، توقيت، فسحة داخل الحصة المزدوجة، أوقات عدم التوفر، نوع القاعة) + قيد `EXCLUDE` في قاعدة البيانات يمنع حجز المعلم/القاعة مرتين حتى عند الحفظ المتزامن |
| السحب والإفلات (الخادم) | `POST /api/cards/<id>/check` فحص قبل الإفلات، و`GET /api/cards/<id>/allowed-slots` شبكة الخانات المسموحة مع السبب |
| التحقق | تقرير أخطاء/تحذيرات + فحص جدوى حسابي (نصاب المعلم مقابل خاناته، حصص الشعبة مقابل أسبوعها) |
| دورة الجدول | نسخ جدول كمسودة، نشر (يؤرشف المنشور السابق، ويرفض النشر مع وجود أخطاء إلا بـ `force`)، الجداول المؤرشفة للقراءة فقط |
| المزامنة | `GET /api/sync?since=N` يعيد كل التغييرات (مع المحذوفات) بالترتيب — أساس العرض دون اتصال |

**التالي:** الواجهة الإدارية (RTL، AR/EN، السحب والإفلات، PWA + عرض دون اتصال)، ثم التقارير والتصدير (Excel/PDF بالشعار)، ثم الإشعارات، ثم البدلاء، ثم المولّد التلقائي.

## التشغيل محلياً

```bash
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://USER:PASS@HOST/DB      # Postgres 15+ (NULLS NOT DISTINCT)
flask --app wsgi.py db upgrade
flask --app wsgi.py seed-base                          # الأيام (الأحد–الخميس دوام) والإعدادات
flask --app wsgi.py create-admin --email you@school --password '...'
flask --app wsgi.py run
```

## الاختبارات

```bash
export TEST_DATABASE_URL=postgresql://postgres@localhost/timetable_test
pytest -q
```
تُبنى قاعدة الاختبار من ملفات الـ migrations نفسها، فالاختبارات تثبت صحة الـ migrations أيضاً.

## النشر على Render + Neon

`render.yaml` جاهز: اضبط `DATABASE_URL` (رابط Neon) فقط؛ `SECRET_KEY` يُولَّد تلقائياً. الـ migrations تعمل تلقائياً عند كل تشغيل.
أنشئ أول حساب مدير من Render Shell: `flask --app wsgi.py create-admin --email ... --password ...`

## ملخص الـ API

كل الكتابات: ترويسة `Idempotency-Key: <uuid>`، والتعديل/الحذف يحتاج `version` الحالي.
الأخطاء بصيغة موحّدة: `{"error", "message" (عربي), "message_en", "details"}`.

| | |
|---|---|
| `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` | الدخول |
| `GET/POST /api/<res>` · `GET/PATCH/DELETE /api/<res>/<id>` | `school, academic-years, terms, weekdays, stages, grades, sections, divisions, groups, bell-schedules, bell-assignments, subjects, teachers, buildings, rooms, timetables, availability, constraint-rules, users` |
| `POST /api/bell-assignments/bulk` | تطبيق قالب توقيت على عدة أيام وصفوف دفعة واحدة |
| `GET /api/timetables/<id>/lessons` · `POST /api/lessons` · `PATCH/DELETE /api/lessons/<id>` | الدروس |
| `GET /api/timetables/<id>/cards` · `PATCH /api/cards/<id>` | وضع/نقل/قفل البطاقات |
| `POST /api/cards/<id>/check` · `GET /api/cards/<id>/allowed-slots` | فحص قبل الإفلات |
| `GET /api/timetables/<id>/validate` | تقرير التحقق |
| `POST /api/timetables/<id>/copy` · `POST /api/timetables/<id>/publish` | دورة الجدول |
| `GET /api/sync?since=N` · `GET /api/settings` · `PUT /api/settings/<key>` | المزامنة والإعدادات |
