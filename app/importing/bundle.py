"""Neutral, source-independent description of what a file contains.

Records refer to each other by `key` (a normalised name for spreadsheets, the aSc
id for aSc files). Missing optional values are None: an import never blanks out a
field that the file does not mention.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Issue:
    message: str
    message_en: str
    where: str = ""      # sheet / section of the file
    row: int | None = None

    def as_dict(self) -> dict:
        d = {"message": self.message, "message_en": self.message_en}
        if self.where:
            d["where"] = self.where
        if self.row is not None:
            d["row"] = self.row
        return d


@dataclass
class Bundle:
    source: str                       # 'asc' | 'xlsx' | 'csv'
    subjects: list[dict] = field(default_factory=list)
    teachers: list[dict] = field(default_factory=list)
    rooms: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)   # {key, stage, grade, name, …}
    divisions: list[dict] = field(default_factory=list)  # {section, name, groups: [{key, name, student_count}]}
    lessons: list[dict] = field(default_factory=list)    # {key, subject, targets: [(section, group|None)], teachers, ppw, duration, room}
    cards: list[dict] = field(default_factory=list)      # {lesson, day, period, duration, room}   (aSc only)
    periods: list[dict] = field(default_factory=list)    # {no, start, end}                        (aSc only)
    days: int = 0                                        # number of days in the aSc week
    # Spreadsheets refer to sections by the names people type; aSc by id.
    by_name: bool = True
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    def error(self, ar: str, en: str, where: str = "", row: int | None = None):
        self.errors.append(Issue(ar, en, where, row))

    def warn(self, ar: str, en: str, where: str = "", row: int | None = None):
        self.warnings.append(Issue(ar, en, where, row))

    def is_empty(self) -> bool:
        return not any((self.subjects, self.teachers, self.rooms, self.sections, self.lessons))
