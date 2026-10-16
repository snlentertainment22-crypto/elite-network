import io, sqlite3, zipfile, re, openpyxl
z = zipfile.ZipFile(r"C:\Users\L-cwa\Desktop\Possible Trivia Questions.zip")
n = next(x for x in z.namelist() if x.endswith("_(Old 0-15236) Questions.xlsx"))
ws = openpyxl.load_workbook(io.BytesIO(z.read(n)), read_only=True, data_only=True).active
