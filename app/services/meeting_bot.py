import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from app.core.config import settings

class TeamsBot:
    def __init__(self, meeting_url: str, bot_name: str = "AI Assistant"):
        self.meeting_url = meeting_url
        self.bot_name = bot_name
        self.output_dir = settings.output_folder / "bot_recordings"
        self.output_dir.mkdir(exist_ok=True)
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def _save_screenshot(self, page, label: str, timestamp: str):
        """Save a debug screenshot."""
        try:
            path = str(self.output_dir / f"debug_{label}_{timestamp}.png")
            page.screenshot(path=path)
            print(f"[Bot] Screenshot saved: {path}")
        except Exception as e:
            print(f"[Bot] Could not save screenshot ({label}): {e}")

    def join_and_record(self, duration_minutes: int = 60):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_filename = self.output_dir / f"bot_rec_{timestamp}.wav"

        with sync_playwright() as p:
            print(f"[Bot] Launching browser...")
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--no-sandbox",
                    "--disable-notifications",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--autoplay-policy=no-user-gesture-required",
                ]
            )
            context = browser.new_context(
                permissions=["microphone", "camera"],
                viewport={'width': 1920, 'height': 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            Stealth().apply_stealth_sync(page)

            print(f"[Bot] Navigating to: {self.meeting_url}")
            page.goto(self.meeting_url, wait_until="domcontentloaded", timeout=30000)
            self._save_screenshot(page, "01_landed", timestamp)

            # --- Teams Join Logic ---
            try:
                # 1. Handle landing page: "Continue on this browser"
                # Teams often shows a dialog asking to open the app
                continue_selectors = [
                    'button:has-text("Continue on this browser")',
                    'a:has-text("Continue on this browser")',
                    '[data-tid="joinOnWeb"]',
                    'button:has-text("Join on the web instead")',
                ]
                for sel in continue_selectors:
                    try:
                        el = page.locator(sel).first
                        try:
                            el.wait_for(state="visible", timeout=3000)
                            el.click()
                            print(f"[Bot] Clicked 'Continue on this browser' via main page")
                            time.sleep(2)
                            break
                        except Exception:
                            # Try looking inside iframes
                            frame_el = page.frame_locator("*").locator(sel).first
                            frame_el.wait_for(state="visible", timeout=3000)
                            frame_el.click()
                            print(f"[Bot] Clicked 'Continue on this browser' via iframe")
                            time.sleep(2)
                            break
                    except Exception:
                        pass
            except Exception:
                pass

            self._save_screenshot(page, "02_after_continue", timestamp)

            try:
                # 2. Wait for name / pre-join screen
                print("[Bot] Waiting for join screen...")

                # Expanded list of selectors for the name input field
                name_selectors = [
                    'input[placeholder*="name" i]',
                    'input[placeholder*="Name" i]',
                    'input#username',
                    '[data-tid="prejoin-display-name-input"]',
                    'input[type="text"]',
                    '[aria-label*="name" i]',
                ]

                name_field = None
                for attempt in range(20):
                    for sel in name_selectors:
                        try:
                            # Search in main page
                            locator = page.locator(sel).first
                            try:
                                locator.wait_for(state="visible", timeout=1000)
                                name_field = locator
                                print(f"[Bot] Found name field via: {sel} on main page")
                                break
                            except Exception:
                                pass
                                
                            # Search in frames
                            frame_locator = page.frame_locator("*").locator(sel).first
                            try:
                                frame_locator.wait_for(state="visible", timeout=1000)
                                name_field = frame_locator
                                print(f"[Bot] Found name field via: {sel} in iframe")
                                break
                            except Exception:
                                pass
                        except Exception:
                            pass
                    if name_field:
                        break
                    if attempt % 4 == 0:
                        self._save_screenshot(page, f"03_waiting_{attempt}", timestamp)
                    print(f"[Bot] Waiting for name field... ({attempt + 1}/20)")
                    time.sleep(3)

                if not name_field:
                    self._save_screenshot(page, "03_name_field_timeout", timestamp)
                    raise Exception("Name field not found after 60s timeout")

                # 3. Dismiss any overlays or cookie banners
                for dismiss_sel in [
                    'button:has-text("Got it")',
                    'button:has-text("Dismiss")',
                    'button:has-text("Accept")',
                    '[aria-label="Close dialog"]',
                    '[aria-label="Close"]',
                ]:
                    try:
                        el = page.locator(dismiss_sel)
                        if el.is_visible(timeout=1000):
                            el.click()
                    except:
                        pass

                # 4. Fill name
                assert name_field is not None
                name_field.fill("")
                time.sleep(0.3)
                name_field.fill(self.bot_name)
                print(f"[Bot] Name set to: {self.bot_name}")

                # 5. Turn off mic & camera via keyboard shortcuts
                page.keyboard.press("Control+Shift+M")  # Mute Mic
                time.sleep(0.5)
                page.keyboard.press("Control+Shift+O")  # Turn off Camera
                time.sleep(0.5)

                self._save_screenshot(page, "04_pre_join", timestamp)

                # 6. Click Join - try multiple selectors
                print("[Bot] Attempting to join...")
                join_selectors = [
                    '[data-tid="prejoin-join-button"]',
                    'button:has-text("Join now")',
                    'button:has-text("Join")',
                    '[aria-label*="Join" i]',
                    'button[type="submit"]',
                ]

                joined = False
                for attempt in range(3): # Retry up to 3 times
                    if joined:
                        break
                    
                    for sel in join_selectors:
                        try:
                            # Try main page
                            btn = page.locator(sel).first
                            if btn.is_visible():
                                btn.click(force=True)
                                print(f"[Bot] Clicked join button via main page: {sel}")
                                # Wait for button to disappear or 'Connecting' state
                                try:
                                    btn.wait_for(state="hidden", timeout=5000)
                                    joined = True
                                    print("[Bot] Join button disappeared. Transitioning...")
                                    break
                                except:
                                    print("[Bot] Join button still visible after click. Retrying...")
                            
                            # Try iframe
                            frame_btn = page.frame_locator("*").locator(sel).first
                            if frame_btn.is_visible():
                                frame_btn.click(force=True)
                                print(f"[Bot] Clicked join button via iframe: {sel}")
                                try:
                                    frame_btn.wait_for(state="hidden", timeout=5000)
                                    joined = True
                                    print("[Bot] Join button (iframe) disappeared. Transitioning...")
                                    break
                                except:
                                    print("[Bot] Join button (iframe) still visible. Retrying...")

                        except Exception:
                            pass
                    
                    if not joined:
                        print(f"[Bot] Join attempt {attempt+1} failed. waiting...")
                        time.sleep(2)

                if not joined:
                    self._save_screenshot(page, "04_no_join_button", timestamp)
                    # Dump HTML
                    try:
                        with open(self.output_dir / f"debug_prejoin_{timestamp}.html", "w", encoding="utf-8") as f:
                            f.write(page.content())
                    except: pass
                    raise Exception("Join button not found or failed to click")

                # 6b. Handle "Are you sure you don't want audio or video?" dialog
                # Teams shows this modal when no mic/camera permissions are granted.
                # We MUST click "Continue without audio or video" or the bot never enters the lobby.
                print("[Bot] Checking for audio/video confirmation dialog...")
                audio_confirm_selectors = [
                    'button:has-text("Continue without audio or video")',
                    'button:has-text("Continue without audio")',
                    '[data-tid="prejoin-audio-video-confirm-continue-btn"]',
                ]
                for attempt in range(6):  # check for up to 6s
                    dialog_handled = False
                    for sel in audio_confirm_selectors:
                        try:
                            btn = page.locator(sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click(force=True)
                                print(f"[Bot] Dismissed audio/video dialog via: {sel}")
                                dialog_handled = True
                                time.sleep(1)
                                self._save_screenshot(page, "04b_after_audio_dialog", timestamp)
                                break
                        except Exception:
                            pass
                    if dialog_handled:
                        break
                    time.sleep(1)

                # 7. LOBBY DETECTION: Wait for admission (up to 3 minutes)
                print("[Bot] Waiting for admission...")
                admission_timeout = 180
                lobby_start = time.time()
                last_lobby_log = 0

                while time.time() - lobby_start < admission_timeout:
                    if self._should_stop:
                        print("[Bot] Stop requested during lobby wait.")
                        browser.close()
                        return None

                    # Trigger toolbar visibility
                    try:
                        page.mouse.move(100, 100)
                        time.sleep(0.5)
                        page.mouse.move(200, 200)
                    except: pass

                    # Check for end of meeting or removal via text (faster than visibility checks)
                    try:
                        full_text = page.locator("body").inner_text()
                        if not full_text.strip():
                            full_text = page.frame_locator("*").locator("body").first.inner_text()
                        
                        end_texts = [
                            "The meeting has ended",
                            "Someone removed you from the meeting",
                            "been removed",
                            "Left the meeting",
                            "You're not in the meeting",
                            "Waiting for others to join"
                        ]
                        ended = False
                        for text in end_texts:
                            if text in full_text:
                                ended = True
                                break
                        if ended:
                            print(f"[Bot] Meeting ended or removal detected during lobby wait.")
                            browser.close()
                            return None
                    except Exception:
                        pass

                    # Check for admission (is_in)
                    is_in = False

                    # Lobby-specific phrases — if any are present, we're definitely still in lobby
                    lobby_phrases = [
                        "Your camera is turned off",
                        "Background filters",
                        "Computer microphone and speaker controls",
                        "Computer audio",
                        "waiting to be let in",
                        "Someone will let you in soon",
                        "waiting to join",
                        "Other people are in the meeting",
                        "Please wait",
                        "Joining the meeting",
                    ]
                    still_in_lobby = any(phrase in full_text for phrase in lobby_phrases)

                    # 1. Text-based detection — only if no lobby phrases detected
                    if not still_in_lobby:
                        try:
                            # More specific: meeting toolbar has "Leave" and timer/participant count
                            if "Leave" in full_text and ("Mic" in full_text or "Camera" in full_text):
                                is_in = True
                        except:
                            pass

                    # 2. Selector-based detection — only use selectors exclusive to in-meeting UI
                    # Deliberately EXCLUDING [aria-label*="camera" i], [aria-label*="Mute" i] etc.
                    # because the lobby device-settings panel also has those controls.
                    if not is_in and not still_in_lobby:
                        inside_selectors = [
                            '[data-tid="hangup-button"]',           # Red hang-up — meeting only
                            '[data-tid="participants-button"]',     # Participant list — meeting only
                            '[data-tid="chat-button"]',             # Chat panel — meeting only
                            '[data-tid="callingButtons-showParticipants"]',
                            '[aria-label="Leave meeting"]',         # Exact label — meeting only
                            '[aria-label="Hang up"]',               # Exact label — meeting only
                        ]
                        for sel in inside_selectors:
                            try:
                                if page.locator(sel).first.is_visible():
                                    is_in = True
                                    print(f"[Bot] Admitted! Detected via selector: {sel}")
                                    break
                                if page.frame_locator("*").locator(sel).first.is_visible():
                                    is_in = True
                                    print(f"[Bot] Admitted! Detected via iframe selector: {sel}")
                                    break
                            except Exception:
                                pass

                    if still_in_lobby and not is_in:
                        pass  # Correctly identified as still in lobby

                    if is_in:
                        print("[Bot] Admitted to meeting!")
                        break

                    # Log lobby status every 30s
                    elapsed = time.time() - lobby_start
                    if elapsed - last_lobby_log >= 30:
                        print(f"[Bot] Still in lobby... ({int(elapsed)}s elapsed)")
                        print(f"[Bot] Screen text sample: {repr(full_text.strip().replace(chr(10), ' '))[:150]}")
                        self._save_screenshot(page, f"05_lobby_{int(elapsed)}s", timestamp)
                        last_lobby_log = elapsed

                    time.sleep(5)
                else:
                    self._save_screenshot(page, "05_lobby_timeout", timestamp)
                    # Dump HTML for debugging
                    try:
                        html_path = self.output_dir / f"debug_dump_timeout_{timestamp}.html"
                        with open(html_path, "w", encoding="utf-8") as f:
                            f.write(page.content())
                        print(f"[Bot] HTML dump saved to: {html_path}")
                    except Exception as e:
                        print(f"[Bot] Failed to save HTML dump: {e}")
                    
                    print("[Bot] Lobby timeout (3 min). No one admitted the bot.")
                    browser.close()
                    return None

                print("[Bot] Joined! Starting recording...")
                self._save_screenshot(page, "06_joined", timestamp)


            except Exception as e:
                self._save_screenshot(page, "err_join", timestamp)
                print(f"[Bot] Join failed: {e}")
                browser.close()
                return None

            # 8. Start FFmpeg Recording
            if sys.platform == "win32":
                # Fallback to generic Stereo Mix or user provided device
                device = os.environ.get("WINDOWS_AUDIO_DEVICE", "audio=Stereo Mix (Realtek(R) Audio)")
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-f", "dshow",
                    "-i", device,
                    "-ac", "2",
                    "-ar", "16000",
                    "-t", str(duration_minutes * 60),
                    str(audio_filename)
                ]
            else:
                device = "virtsink.monitor"
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-f", "pulse",
                    "-i", device,
                    "-ac", "2",
                    "-ar", "16000",
                    "-t", str(duration_minutes * 60),
                    str(audio_filename)
                ]

            if sys.platform == "win32":
                print(f"[Bot] Recording from Windows dshow device: {device}")
            else:
                print(f"[Bot] Recording from isolated PulseAudio sink: {device}")
                
            log_filename = os.path.join(self.output_dir, f"ffmpeg_log_{timestamp}.txt")
            self._log_file = open(log_filename, "w")
            
            record_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdout=self._log_file,
                stderr=self._log_file
            )

            # 9. Active Meeting Monitoring
            try:
                start_time = time.time()
                missing_count = 0
                last_log_time = 0
                while time.time() - start_time < (duration_minutes * 60):
                    if self._should_stop:
                        break

                    # Move the mouse to keep the Teams UI toolbar visible (prevent auto-hide)
                    try:
                        page.mouse.move(100, 100)
                        time.sleep(0.5)
                        page.mouse.move(200, 200)
                        time.sleep(0.5)
                    except Exception:
                        pass

                    is_active = False

                    # 1. Fallback text-based validation
                    try:
                        full_text = page.locator("body").inner_text()
                        if not full_text.strip():
                            full_text = page.frame_locator("*").locator("body").first.inner_text()
                            
                        # If standard active meeting toolbar text is visible (jiggled by mouse)
                        if "Leave" in full_text and ("Mic" in full_text or "Camera" in full_text):
                            is_active = True
                    except Exception:
                        pass
                        
                    # 2. Selector-based UI validation
                    if not is_active:
                        active_selectors = [
                            '[aria-label*="Leave" i]', 
                            '[aria-label*="Hang up" i]', 
                            '[data-tid="hangup-button"]',
                            '[aria-label*="Mute" i]',
                            '[aria-label*="Unmute" i]',
                            '[aria-label*="camera" i]',
                            '[data-tid="participants-button"]'
                        ]
                        for sel in active_selectors:
                            try:
                                if page.locator(sel).first.is_visible():
                                    is_active = True
                                    break
                                if page.frame_locator("*").locator(sel).first.is_visible():
                                    is_active = True
                                    break
                            except Exception:
                                pass

                    if not is_active:
                        missing_count += 1
                        if missing_count >= 3:  # ~45 seconds
                            print("[Bot] Active meeting controls missing for 45s. Finalizing.")
                            break
                    else:
                        missing_count = 0

                    try:
                        end_texts = [
                            "The meeting has ended",
                            "Someone removed you from the meeting",
                            "been removed",
                            "Left the meeting",
                            "You're not in the meeting",
                            "Waiting for others to join"
                        ]
                        ended = False
                        
                        # Use exact text content from the DOM body instead of Playwright element visibility
                        try:
                            check_text = page.locator("body").inner_text()
                            if not check_text.strip():
                                check_text = page.frame_locator("*").locator("body").first.inner_text()
                            for text in end_texts:
                                if text in check_text:
                                    ended = True
                                    break
                        except Exception:
                            pass
                            
                        # Fallback to get_by_text just in case
                        if not ended:
                            for text in end_texts:
                                if page.get_by_text(text, exact=False).first.is_visible():
                                    ended = True
                                    break
                                if page.frame_locator("*").get_by_text(text, exact=False).first.is_visible():
                                    ended = True
                                    break
                            
                        if ended:
                            print("[Bot] Meeting ended or bot removed.")
                            break
                    except Exception:
                        pass

                    try:
                        elapsed = time.time() - start_time
                        if elapsed - last_log_time >= 30:
                            print(f"[Bot] Still recording... ({int(elapsed)}s elapsed). Active UI detected: {is_active}")
                            txt_sample = ""
                            try:
                                txt_sample = page.locator("body").inner_text()
                                if not txt_sample.strip():
                                    txt_sample = page.frame_locator("*").locator("body").first.inner_text()
                            except:
                                pass
                            print(f"[Bot] Rec Screen Text: {repr(txt_sample.strip().replace(chr(10), ' '))[:200]}")
                            self._save_screenshot(page, f"07_recording_{int(elapsed)}s", timestamp)
                            last_log_time = elapsed
                    except Exception:
                        pass

                    time.sleep(15)
            finally:
                record_proc.terminate()
                browser.close()
                if hasattr(self, "_log_file") and not self._log_file.closed:
                    self._log_file.close()
                print(f"[Bot] Recording saved to: {audio_filename}")

        return str(audio_filename)
