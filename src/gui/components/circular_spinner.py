import tkinter as tk


class CircularSpinner:
    """Simple rotating arc spinner on a Canvas."""

    def __init__(self, parent, size=80, line_width=8, color="#333", speed=8):
        self.parent = parent
        self.size = size
        self.line_width = line_width
        self.color = color
        self.speed = speed  # degrees per frame
        self.angle = 0
        self._job = None

        self.canvas = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg='white')
        pad = line_width // 2
        self.arc = self.canvas.create_arc(
            pad, pad, size - pad, size - pad,
            start=self.angle, extent=300, style='arc', width=line_width, outline=self.color
        )

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def grid(self, **kwargs):
        self.canvas.grid(**kwargs)

    def place(self, **kwargs):
        self.canvas.place(**kwargs)

    def start(self, delay=50):
        if self._job:
            return
        self._animate(delay)

    def _animate(self, delay):
        self.angle = (self.angle + self.speed) % 360
        try:
            self.canvas.itemconfigure(self.arc, start=self.angle)
        except Exception:
            return
        self._job = self.parent.after(delay, lambda: self._animate(delay))

    def stop(self):
        if self._job:
            try:
                self.parent.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def destroy(self):
        """Zerstört den Spinner und gibt Ressourcen frei"""
        self.stop()
        if hasattr(self, 'canvas'):
            try:
                self.canvas.destroy()
            except Exception:
                pass