"""Uniform bilingual API errors: {"error": code, "message": ar, "message_en": en, "details": ...}."""
from __future__ import annotations

from flask import jsonify

MESSAGES = {
    "unauthorized": ("يجب تسجيل الدخول", "Login required"),
    "forbidden": ("لا تملك صلاحية على هذه المرحلة أو هذا الإجراء", "You do not have permission for this stage or action"),
    "not_found": ("السجل غير موجود", "Record not found"),
    "validation": ("بيانات غير صالحة", "Invalid data"),
    "version_conflict": ("عدّل مستخدم آخر هذا السجل؛ أعد التحميل ثم حاول مجدداً", "Record was changed by someone else; reload and retry"),
    "idempotency_key_required": ("ترويسة Idempotency-Key مطلوبة لكل عملية تعديل", "Idempotency-Key header is required for every write"),
    "idempotency_key_reused": ("نفس معرّف العملية استُخدم لطلب مختلف", "Idempotency key was reused for a different request"),
    "idempotency_in_progress": ("نفس العملية قيد التنفيذ الآن", "The same request is already being processed"),
    "has_dependents": ("لا يمكن الحذف: توجد سجلات مرتبطة به", "Cannot delete: other records depend on it"),
    "duplicate": ("السجل موجود مسبقاً", "Record already exists"),
    "placement_conflict": ("لا يمكن وضع الحصة هنا بسبب تعارض", "Cannot place the card here due to a conflict"),
    "timetable_readonly": ("هذا الجدول مؤرشف ولا يمكن تعديله", "This timetable is archived and read-only"),
    "integrity": ("تعارض مع قيد في قاعدة البيانات", "Database constraint violated"),
}


class ApiError(Exception):
    def __init__(self, code: str, status: int = 400, details=None, message: str | None = None, message_en: str | None = None):
        super().__init__(code)
        ar, en = MESSAGES.get(code, (code, code))
        self.code = code
        self.status = status
        self.details = details
        self.message = message or ar
        self.message_en = message_en or en

    def body(self) -> dict:
        out = {"error": self.code, "message": self.message, "message_en": self.message_en}
        if self.details is not None:
            out["details"] = self.details
        return out

    def response(self):
        return jsonify(self.body()), self.status
