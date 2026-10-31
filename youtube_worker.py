#!/usr/bin/env python3
"""
Muse VPS Fleet Manager - YouTube Automation Worker
Dijalankan sebagai background subprocess oleh agent.py.
Menggunakan Playwright Chromium dengan Persistent Profile di ~/workspace/browser_profile/
agar login Google & cookies tersimpan permanen.
"""

import asyncio
import json
import os
import random
import sys
import time
import urllib.parse

# Setup output agar terkirim langsung tanpa buffer ke agent.py
sys.stdout.reconfigure(line_buffering=True)

def emit_progress(detail: str):
    """Kirim update JSON satu baris ke stdout (dibaca oleh agent.py)"""
    print(json.dumps({"type": "PROGRESS", "detail": detail}), flush=True)

async def run_campaign(campaign: dict):
    search_query = campaign.get("search_query", "").strip()
    target_channel = campaign.get("target_channel", "").strip().lower()
    min_duration = int(campaign.get("watch_duration_min", 300))
    max_duration = int(campaign.get("watch_duration_max", 600))
    auto_like = campaign.get("auto_like", True)
    auto_comment = campaign.get("auto_comment", True)
    comments_pool = campaign.get("comments", [])

    if not search_query:
        emit_progress("Error: Kata kunci pencarian kosong!")
        sys.exit(1)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        emit_progress("Error: Playwright belum terpasang. Jalankan pip3 install playwright")
        sys.exit(1)

    profile_dir = os.path.expanduser("~/workspace/browser_profile")
    os.makedirs(profile_dir, exist_ok=True)

    target_watch_time = random.randint(min_duration, max_duration)
    emit_progress(f"Membuka browser. Target tonton: {target_watch_time} detik (~{target_watch_time//60} menit)")

    async with async_playwright() as p:
        browser_context = await p.chromium.launch_persistent_context(
            profile_dir,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--mute-audio",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1280,720"
            ],
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )

        page = await browser_context.new_page()

        try:
            # 1. Buka halaman pencarian YouTube
            encoded_query = urllib.parse.quote_plus(search_query)
            search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
            emit_progress(f"Membuka URL pencarian YouTube: {search_query}")
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3)

            # Cek jika ada popup Cookie Consent YouTube
            try:
                consent_btn = page.locator("button:has-text('Reject all'), button:has-text('Accept all'), button:has-text('I agree')")
                if await consent_btn.first.is_visible(timeout=3000):
                    await consent_btn.first.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            # 2. Cari Video Target
            video_clicked = False

            if target_channel:
                emit_progress(f"Mencari video dari channel: {target_channel}...")
                for scroll_attempt in range(4):
                    # Cari item video yang mengandung nama channel
                    video_elements = await page.locator("ytd-video-renderer").all()
                    for v in video_elements:
                        text_content = (await v.inner_text()).lower()
                        if target_channel in text_content:
                            title_el = v.locator("#video-title")
                            if await title_el.is_visible():
                                title = await title_el.inner_text()
                                emit_progress(f"Ditemukan video target: '{title}'")
                                await title_el.click()
                                video_clicked = True
                                break
                    if video_clicked:
                        break
                    # Scroll ke bawah untuk memuat lebih banyak hasil
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(2)

            # Jika tidak ada target spesifik atau belum ketemu, klik video pertama
            if not video_clicked:
                emit_progress("Memilih video pertama di hasil pencarian...")
                first_video = page.locator("ytd-video-renderer #video-title").first
                await first_video.wait_for(state="visible", timeout=15000)
                title = await first_video.inner_text()
                emit_progress(f"Membuka video: '{title}'")
                await first_video.click()

            # 3. Tunggu Video Player Siap
            await page.wait_for_selector("video", state="attached", timeout=30000)
            emit_progress("Pemutaran video dimulai!")

            # Pastikan video play (klik tombol play jika paused)
            try:
                await page.evaluate("""
                    const v = document.querySelector('video');
                    if (v && v.paused) { v.play(); }
                """)
            except Exception:
                pass

            # 4. Loop Nonton Video (Watch Delay)
            elapsed = 0
            while elapsed < target_watch_time:
                sleep_interval = min(30, target_watch_time - elapsed)
                await asyncio.sleep(sleep_interval)
                elapsed += sleep_interval

                # Human-like interaction: scroll sedikit secara acak
                if random.random() < 0.3:
                    await page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
                    await asyncio.sleep(1)
                    await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 150)})")

                emit_progress(f"Sedang menonton... ({elapsed // 60}:{elapsed % 60:02d} / {target_watch_time // 60}:{target_watch_time % 60:02d})")

            # 5. Auto-Like (Jika diaktifkan)
            if auto_like:
                emit_progress("Mencari tombol Like...")
                try:
                    # Selector tombol Like YouTube
                    like_button = page.locator("like-button-view-model button, button[aria-label*='like this video' i], button[aria-label*='sukai video ini' i]").first
                    if await like_button.is_visible(timeout=5000):
                        # Cek apakah sudah di-like sebelumnya
                        aria_pressed = await like_button.get_attribute("aria-pressed")
                        if aria_pressed != "true":
                            await like_button.click()
                            emit_progress("👍 Berhasil klik Like!")
                        else:
                            emit_progress("Tombol Like sudah ditekan sebelumnya.")
                    else:
                        emit_progress("Tombol Like tidak ditemukan (kemungkinan perlu login Google).")
                except Exception as e:
                    emit_progress(f"Gagal klik like: {e}")

            # 6. Auto-Comment (Jika diaktifkan & ada pool komentar)
            if auto_comment and comments_pool:
                chosen_comment = random.choice(comments_pool).strip()
                emit_progress(f"Mencoba mengirim komentar: '{chosen_comment}'")
                try:
                    # Scroll ke area komentar YouTube
                    await page.evaluate("window.scrollTo(0, 600)")
                    await asyncio.sleep(2)

                    # Selector placeholder komentar YouTube
                    comment_box = page.locator("#simplebox-placeholder, #placeholder-area").first
                    if await comment_box.is_visible(timeout=8000):
                        await comment_box.click()
                        await asyncio.sleep(1)

                        # Input textarea komentar
                        input_area = page.locator("#contenteditable-root").first
                        await input_area.wait_for(state="visible", timeout=5000)
                        
                        # Ketik dengan delay natural
                        for char in chosen_comment:
                            await input_area.type(char, delay=random.randint(40, 120))
                        await asyncio.sleep(1)

                        # Klik tombol Kirim / Comment
                        submit_btn = page.locator("#submit-button button").first
                        if await submit_btn.is_enabled(timeout=5000):
                            await submit_btn.click()
                            emit_progress(f"💬 Komentar terkirim: '{chosen_comment}'")
                            await asyncio.sleep(3)
                        else:
                            emit_progress("Tombol submit komentar dinonaktifkan.")
                    else:
                        emit_progress("Kolom komentar tidak muncul (kemungkinan perlu login Google terlebih dahulu).")
                except Exception as e:
                    emit_progress(f"Catatan komentar: {e}")

            emit_progress("Semua tugas selesai. Menutup browser...")

        finally:
            await browser_context.close()

    emit_progress("Worker selesai.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"type": "PROGRESS", "detail": "Argumen JSON campaign dibutuhkan!"}))
        sys.exit(1)

    try:
        campaign_data = json.loads(sys.argv[1])
    except Exception as e:
        print(json.dumps({"type": "PROGRESS", "detail": f"JSON parse error: {e}"}))
        sys.exit(1)

    asyncio.run(run_campaign(campaign_data))
