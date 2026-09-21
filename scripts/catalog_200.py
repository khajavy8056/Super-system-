"""Append docs/200 workbooks recursively, without altering source barcodes or loading images."""
from pathlib import Path
import hashlib
import json
import re
import openpyxl

DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
def text(value):
    if value is None: return ''
    if isinstance(value, float) and value.is_integer(): return str(int(value))
    return str(value).strip().replace('\r', ' ').replace('\n', ' ')
def key(value):
    return re.sub(r'[\s\u200c]+', '', text(value)).replace('ي','ی').replace('ك','ک')
def append(records, root):
    known = {r['barcode']: r for r in records}
    report = {'files': [], 'rows': 0, 'added': 0, 'duplicate_barcodes': 0, 'missing_barcodes': 0, 'conflicts': [], 'source_images': []}
    for path in sorted(Path(root).rglob('*.xlsx')):
        if path.name.startswith('~$'): continue
        rel = path.relative_to(root).as_posix()
        report['files'].append(rel)
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in wb:
                rows = sheet.iter_rows(values_only=True)
                header = [key(v) for v in next(rows, ())]
                if 'ناممحصول' not in header or 'بارکد' not in header:
                    raise ValueError(f'Unknown product columns: {rel}/{sheet.title}')
                for line, row in enumerate(rows, 2):
                    d = {k: text(v) for k,v in zip(header,row)}
                    name = d.get('ناممحصول','')
                    if not name: continue
                    report['rows'] += 1
                    bc = d.get('بارکد','').translate(DIGITS)
                    if not bc:
                        identity = f'{rel}\0{sheet.title}\0{line}\0{name}'
                        bc = 'INT-X' + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
                        report['missing_barcodes'] += 1
                    image = d.get('نامتصویر') or d.get('نامعکس') or d.get('آدرستصویر') or ''
                    report['source_images'].append({'file':rel,'sheet':sheet.title,'row':line,'barcode':bc,'name':name,'image_filename':image})
                    if bc in known:
                        report['duplicate_barcodes'] += 1
                        if name != known[bc]['name']:
                            report['conflicts'].append({'file':rel,'row':line,'barcode':bc,'kept':known[bc]['name'],'incoming':name})
                        continue
                    rec = {'barcode':bc, 'name':name, 'category':d.get('دستهبندی') or path.parent.name,
                           'subcategory':d.get('زیردستهبندی') or d.get('زیرگروه') or d.get('گروه') or '',
                           'images':[], '_exact_source':True}
                    records.append(rec);known[bc]=rec;report['added']+=1
        finally: wb.close()
    report['total_products'] = len(records)
    return report
