"""Importing school data and timetables from Excel / CSV files and from aSc Timetables (XML, .roz).

Every source is first parsed into a neutral `Bundle` (bundle.py); a single `Importer`
(apply.py) then matches it against what is already in the database and creates or
updates records. Preview and commit run the very same code: the preview simply rolls
the transaction back, so what you see is exactly what the commit will do.
"""
