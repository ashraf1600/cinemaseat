import pypdf
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

pdf_path = r'd:\Semester_4_1\cinemaseat\backend\CinemaSeat_API_and_ER_Documentation.pdf'
reader = pypdf.PdfReader(pdf_path)
print(f'TOTAL_PAGES: {len(reader.pages)}')
print('=' * 80)
for i, page in enumerate(reader.pages):
    print(f'\n===== PAGE {i+1} =====')
    text = page.extract_text()
    print(text)