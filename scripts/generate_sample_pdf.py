from pathlib import Path

import pymupdf

# 1. Create the PDF
corpus_dir = Path("data/corpus")
corpus_dir.mkdir(parents=True, exist_ok=True)
pdf_path = corpus_dir / "Apollo_11_Mission_Report.pdf"

doc = pymupdf.open()
# Page 1
page1 = doc.new_page()
text1 = (
    "Apollo 11 Lunar Landing Summary\n\n"
    "Apollo 11 was the American spaceflight that first landed humans on the Moon. "
    "Commander Neil Armstrong and Lunar Module Pilot Buzz Aldrin landed the Apollo Lunar Module Eagle "
    "on July 20, 1969, at 20:17 UTC. Armstrong became the first person to step onto the lunar surface "
    "six hours and 39 minutes later, on July 21 at 02:56 UTC. Aldrin joined him 19 minutes later. "
    "They spent two hours and 15 minutes together outside the spacecraft, and collected 47.5 pounds "
    "(21.5 kg) of lunar material to bring back to Earth."
)
page1.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text1, fontsize=12)

# Page 2
page2 = doc.new_page()
text2 = (
    "Command Module Operations and Recovery\n\n"
    "Command Module Pilot Michael Collins flew the Command Module Columbia alone in lunar orbit "
    "while Armstrong and Aldrin were on the Moon's surface. Armstrong and Aldrin spent 21 hours and "
    "36 minutes on the lunar surface at a site they named Tranquility Base before lifting off to rejoin "
    "Columbia in lunar orbit. The mission launched from Kennedy Space Center on July 16, 1969, at 13:32 UTC "
    "on a Saturn V rocket. The crew splashed down safely in the Pacific Ocean on July 24, 1969, after "
    "eight days, three hours, and 18 minutes in space."
)
page2.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text2, fontsize=12)
doc.save(str(pdf_path))
doc.close()
print(f"Generated PDF at {pdf_path}")
