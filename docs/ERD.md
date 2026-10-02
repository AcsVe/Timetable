# مخطط قاعدة البيانات — نظام جدولة الحصص وتوزيع المعلمين
**الإصدار 0.3 — كما بُني في المرحلة 1 (انظر سجل القرارات في القسم 11)**
Postgres (Neon) + SQLAlchemy — الأسماء التقنية بالإنجليزية، الشرح بالعربية.

---

## 0. قائمة مرجعية: ميزات ASC Timetables ← مكانها في هذا المخطط

| ميزة في ASC | في هذا المخطط | المرحلة |
|---|---|---|
| الصفوف، المعلمون، المباحث، القاعات، المباني | `grade/section`, `teacher`, `subject`, `room`, `building` | 1 |
| "الدروس" (Lessons): مبحث + صف/شعب + معلم + عدد حصص أسبوعياً + مدة (مفردة/مزدوجة) | `lesson`, `lesson_teacher`, `lesson_target` | 1 |
| "البطاقات" (Cards): وضع الدرس في يوم/حصة، مع القفل (lock) | `card` (`is_locked`) | 1 |
| التقسيمات والمجموعات (Divisions/Groups) — رياضة (معلم للأولاد + معلمة للبنات)، دراما، موسيقى: الطلبة مجموعتان بنفس الحصة | `division`, `student_group` | 1 |
| الدروس المشتركة بين شعب/صفوف (Joint lessons) | عدة صفوف في `lesson_target` لنفس الدرس | 1 |
| أكثر من معلم في نفس البطاقة (تدريس مشترك حقيقي) | `lesson_teacher` + `subject.max_teachers_per_block` | 1 |
| كشف التعارضات (على رقم الحصة) | قيد `EXCLUDE` على `occupancy` + تقرير تحقق | 1 |
| أوقات حصص وفسح لكل يوم، ونسخ توقيت يوم لأيام أخرى | `bell_schedule` (قوالب توقيت) + `bell_assignment` | 1 |
| أوقات عدم التوفر (Time-off) للمعلم/الصف/المبحث/القاعة | `availability` | 1 |
| قيود المعلم: أقصى حصص يومياً، أقصى فراغات، أقصى تتالٍ | أعمدة في `teacher` | 1 (تخزين) |
| قيود متقدمة (Card relationships): نفس اليوم، قبل حصة معينة، بدء المجموعات معاً… | `constraint_rule` (نوع + `params jsonb`) | 1 (تخزين) / 3 (تطبيق) |
| جداول أسبوع أ/ب (دورات متعددة الأسابيع) | `timetable.cycle_weeks`, `card.week_no` | 1 |
| أرشفة ونسخ الجداول، مسودة/منشور | `timetable` (`status`, `based_on_id`) | 1 |
| تعدد المستخدمين والصلاحيات | `app_user`, `user_stage` (أدق من ASC: حسب المرحلة) | 1 |
| الطباعة (جدول صف/معلم/قاعة/ملخص الكل) + تصدير | تقارير فوق الجداول (لا جداول إضافية) | 1 |
| تقرير التحقق / Advisor (حصص ناقصة، نصاب غير مكتمل…) | استعلامات تحقق + `GET /api/validate` | 1 |
| **التوليد التلقائي (Generator)** | محرّك CP-SAT — القسم 12، **ضمن النطاق** | 3 |
| تخفيف القيود عند التوليد (Constraint relaxation) | أفضل منه: تفسير سبب الاستحالة بدقة — القسم 12 | 3 |
| البدلاء (Substitutions) واقتراح أنسب بديل | `teacher_absence`, `substitution` | 2 |
| التقويم المدرسي والأحداث | `calendar_event` | 2 |
| حجز القاعات لحدث | `occupancy` نفسها تمنع التعارض | لاحقاً |
| دفتر الصف / الحضور | خارج النطاق (موجود لديكم في أنظمة أخرى) | — |
| مساعد ذكاء اصطناعي داخل البرنامج | خارج النطاق حالياً | — |
| **تفوّق على ASC** | ويب/PWA، أدوار حسب المرحلة، إشعارات بريد/Push، تصدير Excel/PDF مباشر بشعار المدرسة، عرض دون اتصال | 1 |

> المولّد التلقائي ضمن النطاق، والهدف أن يتفوّق على ASC منطقياً وخوارزمياً — التفاصيل في القسم 12.

---

## 1. اصطلاحات عامة (تنطبق على كل جدول قابل للتعديل)

كل جدول يرث mixin واحداً `SyncMixin`:

```
id           UUID  PK          -- UUIDv7، يمكن توليده في المتصفح (ضروري للمستوى 2: إنشاء سجل دون اتصال بلا تعارض معرّفات)
created_at   timestamptz  NOT NULL default now()
updated_at   timestamptz  NOT NULL                 -- يُحدَّث تلقائياً
version      int          NOT NULL default 1       -- SQLAlchemy version_id_col → قفل تفاؤلي؛ العميل يرسله، 409 عند عدم التطابق
change_seq   bigint       NOT NULL                 -- من sequence عام واحد، يزيد مع كل تعديل → مزامنة دلتا لاحقاً: GET /api/sync?since=N
created_by   UUID FK app_user NULL
updated_by   UUID FK app_user NULL
deleted_at   timestamptz  NULL                     -- حذف ناعم (tombstone) حتى تعلم الأجهزة غير المتصلة بالحذف
```

- **لماذا UUID بدل integer؟** عند تفعيل التعديل دون اتصال، الجهاز ينشئ سجلات قبل أن يراها الخادم؛ بـ integer ستحتاج جدول ربط "معرّف مؤقت ← حقيقي" وإعادة كتابة المراجع. UUIDv7 مرتّب زمنياً فلا يضر الفهارس.
- **كل طلب تعديل** يحمل ترويسة `Idempotency-Key` (UUID من العميل) — انظر `idempotency_key` في القسم 9.
- الاستعلامات العادية تستثني `deleted_at IS NOT NULL` عبر فلتر افتراضي.

---

## 2. المدرسة والإعدادات والتقويم

```
school                        -- صف واحد
  name_ar, name_en            text
  logo_path                   text      -- يُستخدم في رأس كل تقرير (نمط ORG_LOGO_URL)
  default_lang                'ar'|'en'

app_setting                   -- مفتاح/قيمة
  key   text PK               -- مثال: offline_edit_enabled=false, vapid_public_key, report_footer_ar
  value jsonb

academic_year
  name            text        -- "2026/2027"
  start_date, end_date  date
  is_current      bool        -- فهرس فريد جزئي WHERE is_current

term                          -- الفصل الدراسي
  academic_year_id  FK
  name_ar, name_en            -- أول/ثاني
  ordinal           int
  start_date, end_date

weekday                       -- أيام الدوام المعتمدة (قابلة للتخصيص)
  iso_dow     int  UNIQUE     -- 1=الاثنين … 7=الأحد (ISO)
  name_ar, name_en
  sort_order  int             -- ترتيب العرض (الأحد أولاً مثلاً)
  is_school_day bool
```

---

## 3. البنية الأكاديمية

```
stage                         -- أساسي/ثانوي…
  name_ar, name_en, sort_order

grade                         -- الصف ضمن المرحلة
  stage_id  FK
  name_ar, name_en, sort_order

section                       -- الشعبة
  grade_id      FK
  name_ar, name_en            -- "أ"، "ب"
  student_count int NULL
  home_room_id  FK room NULL

division                      -- تقسيم الشعبة لمجموعات (مفهوم ASC)
  section_id  FK
  name        text            -- "أولاد/بنات"، "موسيقى/دراما"
  -- "كامل الشعبة" = lesson_target.group_id IS NULL (لا حاجة لتقسيم "كامل" مخزّن)

student_group
  division_id  FK
  name_ar, name_en            -- "أولاد"، "بنات"، "فرنسي"
  student_count int NULL
```

**القاعدة (مثل ASC):** مجموعات **نفس التقسيم** يمكن أن تكون بنفس الوقت (أولاد+بنات بحصة الرياضة)، أما مجموعات من تقسيمين مختلفين أو "كامل الشعبة" مع أي مجموعة فتعارض.

---

## 4. الوقت: توقيت الحصص لكل يوم

التوقيت يُعرَّف **لكل يوم**، ويمكن ربط نفس التوقيت بأيام وصفوف أخرى. الفكرة: "قالب توقيت" مسمّى يُربط بأي عدد من (صف × يوم).

```
bell_schedule                  -- قالب توقيت: "دوام عادي"، "يوم الخميس القصير"، "ثانوي - عادي"
  name_ar, name_en
  stage_id   FK NULL           -- للتصفية في الواجهة فقط

bell_slot                      -- خانات القالب بالترتيب
  bell_schedule_id  FK
  slot_no     int
  kind        'lesson'|'break'
  period_no   int NULL         -- رقم الحصة (أولى، ثانية…)؛ NULL للفسحة
  label_ar, label_en NULL      -- "الفسحة الأولى"
  starts_at, ends_at  time
  UNIQUE (bell_schedule_id, slot_no)

bell_assignment                -- أي قالب يُطبَّق على أي صف في أي يوم
  term_id     FK
  weekday_id  FK
  stage_id    FK NOT NULL
  grade_id    FK NULL          -- NULL = كل صفوف المرحلة في هذا اليوم
  bell_schedule_id  FK
  UNIQUE NULLS NOT DISTINCT (term_id, weekday_id, stage_id, grade_id)
```

**الحلّ:** للصف ج في اليوم ي: تعيين (صف+يوم) إن وُجد، وإلا تعيين (مرحلة+يوم).

**في الواجهة:** شبكة (صفوف × أيام)، تختار قالباً لخلية ثم "تطبيق على…" مع اختيار أيام وصفوف متعددة دفعة واحدة. تعديل قالب يُحدّث كل الأيام المرتبطة به فوراً؛ و"نسخ كقالب جديد" عندما تريد أن ينفصل يوم عن البقية.

> **التعارض يُحسب على رقم الحصة وليس على الوقت الفعلي.** اختلاف الأوقات موجود فقط في المرحلة الثانوية (10–12)، ومعلموها عادةً غير مشتركين مع الأساسي الأدنى. الأوقات للعرض والطباعة والإشعارات فقط.

---

## 5. الموارد: المباحث، المعلمون، القاعات

```
subject
  name_ar, name_en, short_ar, short_en
  color                  text      -- لون البطاقة
  max_teachers_per_block int  default 1    -- تدريس مشترك حقيقي لنفس المجموعة (نادر)
  requires_room_type     text NULL          -- 'lab','gym','music'…
  -- لا يوجد "سماح بتداخل المعلم": الرياضة/الدراما/الموسيقى = مجموعتان من نفس التقسيم،
  --   لكل مجموعة معلمها، بنفس الحصة. المعلم الواحد لا يكون في مكانين أبداً.

teacher
  name_ar, name_en, short
  email                  text NULL          -- للإشعارات
  gender                 'm'|'f' NULL       -- مفيد لقاعدة معلم/معلمة الرياضة
  color                  text
  user_id                FK app_user NULL UNIQUE  -- إن كان للمعلم حساب لعرض جدوله
  -- قيود ASC الأساسية (مخزّنة من الآن، تُفحص في التحقق، ويستخدمها المولّد لاحقاً):
  target_weekly_periods  int NULL           -- النصاب
  max_periods_per_day    int NULL
  max_gaps_per_day       int NULL
  max_gaps_per_week      int NULL
  max_consecutive        int NULL
  max_days_per_week      int NULL

teacher_stage       (teacher_id, stage_id)      -- المراحل التي يدرّس فيها (للتصفية فقط، لا للصلاحيات)
teacher_subject     (teacher_id, subject_id)    -- المباحث المؤهّل لها (اقتراح عند السحب والإفلات)

building
  name_ar, name_en

room
  building_id  FK NULL
  name_ar, name_en, short
  room_type    text NULL
  capacity     int NULL
  is_shared    bool             -- ملعب/مسرح يتسع لأكثر من صف بنفس الوقت

subject_room  (subject_id, room_id)             -- القاعات المسموحة لمبحث معيّن
```

---

## 6. الجداول والتوزيع (القلب)

```
timetable                      -- نسخة جدول لفصل دراسي
  term_id      FK
  name         text             -- "المسودة 3"، "المعتمد"
  status       'draft'|'published'|'archived'
  cycle_weeks  int default 1    -- 2 = أسبوع أ/ب
  based_on_id  FK timetable NULL  -- نُسخ من
  published_at, published_by
  -- فهرس فريد جزئي: جدول منشور واحد لكل فصل

lesson                         -- "الطلب": ماذا يجب أن يُدرَّس (مفهوم Lesson في ASC)
  timetable_id      FK
  subject_id        FK
  periods_per_week  int          -- مثلاً 5
  duration          int default 1  -- 2 = حصة مزدوجة
  week_no           int NULL     -- NULL = كل الأسابيع؛ 1/2 لأسبوع أ/ب
  preferred_room_id FK room NULL
  notes             text

lesson_teacher                 -- معلم أو أكثر
  lesson_id, teacher_id   (PK مركّب)
  role  'main'|'assistant'
  -- التحقق: عدد المعلمين ≤ subject.max_teachers_per_block

lesson_target                  -- لمن؟ صف واحد = درس عادي، عدة صفوف = درس مشترك (Joint)
  lesson_id   FK
  section_id  FK
  group_id    FK student_group NULL   -- NULL = الشعبة كاملة

card                           -- "البلوك": وضع فعلي لحصة من الدرس في الجدول
  timetable_id  FK             -- مكرر من lesson لتسهيل الفهارس
  lesson_id     FK
  weekday_id    FK NULL        -- NULL = غير موضوعة بعد (في "صندوق" البطاقات)
  period_no     int  NULL      -- حصة البداية
  duration      int            -- يُنسخ من lesson
  week_no       int  NULL
  room_id       FK NULL
  is_locked     bool default false   -- المولّد لا يحرّكها
  -- البطاقات تُنشأ تلقائياً: 5 حصص بمدة 2 ← بطاقتان مزدوجتان + بطاقة مفردة (2+2+1)

occupancy                      -- إشغال محسوب (denormalized) — حارس التعارض على مستوى قاعدة البيانات
  timetable_id   FK
  card_id        FK ON DELETE CASCADE
  resource_type  'teacher'|'room'
  resource_id    UUID
  weekday_id     FK
  periods        int4range     -- [3,4) حصة مفردة، [3,5) مزدوجة
  weeks          int4range     -- [1,2) أسبوع أ فقط، [1,3) كل الأسابيع (دورة أسبوعين)
  EXCLUDE USING gist (
      timetable_id WITH =, resource_type WITH =, resource_id WITH =,
      weekday_id WITH =, periods WITH &&, weeks WITH &&
  )   -- امتداد btree_gist (مدعوم على Neon)
```

**كيف يعمل منع التعارض:**
- **المعلم والقاعة:** قاعدة البيانات نفسها ترفض الحفظ إن تداخلت حصتان (حتى لو أخطأ الكود أو حفظ مستخدمان بنفس اللحظة). المزدوجة تُغطّى تلقائياً بالنطاق.
- القاعات المشتركة (`is_shared`) لا تُكتب لها صفوف.
- **الشعب والمجموعات** (قاعدة التقسيمات) + أسبوع أ/ب تُفحص في محرّك القواعد الموحّد (القسم 12) لأنها لا تُعبَّر عنها بقيد بسيط.

---

## 7. القيود (Time-off + قيود متقدمة)

```
availability                   -- جدول الأوقات المتاحة (Time-off في ASC)
  timetable_id  FK
  entity_type   'teacher'|'section'|'subject'|'room'
  entity_id     UUID
  weekday_id    FK
  period_no     int
  status        'unavailable'|'conditional'   -- الغياب عن الجدول = متاح

constraint_rule                -- مكافئ Card relationships في ASC
  timetable_id  FK
  kind          text           -- 'same_day','not_same_day','max_per_day','before_period',
                               -- 'after_period','consecutive','no_gap_between','groups_start_together',
                               -- 'max_first_period','double_before_single',…
  scope_type    'subject'|'lesson'|'teacher'|'section'|'grade'|'stage'|'global'
  scope_ids     UUID[]
  params        jsonb          -- {"max": 1, "period": 6}
  strength      'hard'|'soft'
  weight        int  NULL      -- للمولّد: أولوية القيد الناعم عند التخفيف
  is_active     bool
```

في المرحلة 1 تُخزَّن هذه القيود ويُفحص الواضح منها في تقرير التحقق؛ تطبيقها الكامل مسؤولية المولّد (المرحلة 3).

---

## 8. البدلاء والتقويم (البدلاء مبنيّون — المرحلة 5)

```
teacher_absence  teacher_id, date_from, date_to, period_from NULL, period_to NULL, reason text, note, extra jsonb
                 -- أسباب الغياب قائمة تعدّلها المدرسة في app_setting["module:cover"] بدل جدول absence_reason
substitution     timetable_id, date, card_id, period_no, original_teacher_id, substitute_teacher_id NULL,
                 kind 'cover'|'merge'|'cancel'|'none', room_id NULL, note, notified_at, auto
                 -- سجل لكل حصة (لا لكل بطاقة) حتى تأخذ الحصة المزدوجة بديلين مختلفين إن لزم
                 -- فريد: (date, card_id, period_no, original_teacher_id) للسجلات الحية
calendar_event   title_ar, title_en, date_from, date_to, kind, cancels_lessons bool,
                 scope_type, scope_ids UUID[]
```

---

## 9. المستخدمون، الإشعارات، والبنية التحتية

```
app_user
  email          citext UNIQUE
  display_name
  password_hash  text NULL        -- NULL لاحقاً إن اعتُمد دخول Microsoft (ms_oid)
  ms_oid         text NULL UNIQUE
  role           'admin'|'stage_editor'|'viewer'
  preferred_lang 'ar'|'en'
  is_active      bool
  valid_until    timestamptz NULL -- لحساب البديل المؤقت: ينتهي تلقائياً
  last_login_at

user_stage       (user_id, stage_id)   -- المراحل المسموحة لـ stage_editor / viewer

push_subscription
  user_id, endpoint UNIQUE, p256dh, auth, user_agent, last_success_at

notification
  user_id, kind, title_ar, title_en, body jsonb, url,
  read_at, email_sent_at, push_sent_at, error

audit_log                          -- من غيّر ماذا (لا يرث SyncMixin — إلحاق فقط)
  id bigint identity, at, user_id, entity_type, entity_id, action, diff jsonb, idempotency_key

idempotency_key                    -- أساس المستوى 2 (مفعّل من اليوم الأول لكل POST/PUT/PATCH/DELETE)
  key            UUID PK
  user_id        FK
  method, path   text
  request_hash   text              -- نفس المفتاح بجسم مختلف ← 422
  status_code    int
  response_body  jsonb
  created_at, expires_at           -- تنظيف بعد 7 أيام مثلاً
```

**الصلاحيات:** `admin` = كل شيء. `stage_editor` = تعديل الدروس والبطاقات التي تستهدف شعباً ضمن مراحله. درس مشترك يمتد لمرحلتين يحتاج صلاحية على كلتيهما. **كشف التعارض يرى كل المراحل دائماً** بغض النظر عن صلاحية المستخدم (المعلم المشترك بين مرحلتين يظهر مشغولاً للجميع).

**المستوى 2 دون اتصال:** الخادم جاهز من اليوم الأول (UUID من العميل، `Idempotency-Key`، `version`، `change_seq`، `deleted_at`). في المتصفح: قاعدة IndexedDB بمخازن `cache` و`outbox` (الأخير فارغ وغير مستخدم) ، والتفعيل عبر `app_setting.offline_edit_enabled`.

---

## 10. التقارير (بدون جداول إضافية)

كل التقارير استعلامات/Views فوق `card` + `lesson*` + `bell_slot`:
جدول معلم، جدول شعبة، جدول قاعة، ملخص كل الصفوف، ملخص كل المعلمين، توزيع المعلمين على الصفوف، توزيع المعلمين على المباحث، إحصائيات (نصاب فعلي مقابل المستهدف، معلمين لكل مبحث، نسبة تغطية الحصص لكل شعبة، بطاقات غير موضوعة) — كلها مع فلترة (مرحلة/صف/شعبة/مبحث/معلم) وتصدير xlsx (openpyxl) و PDF RTL (WeasyPrint) بشعار المدرسة.

---

## 11. سجل القرارات (المراجعة الأولى — 27/09/2026)

| # | القرار |
|---|---|
| 1 | التعارض على **رقم الحصة** بين المراحل، لا على الوقت الفعلي. |
| 2 | التوقيت **لكل يوم** عبر قوالب قابلة للربط بعدة أيام وصفوف (القسم 4). |
| 3 | UUID + حذف ناعم + `change_seq` معتمدة كما في القسم 1. |
| 4 | المولّد التلقائي **ضمن النطاق**، ويجب أن يتفوّق على ASC (القسم 12). |
| 5 | صلاحيات بعمود `role` صريح + `user_stage`. |
| 6 | حُذف `allows_teacher_overlap`؛ الرياضة/الدراما/الموسيقى = مجموعتان من نفس التقسيم. |
| 7 | أسبوع أ/ب: يبقى في المخطط (`cycle_weeks=1` افتراضياً) ومخفي في الواجهة حتى الحاجة. |
| 8 | الدخول: كلمة مرور محلية الآن؛ `ms_oid` جاهز لدخول Microsoft 365 لاحقاً. |
| 9 | (عند البناء) حُذف `division.is_whole`؛ الشعبة الكاملة = `group_id` فارغ. |
| 10 | (عند البناء) `occupancy.weeks` نطاق أسابيع، فيعمل حارس قاعدة البيانات صحيحاً مع أسبوع أ/ب. |
| 11 | (عند البناء) الجداول التابعة (`bell_slot`، `lesson_teacher`، `lesson_target`، جداول الربط) لا ترث SyncMixin؛ تُستبدل كاملة مع الأب، ويرتفع `version` و`change_seq` للأب، فتُزامَن معه. |

---

## 12. المولّد التلقائي ومحرّك القواعد — أين نتفوّق على ASC

### محرّك قواعد واحد لكل شيء
وحدة Python واحدة `rules/` تعرّف كل قيد مرة واحدة، ويستخدمها ثلاثة مستهلكين: **التحقق** (تقرير الأخطاء)، **السحب والإفلات** (تلوين الخانات المسموحة قبل الإفلات)، و**المولّد**. لا يمكن أن يقبل المولّد شيئاً يرفضه التحقق أو العكس.

### المحرّك: Google OR-Tools CP-SAT
- متغيّر منطقي لكل (بطاقة غير مقفلة × يوم × حصة)، بعد تقليص المجال مسبقاً بأوقات عدم التوفر والبطاقات المقفلة.
- **قيود صلبة:** كل بطاقة مرة واحدة؛ لا تعارض معلم/قاعة/مجموعة (قاعدة التقسيمات)؛ المزدوجة متتالية ولا تعبر فسحة؛ Time-off؛ الحدود القصوى للمعلم؛ القواعد الصلبة في `constraint_rule`.
- **دالة هدف موزونة (قيود ناعمة):** تقليل فراغات المعلمين، توزيع حصص المبحث على الأسبوع، تجنّب التتالي الزائد، تفضيلات الحصص الأولى/الأخيرة، إلخ — كل وزن قابل للضبط.

### نقاط التفوّق المحددة
1. **فحص الجدوى الحسابي قبل التوليد.** حسابات فورية تكشف المستحيل قبل تشغيل أي شيء: نصاب المعلم مقابل خاناته المتاحة، مجموع حصص الشعبة مقابل خانات أسبوعها، طلب القاعات الخاصة مقابل عددها في كل حصة (مبدأ برج الحمام). رسالة مثل: «المعلم س: 26 حصة مطلوبة، 24 خانة متاحة فقط».
2. **تفسير الاستحالة بدل التخفيف الأعمى.** ASC يخفّف القيود تلقائياً حتى ينجح. نحن نربط كل مجموعة قيود بمتغيّر افتراض، وعند الاستحالة نستخرج **أصغر مجموعة قيود متعارضة** ونعرضها بالعربية، ليقرر الإنسان أيها يُرخى.
3. **إصلاح بأقل تغيير.** عند تغيّر معلم أو نصاب منتصف الفصل، يُعاد الحل مع عقوبة على كل بطاقة تتحرّك من مكانها الحالي — فيتغيّر عدد قليل من البطاقات بدل جدول جديد كلياً يربك الجميع. والمعلمون المتأثرون فقط يصلهم إشعار.
4. **درجة جودة قابلة للقياس.** كل تشغيل يحفظ مقاييس رقمية (مجموع الفراغات، انتظام التوزيع، القيود الناعمة المخالفة) — فتقارن بين مسودتين بالأرقام لا بالنظر.
5. **نتيجة قابلة للتكرار ومعزولة.** البذرة (seed) محفوظة، والنتيجة تُكتب في **مسودة جديدة** (`based_on_id`) ولا تمسّ الجدول المنشور حتى تعتمدها.

```
generator_run
  timetable_id     FK            -- المصدر
  result_timetable_id FK NULL    -- المسودة الناتجة
  mode             'full'|'repair'
  status           'queued'|'feasibility_failed'|'running'|'solved'|'infeasible'|'timeout'|'cancelled'
  params           jsonb         -- الأوزان، المهلة، البذرة
  feasibility      jsonb         -- نتائج فحص الجدوى
  infeasible_core  jsonb NULL    -- أصغر مجموعة قيود متعارضة
  metrics          jsonb         -- درجة الجودة
  objective        bigint NULL
  started_at, finished_at, created_by
```

يعمل في الخلفية بمهلة محددة، والتقدّم يظهر في الواجهة، وإشعار Push عند الانتهاء.

> صراحةً: لا يمكن ضمان التفوّق على ASC في كل مدرسة مسبقاً؛ سنقيس ذلك على بيانات مدرستكم الفعلية (نفس المدخلات في الاثنين، ومقارنة المقاييس) قبل اعتماد المولّد.
