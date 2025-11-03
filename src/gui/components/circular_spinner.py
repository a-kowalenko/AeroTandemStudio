import tkinter as tk


class CircularSpinner:
    """Moderner, mehrschichtiger Spinner mit Gradient-Effekt."""

    def __init__(self, parent, size=80, line_width=6, color="#007ACC", speed=10):
        self.parent = parent
        self.size = size
        self.line_width = line_width
        self.base_color = color
        self.speed = speed  # degrees per frame
        self.angle = 0
        self._job = None

        # Transparenter Hintergrund - holt sich die Farbe vom Parent
        parent_bg = parent.cget('bg') if hasattr(parent, 'cget') else 'white'
        self.canvas = tk.Canvas(
            parent,
            width=size,
            height=size,
            highlightthickness=0,
            bg=parent_bg  # Transparenter Look durch Übernahme der Parent-Farbe
        )

        # Erstelle mehrere Arcs für Gradient-Effekt
        self.arcs = []
        self._create_gradient_arcs()

    def _create_gradient_arcs(self):
        """Erstellt mehrere Arcs für einen modernen Gradient-Effekt"""
        # Gradient von hell nach dunkel (außen nach innen)
        gradient_layers = [
            {'extent': 280, 'width': self.line_width, 'color': self._lighten_color(self.base_color, 0.7)},
            {'extent': 240, 'width': self.line_width - 1, 'color': self._lighten_color(self.base_color, 0.5)},
            {'extent': 200, 'width': self.line_width - 2, 'color': self._lighten_color(self.base_color, 0.3)},
            {'extent': 160, 'width': self.line_width - 3, 'color': self.base_color},
        ]

        center = self.size / 2
        radius = (self.size - self.line_width) / 2

        for layer in gradient_layers:
            pad = (self.size - radius * 2) / 2
            arc = self.canvas.create_arc(
                pad, pad,
                self.size - pad, self.size - pad,
                start=0,
                extent=layer['extent'],
                style='arc',
                width=layer['width'],
                outline=layer['color'],
                tags='spinner'
            )
            self.arcs.append({'arc': arc, 'extent': layer['extent']})

    def _lighten_color(self, hex_color, factor):
        """Hellt eine Hex-Farbe auf für Gradient-Effekt"""
        # Entferne '#' wenn vorhanden
        hex_color = hex_color.lstrip('#')

        # Konvertiere zu RGB
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)

        # Helligkeit erhöhen
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)

        # Zurück zu Hex
        return f'#{r:02x}{g:02x}{b:02x}'

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def grid(self, **kwargs):
        self.canvas.grid(**kwargs)

    def place(self, **kwargs):
        self.canvas.place(**kwargs)

    def pack_forget(self):
        """Versteckt den Spinner (entfernt aus dem Layout)"""
        self.canvas.pack_forget()

    def grid_forget(self):
        """Versteckt den Spinner (entfernt aus dem Grid)"""
        self.canvas.grid_forget()

    def place_forget(self):
        """Versteckt den Spinner (entfernt aus dem Place)"""
        self.canvas.place_forget()

    def start(self, delay=30):
        """Startet die Animation mit smooth delay (30ms = ~33fps)"""
        if self._job:
            return
        self._animate(delay)

    def _animate(self, delay):
        """Smooth Animation im Uhrzeigersinn mit variablen Geschwindigkeiten"""
        # Uhrzeigersinn: Winkel wird SUBTRAHIERT statt addiert
        self.angle = (self.angle - self.speed) % 360

        try:
            # Rotiere jeden Arc mit leicht unterschiedlichen Geschwindigkeiten
            # für einen "fließenden" Effekt
            for i, arc_data in enumerate(self.arcs):
                # Jeder Arc rotiert etwas schneller als der vorherige
                offset = self.angle - (i * 5)  # 5° Offset zwischen den Layers (negativ für Uhrzeigersinn)
                self.canvas.itemconfigure(arc_data['arc'], start=offset % 360)
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