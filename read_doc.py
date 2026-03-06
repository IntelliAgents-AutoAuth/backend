import win32com.client
import os
import sys

# Must be absolute path
path = os.path.abspath("Sample Architecture Document_virtusa_stage_2.doc")
text = ""
try:
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    doc = word.Documents.Open(path)
    text = doc.Content.Text
    doc.Close(False)
    word.Quit()
    print("Read with win32com")
    print("==CONTENT_START==")
    print(text.encode("utf-8", "ignore").decode("utf-8"))
    print("==CONTENT_END==")
except Exception as e:
    print(f"Failed with Word.Application: {e}")
    # try reading as docx anyway
    try:
        import docx
        doc = docx.Document(path)
        print("Read with python-docx")
        print("==CONTENT_START==")
        for para in doc.paragraphs:
            print(para.text.encode("utf-8", "ignore").decode("utf-8"))
        print("==CONTENT_END==")
    except Exception as e2:
        print(f"Failed with python-docx: {e2}")
