"""Standalone process entry point for the microphone voice changer."""
import tkinter as tk
from voice_reader.live_voice_ui import LiveVoiceApp


def run() -> int:
    root = tk.Tk()
    LiveVoiceApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
