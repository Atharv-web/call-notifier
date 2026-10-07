"""Receive local call signals and show Windows notifications."""

import argparse
import hmac
import json
from pathlib import Path
import secrets
import socket
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", action="store_true", help="Print alerts without the notification library.")
    args = parser.parse_args()
    toaster = None
    if not args.console:
        try:
            from windows_toasts import Toast, WindowsToaster
        except ImportError:
            parser.exit(1, "Install windows/requirements.txt in your virtual environment first.\n")
        toaster = WindowsToaster("call-notifier")

    token_path = Path(__file__).resolve().parents[1] / "runtime" / "token.txt"
    token_path.parent.mkdir(exist_ok=True)
    if not token_path.exists():
        token_path.write_text(secrets.token_hex(16), encoding="utf-8")
    token = token_path.read_text(encoding="utf-8").strip()
    print("call-notifier: listening on UDP port 45832")
    print("Find the laptop hotspot IPv4 address with ipconfig.")
    print(f"Enter this pairing token on your phone: {token}")
    print("Keep this window open. Press Ctrl+C to stop.")
    seen = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("0.0.0.0", 45832))
        receiver.settimeout(1.0)
        try:
            while True:
                try:
                    raw, _ = receiver.recvfrom(2048)
                except socket.timeout:
                    continue
                now = time.time()
                seen = {key: stamp for key, stamp in seen.items() if now - stamp < 60}
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        continue
                    supplied = event.get("token")
                    event_id = event.get("id")
                    stamp = event.get("time")
                    kind = event.get("type")
                    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, token):
                        continue
                    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 64:
                        continue
                    if not isinstance(stamp, (int, float)) or not abs(now - stamp) <= 30:
                        continue
                    if kind not in ("ringing", "test") or event_id in seen:
                        continue
                    seen[event_id] = now
                    message = "Your phone is ringing" if kind == "ringing" else "Test alert from your phone"
                    print(message, flush=True)
                    if toaster is not None:
                        toast = Toast()
                        toast.text_fields = ["call-notifier", message]
                        try:
                            toaster.show_toast(toast)
                        except Exception as error:
                            print(f"Notification failed: {error}", flush=True)
                except (ValueError, UnicodeError, TypeError):
                    continue
        except KeyboardInterrupt:
            print("\nReceiver stopped.")


if __name__ == "__main__":
    main()
