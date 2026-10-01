// Arabic is the source language; English comes from this dictionary (keyed by the Arabic text).
//   t('نص')               → translated string for the current language
//   captureStaticText()   → remembers the Arabic text of the static page once
//   setLang('en' | 'ar')  → switches direction + static text, then notifies views to re-render
const I18N = {
  '(عدم الاختيار يعني جميع صفوف المرحلة)': '(none selected = every grade in the stage)',
  'أخطاء': 'Errors', 'أضف شعبة أولاً': 'Add a section first',
  'أضف فصلاً دراسياً ومرحلة أولاً': 'Add a term and a stage first',
  'أقصى عدد من أيام الدوام': 'Max working days', 'أقصى عدد من الحصص المتتالية': 'Max consecutive periods',
  'أقصى عدد من الحصص يومياً': 'Max periods per day', 'أقصى عدد من المعلمين في البطاقة الواحدة': 'Max teachers on one card',
  'أقصى عدد من الفجوات أسبوعياً': 'Max gaps per week', 'أقصى عدد من الفجوات يومياً': 'Max gaps per day', 'أنثى': 'Female',
  'أنشئ قوالب التوقيت (مثل: دوام عادي، يوم قصير)، ثم حدِّد القالب لكل يوم ولكل صف. والصف الذي لا يُحدَّد له قالب يأخذ قالب مرحلته. ويُحتسَب تعارض المعلمين على رقم الحصة لا على وقتها.':
    'Create timing templates (e.g. normal day, short day), then choose the template for each day and grade. A grade without its own template uses its stage\'s. Teacher clashes are checked by period number, not clock time.',
  'أوقات عدم التوفر': 'Unavailable times', 'أولاد/بنات': 'Boys/Girls', 'أولاد، بنات': 'Boys, Girls',
  'أيام الأسبوع': 'Weekdays', 'أُزيلت الحصة من الجدول': 'Card removed from the timetable', 'إضافة': 'Add',
  'إعادة الفحص': 'Re-check', 'إلغاء': 'Cancel', 'إلى': 'To',
  'اتركها فارغةً للإبقاء على كلمة المرور الحالية (ثمانية أحرف على الأقل)': 'Leave empty to keep the current one (min 8 characters)',
  'اختر خانةً خضراء لوضع الحصة فيها، أو أفلِتها في صندوق "غير مُدرَجة" لإزالتها من الجدول.':
    'Choose a green cell to place the card, or drop it in "Unplaced" to remove it from the timetable.',
  'اختر قالباً ويوماً واحداً على الأقل': 'Choose a template and at least one day',
  'اختر من القائمة': 'Choose from the list', 'اختر من القائمة لعرض الجدول': 'Choose from the list to show the timetable',
  'اختصار': 'Short', 'اختصار (عربي)': 'Short (Arabic)',
  'اسحب الحصة، أو انقر عليها ثم انقر على الخانة المطلوبة. الخانات الخضراء متاحة، والحمراء فيها تعارض (مرِّر المؤشر فوقها لمعرفة السبب).':
    'Drag a card, or tap it then tap a cell. Green cells are allowed; red cells have a conflict (hover to see why).',
  'اسم التقسيم': 'Division name', 'اسم القالب': 'Template name', 'اسم المدرسة (إنجليزي)': 'School name (English)',
  'اسم المدرسة (عربي)': 'School name (Arabic)', 'اسم المسودة الجديدة': 'New draft name',
  'انقر على الخانة للتبديل بين «متاح» و«غير متاح». لا تُوضَع الحصص في الخانات غير المتاحة.':
    'Click a cell to toggle available / unavailable. Cards cannot be placed in unavailable cells.',
  'انقر لقفل الحصة': 'Click to lock',
  'اعمل على مسودة ثم انشرها. ويؤدي النشر إلى أرشفة الجدول المنشور سابقاً للفصل نفسه، والجدول المؤرشف للقراءة فقط.':
    'Work on a draft, then publish it. Publishing archives the previously published timetable of the term; archived timetables are read-only.',
  'الأيام': 'Days', 'الإعداد': 'Setup', 'الاسم': 'Name', 'الاسم (إنجليزي)': 'Name (English)', 'الاسم (عربي)': 'Name (Arabic)',
  'البريد الإلكتروني': 'Email', 'التحقق': 'Validation', 'الترتيب': 'Order', 'التسمية': 'Label',
  'يقسم التقسيمُ الشعبةَ إلى مجموعات تُدرَّس في الحصة نفسها، مثل: التربية الرياضية (أولاد / بنات)، أو (موسيقى / دراما). ويجوز أن تجتمع مجموعات التقسيم الواحد في حصة واحدة، أما مجموعات تقسيمين مختلفين فتتعارض.':
    'A division splits a section into groups taught in the same period, e.g. PE (boys / girls) or (music / drama). Groups of one division may share a period; groups of different divisions conflict.',
  'التقسيمات والمجموعات': 'Divisions & groups', 'التوقيت لكل يوم وصف': 'Timing per day and grade', 'الجداول': 'Timetables',
  'الجداول (المسودّات والمنشورة)': 'Timetables (draft/published)', 'في الجدول أخطاء': 'The timetable has errors',
  'الجدول:': 'Timetable:', 'الجنس': 'Gender', 'الحالة': 'Status', 'الحصة': 'Period',
  'الحصة مقفلة؛ ألغِ قفلها أولاً': 'Card is locked; unlock it first', 'الحقل': 'Field', 'الدروس والتوزيع': 'Lessons & allocation',
  'الدور': 'Role', 'السعة': 'Capacity', 'السنة الحالية': 'Current year', 'السنة الدراسية': 'Academic year',
  'السنوات الدراسية': 'Academic years', 'الشعب': 'Sections', 'الشعب / المجموعات': 'Sections / groups',
  'الشعب / المجموعات (اختيار أكثر من شعبة يعني درساً مشتركاً)': 'Sections / groups (several sections = joint lesson)',
  'الشعبة': 'Section', 'الصف': 'Grade', 'الصفحة غير موجودة': 'Page not found', 'الصفوف': 'Grades', 'العربية': 'Arabic',
  'الغرفة الصفية': 'Home room', 'الاستراحة': 'Break', 'الفصل': 'Term', 'الفصل الدراسي': 'Term', 'الفصول الدراسية': 'Terms',
  'القائمة': 'Menu', 'القاعات': 'Rooms', 'القاعات المسموحة': 'Allowed rooms', 'القاعة المفضلة': 'Preferred room',
  'القالب': 'Template', 'الكل': 'All', 'اللغة': 'Language', 'اللون': 'Colour', 'المباحث': 'Subjects',
  'المباحث المؤهّل لها': 'Qualified subjects', 'المباني': 'Buildings', 'المبحث': 'Subject', 'المبنى': 'Building',
  'المجموعات (افصل بينها بفاصلة)': 'Groups (comma separated)', 'المدة': 'Duration', 'المراحل': 'Stages',
  'المراحل التي يدرّس فيها': 'Stages taught in', 'المراحل المسموحة (لمحرّر المرحلة)': 'Allowed stages (for stage editors)',
  'المرحلة': 'Stage', 'المستخدمون': 'Users', 'المسودة 1': 'Draft 1', 'المعروض حالياً': 'Currently shown', 'المعلم': 'Teacher',
  'المعلمون': 'Teachers', 'المُدرَج': 'Placed', 'المُدرَج في الجدول': 'Placed', 'المُسنَد': 'Assigned',
  'أتريد النشر على الرغم من ذلك؟': 'Publish anyway?', 'النصاب': 'Target load', 'النصاب الأسبوعي': 'Weekly target load', 'النظام': 'System',
  'النوع': 'Type', 'اليوم': 'Day', 'موعد بدء الحصة الأولى': 'First period starts', 'بطاقة': 'cards',
  'بيانات المدرسة': 'School details', 'تأكيد': 'Confirm', 'تتمّة': 'cont.', 'تاريخ البداية': 'Start date',
  'تاريخ النشر': 'Published on', 'تاريخ النهاية': 'End date', 'تحذيرات': 'Warnings', 'تطبيق': 'Apply',
  'على هذه الصفحة': 'On this page', 'انتقل إلى': 'Jump to',
  'تطبيق قالب على عدة أيام وصفوف دفعةً واحدة': 'Apply a template to several days and grades at once', 'تعديل': 'Edit',
  'تعديل الحصص': 'Edit periods', 'تعديل الدرس': 'Edit lesson', 'تقسيم جديد': 'New division', 'تم التطبيق': 'Applied',
  'تم الحذف': 'Deleted', 'تم الحفظ': 'Saved',
  'تم الحفظ، وأُعيد إنشاء البطاقات لتغيّر مدتها': 'Saved — the card length changed, so the cards were recreated',
  'تم النسخ': 'Copied', 'تم النشر، وأُرشِف الجدول المنشور سابقاً': 'Published; the previously published timetable is now archived',
  'تم وضع الحصة': 'Card placed', 'توقيت الحصص': 'Bell schedules', 'جارٍ التحميل…': 'Loading…', 'جدول جديد': 'New timetable',
  'جدولة الحصص': 'School Timetable', 'حذف': 'Delete', 'أتريد حذف الدرس وجميع بطاقاته من الجدول؟': 'Delete the lesson and all its cards?',
  'أتريد حذف هذا السجل؟': 'Delete this record?', 'حساب المستخدم المرتبط': 'Linked user account', 'حسب الشعبة': 'By section',
  'حسب القاعة': 'By room', 'حسب المعلم': 'By teacher', 'حصة': 'Period', 'حصة مزدوجة': 'Double period', 'حصة مفردة': 'Single period',
  'حصص القالب': 'Template periods', 'حصص متتالية': 'consecutive periods', 'الحصص المُدرَجة': 'Periods placed', 'الحصص أسبوعياً': 'Periods/week',
  'حفظ': 'Save', 'حفظ الحصص': 'Save periods', 'تسجيل الخروج': 'Log out', 'درس جديد': 'New lesson', 'دوام عادي': 'Normal day', 'ذكر': 'Male',
  'رابط الشعار': 'Logo URL', 'شبكة الجدول': 'Timetable grid', 'شعبة': 'Section',
  'صالح حتى تاريخ (للحساب البديل المؤقت)': 'Valid until (temporary substitute account)', 'عامّ لجميع المراحل': 'General', 'عدد الحصص': 'Periods',
  'عدد الحصص أسبوعياً': 'Periods per week', 'عدد الطلبة': 'Students', 'عرض في الجدول': 'Show in grid', 'غير متاح': 'Unavailable',
  'غير مُدرَجة': 'Unplaced', 'فتح': 'Open', 'استراحة': 'Break', 'استراحة بعد الحصص (مثال: 3، 5)': 'Break after periods (e.g. 3,5)',
  'مفعَّل': 'Active', 'قاعة': 'Room', 'قالب توقيت جديد': 'New timing template', 'قوالب التوقيت': 'Timing templates',
  'كامل الشعبة': 'whole section', 'أُدرِجت الحصص كلها': 'All cards placed', 'جميع صفوف المرحلة': 'All grades of the stage',
  'كلمة المرور': 'Password', 'لا توجد تقسيمات لهذه الشعبة': 'No divisions for this section', 'لا توجد دروس مطابقة': 'No matching lessons',
  'لا توجد سجلات بعد': 'No records yet', 'لا توجد عناصر': 'No items', 'لا توجد قوالب بعد': 'No templates yet',
  'لا توجد مجموعات': 'No groups', 'لا شيء': 'None',
  'لا يوجد اتصال، ولا نسخة محفوظة من هذه البيانات': 'Offline and no saved copy of this data',
  'لا يوجد اتصال بالإنترنت — وضع العرض فقط، ولا يمكن الحفظ الآن': 'Offline — view only, saving is not possible right now',
  'لا يوجد جدول بعد': 'No timetable yet',
  'لا يوجد جدول بعد. أنشئ سنةً دراسية وفصلاً دراسياً، ثم جدولاً جديداً.': 'No timetable yet. Create an academic year and a term, then a new timetable.',
  'لم يُحدَّد جدول بعد. أنشئ جدولاً من صفحة "الجداول".': 'No timetable selected. Create one on the "Timetables" page.',
  'لحصص الأولاد والبنات، أو الموسيقى والدراما، استخدم مجموعتين من التقسيم نفسه بدلاً من رفع هذا الرقم':
    'For boys/girls or music/drama, use two groups of one division instead of raising this number',
  'مؤرشف': 'archived', 'مبحث': 'Subject', 'متاح': 'Available', 'مجموعة': 'Group', 'مجموعة جديدة': 'New group',
  'محرّر مرحلة': 'Stage editor', 'مدة البطاقة': 'Card length', 'مدة الحصة (بالدقائق)': 'Period length (min)',
  'مدة الاستراحة (بالدقائق)': 'Break length (min)', 'مدير النظام': 'Administrator', 'مزدوجة': 'Double', 'مسودة': 'draft',
  'مشاهد': 'Viewer', 'مشتركة (تتّسع لأكثر من صف في الوقت نفسه)': 'Shared (holds several classes at once)', 'معلم': 'Teacher',
  'مفردة': 'Single', 'مقفلة — انقر لإلغاء القفل': 'Locked — click to unlock', 'ملاحظات': 'Notes',
  'ملخص نصاب المعلمين': 'Teacher load summary', 'من': 'From', 'منشور': 'published', 'نسبة الإنجاز': 'Completion',
  'نسخ كقالب جديد': 'Copy as new template', 'نسخ كمسودة': 'Copy as draft', 'نسخة': 'copy', 'نشر': 'Publish',
  'نوع القاعة': 'Room type', 'نوع القاعة المطلوب': 'Required room type', 'هذا الجدول مؤرشف وللقراءة فقط': 'This timetable is archived and read-only',
  'يظهر الشعار في رأس الواجهة وفي كل تقرير مطبوع أو مُصدَّر.': 'The logo appears in the header and on every printed or exported report.',
  'يوم دراسي': 'School day', '— بدون —': '— none —', '— وفق المرحلة —': '— stage default —',
  'التقارير': 'Reports',
  'التقرير': 'Report',
  'تصدير Excel': 'Export Excel',
  'تصدير PDF': 'Export PDF',
  'لغة الملف': 'File language',
  'طباعة': 'Print',
  'لا توجد بيانات مطابقة': 'No matching data',
  'لا يوجد اتصال، لا يمكن التصدير الآن': 'Offline — cannot export now',
  'الجدول الأسبوعي للشعبة': 'Section weekly timetable',
  'جدول حصص المعلم': 'Teacher timetable',
  'جدول إشغال القاعة': 'Room timetable',
  'توزيع المعلمين على الشعب': 'Teachers by section',
  'توزيع المعلمين على المباحث': 'Teachers by subject',
  'إحصائيات المعلمين والنصاب': 'Teacher load statistics',
  'إحصائيات المباحث': 'Subject statistics',
  'تغطية الحصص في الشعب': 'Section coverage',
  'احفظ اسم المدرسة أولاً، ثم ارفع الشعار': 'Save the school name first, then upload the logo',
  'تم رفع الشعار': 'Logo uploaded',
  'أتريد حذف الشعار؟': 'Delete the logo?',
  'شعار المدرسة': 'School logo',
  'اختيار صورة الشعار': 'Choose logo image',
  'حذف الشعار': 'Delete logo',
  'صيغة PNG أو JPEG، بحجم لا يتجاوز 1 ميغابايت. يظهر الشعار في رأس الواجهة وفي كل تقرير مطبوع أو مُصدَّر (Excel وPDF).': 'PNG or JPEG, up to 1 MB. The logo appears in the header and on every printed or exported report (Excel and PDF).',
  'مربي الصف': 'Class teacher',
  'الجدول': 'Timetable',
  'الدروس': 'Lessons',
  'التقسيمات': 'Divisions',
  'اللقب': 'Title',
  'الهاتف': 'Phone',
  'هذه الحصة لا تخص هذا الصف من الجدول': 'This card does not belong to that row',
  'جميع المراحل': 'All stages',
  'الأيام صفوفاً': 'Days as rows',
  'الأيام أعمدةً': 'Days as columns',
  'الجدول الكامل — الشعب': 'Whole school — sections',
  'الجدول الكامل — المعلمون': 'Whole school — teachers',
  'اتجاه الجدول': 'Layout',
  'الأيام صفوفاً (نمط ASC)': 'Days as rows (ASC style)',
  'الأيام أعمدةً ': 'Days as columns',
  'الموقع': 'Location', 'English': 'العربية',
  grade: 'grades', section: 'sections', lesson: 'lessons', card: 'cards', teacher: 'teachers',
  'CSV: جدول واحد بالعناوين نفسها، ويُقبل الترميز UTF-8 وترميز ويندوز العربي.': 'CSV: a single table with the same headings; UTF-8 and Windows Arabic encodings are accepted.',
  'Excel ‏(‎.xlsx): استخدم القالب الجاهز؛ لكل نوع من البيانات ورقة مستقلة.': 'Excel (.xlsx): use the ready-made template; one sheet per kind of data.',
  'aSc Timetables: صدِّر من البرنامج عبر: ملف ← تصدير ← aSc Timetables XML، وارفع ملف ‎.xml. ويُقبل ملف ‎.roz إذا كان بصيغة XML.': 'aSc Timetables: in aSc choose File → Export → aSc Timetables XML and upload the .xml file. A .roz file is accepted when it contains XML.',
  'أمثلة من الجديد': 'Examples of new records',
  'اختيار ملف': 'Choose file',
  'استورد المعلمين والمباحث والقاعات والشعب والدروس من ملف Excel أو CSV، أو استورد جدولاً كاملاً من aSc Timetables. تُعرض معاينة أولاً، ولا يُحفظ شيء قبل التأكيد، ولا يتكرر شيء عند إعادة الاستيراد.': 'Import teachers, subjects, rooms, sections and lessons from Excel or CSV, or a whole timetable from aSc Timetables. You see a preview first; nothing is saved until you confirm, and re-importing never creates duplicates.',
  'اسم المرحلة الجديدة': 'New stage name',
  'الأسطر التي فيها أخطاء لن تُستورد، ويُستورد الباقي. يمكنك تصحيح الملف وإعادة المعاينة.': 'Rows with errors will be skipped; the rest will be imported. You can fix the file and preview again.',
  'الاستيراد': 'Import',
  'الجدول المعروض حالياً': 'The timetable shown now',
  'الحصص الموزعة على الجدول': 'Cards placed on the timetable',
  'الدروس والحصص تُستورد إلى': 'Import lessons and cards into',
  'السطر': 'Row',
  'المرحلة للشعب التي لم تُحدَّد مرحلتها': 'Stage for sections without one',
  'الملخص': 'Summary',
  'بلا تغيير': 'Unchanged',
  'تأكيد الاستيراد': 'Confirm import',
  'تحديث': 'Updated',
  'تلقائي': 'Automatic',
  'تم الاستيراد': 'Import complete',
  'تنبيهات': 'Notices',
  'تنزيل قالب Excel': 'Download Excel template',
  'جارٍ قراءة الملف…': 'Reading the file…',
  'جدول جديد باسم': 'A new timetable named',
  'جدول مستورد': 'Imported timetable',
  'جديد': 'New',
  'غير الموزعة': 'Unplaced',
  'فتح شبكة الجدول': 'Open the timetable grid',
  'لا توجد بيانات صالحة للاستيراد': 'No valid data to import',
  'لم يُختر ملف': 'No file chosen',
  'محتوى ملف CSV': 'CSV contents',
  'مرحلة جديدة…': 'New stage…',
  'مستورد': 'Imported',
  'معاينة': 'Preview',
  'معاينة الاستيراد — لم يُحفظ شيء بعد': 'Import preview — nothing saved yet',
  'تحديد تلقائي من العناوين': 'Detect from headings',
  'المجموعات': 'Groups',
  'أوقات الحصص والاستراحات لكل يوم': 'Period and break times for each day',
  'إنشاء جدول (مسودة)': 'Create a timetable (draft)',
  'اختر الملف': 'Choose the file',
  'استيراد ملف aSc ‏(XML) أو Excel': 'Import an aSc (XML) or Excel file',
  'اضغط «معاينة» لترى ما سيُضاف قبل الحفظ': 'Press "Preview" to see what will be added before saving',
  'اضغط هنا لاختيار الملف': 'Tap here to choose the file',
  'افتح': 'Open',
  'الاسم والشعار': 'Name and logo',
  'البداية': 'Start',
  'التحقق والنشر': 'Validate and publish',
  'الحصص': 'Cards',
  'الخطوة التالية': 'Next step',
  'السنة والفصل الدراسي': 'Year and term',
  'السنوات': 'Years',
  'الفصول': 'Terms',
  'المباحث والمعلمون': 'Subjects and teachers',
  'المراحل والصفوف والشعب': 'Stages, grades and sections',
  'توزيع الحصص على الجدول': 'Place the cards on the timetable',
  'خطوات إعداد الجدول': 'Steps to build the timetable',
  'خيارات إضافية (اختيارية)': 'More options (optional)',
  'راجع الأخطاء ثم انشر الجدول': 'Review the errors, then publish',
  'راجع المعاينة ثم اضغط «تأكيد الاستيراد»': 'Review the preview, then press "Confirm import"',
  'ملف aSc ‏(‎.xml) أو Excel ‏(‎.xlsx) أو CSV': 'aSc file (.xml), Excel (.xlsx) or CSV',
  'من أين أحصل على الملف؟': 'Where do I get the file?',
  'يُدخل المعلمين والمباحث والشعب والدروس والجدول دفعةً واحدة': 'Brings in teachers, subjects, sections, lessons and the timetable in one go',
  'الاستيراد (aSc / Excel)': 'Import (aSc / Excel)',
  'ستُحذف البيانات الحالية أولاً': 'Current data will be deleted first',
  'البدء من جديد: حذف كل البيانات الحالية قبل الاستيراد': 'Start over: delete all current data before importing',
  'حُذفت البيانات السابقة': 'Previous data deleted',
  'سيُحذف كل ما في النظام من بيانات (المعلمون والمباحث والشعب والجداول والتوقيت) ويُستبدل بما في الملف. لا يمكن التراجع. أتريد المتابعة؟': 'All data in the system (teachers, subjects, sections, timetables, bell times) will be deleted and replaced by the file. This cannot be undone. Continue?',
  'يُبقي المستخدمين واسم المدرسة وشعارها وأيام الأسبوع فقط. استخدمه لاستيراد ملف aSc جديد بدل القديم.': 'Keeps only users, the school name and logo, and the weekdays. Use it to import a new aSc file instead of the old one.',
  'يمكن اختيار أكثر من ملف معاً، مثل ملف aSc ‏(‎.xml) مع ملف Excel لتوقيت الحصص.': 'You can pick several files together, e.g. the aSc file (.xml) with an Excel file of bell times.',
  'طباعة PDF': 'Print PDF',
  'إسناد التوقيت للأيام والصفوف': 'Timing assigned to days and grades',
};

function readLang() {
  try { return localStorage.getItem('lang') === 'en' ? 'en' : 'ar'; } catch (_) { return 'ar'; }
}
export let lang = readLang();

export function t(ar) {
  if (lang !== 'en') {
    // Arabic UI: map technical table names (used in dependency errors) to Arabic.
    return { grade: 'صفوف', section: 'شعب', lesson: 'دروس', card: 'بطاقات', teacher: 'معلمون', division: 'تقسيمات',
             student_group: 'مجموعات', term: 'فصول', timetable: 'جداول', bell_assignment: 'توقيت مرتبط' }[ar] || ar;
  }
  return I18N[ar] ?? ar;
}

// Counted nouns with correct Arabic agreement: 1 → «بطاقة واحدة»، 2 → «بطاقتان»، 3–10 → «3 بطاقات»، 11+ → «11 بطاقة».
const NOUNS = {
  card: ['بطاقة', 'بطاقتان', 'بطاقات', true, 'card', 'cards'],
  record: ['سجل', 'سجلان', 'سجلات', false, 'record', 'records'],
};
export function countAr(n, noun) {
  const [one, two, few, fem, en1, enN] = NOUNS[noun];
  if (lang === 'en') return `${n} ${n === 1 ? en1 : enN}`;
  if (n === 1) return `${one} ${fem ? 'واحدة' : 'واحد'}`;
  if (n === 2) return two;
  const r = n % 100;
  return r >= 3 && r <= 10 ? `${n} ${few}` : `${n} ${one}`;
}

const originals = [];  // [node, attr|null, arabicText]
export function captureStaticText(root = document.body) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const s = n.nodeValue.trim();
    if (s && /[؀-ۿ]/.test(s) && !n.parentElement.closest('#view')) originals.push([n, null, s]);
  }
  root.querySelectorAll('[aria-label],[title],[placeholder]').forEach(el => {
    for (const a of ['aria-label', 'title', 'placeholder']) {
      const v = el.getAttribute(a);
      if (v && /[؀-ۿ]/.test(v)) originals.push([el, a, v]);
    }
  });
  originals.push([document, 'title', document.title]);
}

function applyStatic() {
  for (const [node, attr, ar] of originals) {
    const val = t(ar);
    if (node === document) document.title = val;
    else if (attr) node.setAttribute(attr, val);
    else node.nodeValue = node.nodeValue.replace(node.nodeValue.trim(), val);
  }
  const btn = document.getElementById('lang-toggle');
  if (btn) btn.textContent = lang === 'en' ? 'العربية' : 'English';
}

const langListeners = new Set();
export function onLangChange(fn) { langListeners.add(fn); }

export function setLang(l) {
  const changed = l !== lang;
  lang = l;
  try { localStorage.setItem('lang', l); } catch (_) { /* private mode */ }
  document.documentElement.lang = l;
  document.documentElement.dir = l === 'en' ? 'ltr' : 'rtl';
  applyStatic();
  if (changed) langListeners.forEach(fn => fn(l));
}
