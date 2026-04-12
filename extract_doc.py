from docx import Document

doc = Document('PROMPTS_MAESTROS_Empanadas_Bot.docx')
for para in doc.paragraphs:
    if para.text.strip():
        print(para.text)
