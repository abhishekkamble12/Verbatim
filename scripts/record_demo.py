"""Record the demo video: upload -> question -> evidence -> abstention -> report + trace -> cost.

Needs the full local stack running (DB, LocalStack, API, worker, Vite) and a dev-only tool:
    pip install playwright && python -m playwright install chromium
Usage: python scripts/record_demo.py  [WEB_URL env, default http://127.0.0.1:5173]
Writes results/demo/demo.webm.
"""

import os
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

WEB_URL = os.environ.get("WEB_URL", "http://127.0.0.1:5173")
PDF = Path("data/corpus/Apollo_11_Mission_Report.pdf").resolve()
OUT = Path("results/demo")
SIZE = {"width": 1440, "height": 900}
QUESTION = "How much lunar material was collected, and when did the crew land on the Moon?"
UNANSWERABLE = "What was the color of Neil Armstrong's car on Earth?"
REPORT_Q = "Summarize the Apollo 11 mission: landing, surface activities and return."


def pause(s: float) -> None:
    time.sleep(s)  # viewer reading time, not a wait for the app


def type_slowly(page, selector: str, text: str) -> None:
    page.click(selector)
    page.keyboard.type(text, delay=35)


def main() -> None:
    tmp = OUT / "raw"
    shutil.rmtree(tmp, ignore_errors=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport=SIZE, record_video_dir=str(tmp), record_video_size=SIZE)
        page = ctx.new_page()
        page.set_default_timeout(180_000)  # LLM answers and report jobs can be slow

        page.goto(WEB_URL)
        type_slowly(page, "#uid", "alice")
        page.click("button[type=submit]")
        type_slowly(page, "#nbtitle", f"Apollo 11 Demo {time.strftime('%H%M')}")
        page.click("button:has-text('Create')")

        # 1. Upload and wait for the source to be ready.
        page.set_input_files("input[type=file]", str(PDF))
        page.wait_for_selector(".src-ready")
        pause(2)

        # 2. Grounded question, then open the evidence for the first claim.
        type_slowly(page, "#q", QUESTION)
        page.keyboard.press("Enter")
        page.wait_for_selector(".bubble.assistant .claim")
        pause(3)
        page.click(".bubble.assistant .claim >> nth=0")
        pause(5)

        # 3. Abstention.
        type_slowly(page, "#q", UNANSWERABLE)
        page.keyboard.press("Enter")
        page.wait_for_selector(".bubble.abstain")
        pause(5)

        # 4. Report agent, its trace, and its cost.
        page.click("role=tab[name='Report']")
        type_slowly(page, "#rq", REPORT_Q)
        page.keyboard.press("Enter")
        page.wait_for_selector("article h2")
        pause(3)
        page.click("button:has-text('Show trace')")
        pause(3)
        page.mouse.wheel(0, 1500)
        pause(5)

        video = page.video
        ctx.close()  # flushes the video file
        browser.close()
        OUT.mkdir(parents=True, exist_ok=True)
        dest = OUT / "demo.webm"
        shutil.move(video.path(), dest)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"Saved {dest}")


if __name__ == "__main__":
    main()
