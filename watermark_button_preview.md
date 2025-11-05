Spezifikation: Feature - Wasserzeichen-Button in Preview

1. Zielsetzung

In video_preview.py und photo_preview.py soll ein neuer Button (💧) hinzugefügt werden. Dieser Button dient als "Shortcut", um das aktuell in der Vorschau angezeigte Video oder Foto für das Wasserzeichen zu markieren oder die Markierung aufzuheben.

Die gesamte Logik und der Status (State) der Wasserzeichen-Markierung verbleiben in drag_drop.py. Die neuen Buttons in den Preview-Komponenten rufen lediglich Funktionen in app.py auf, welche die Aktion an drag_drop.py weiterleiten (Proxy).

2. Änderungen an drag_drop.py (State Owner)

Damit app.py den Status umschalten und lesen kann, benötigt DragDropFrame vier neue "öffentliche" Methoden.

Füge der Klasse DragDropFrame die folgenden Methoden hinzu:

    # --- NEUE ÖFFENTLICHE METHODEN FÜR WASSERZEICHEN-STEUERUNG ---

    def toggle_video_watermark_at_index(self, index):
        """
        Schaltet die Wasserzeichen-Markierung für einen bestimmten Video-Index um.
        Wird von app.py aufgerufen.
        """
        if self.watermark_clip_index == index:
            # Bereits ausgewählt -> abwählen
            self.watermark_clip_index = None
        else:
            # Anderes oder keins ausgewählt -> dieses auswählen
            self.watermark_clip_index = index
        
        self._update_video_table()

    def is_video_watermarked(self, index):
        """Prüft, ob ein bestimmter Video-Index als Wasserzeichen markiert ist."""
        return self.watermark_clip_index == index

    def toggle_photo_watermark_at_index(self, index):
        """
        Schaltet die Wasserzeichen-Markierung für einen bestimmten Foto-Index um.
        Wird von app.py aufgerufen.
        """
        if index in self.watermark_photo_indices:
            # Bereits in der Liste -> entfernen
            self.watermark_photo_indices.remove(index)
        else:
            # Nicht in der Liste -> hinzufügen
            self.watermark_photo_indices.append(index)
        
        self._update_photo_table()

    def is_photo_watermarked(self, index):
        """Prüft, ob ein bestimmter Foto-Index als Wasserzeichen markiert ist."""
        return index in self.watermark_photo_indices


3. Änderungen an video_preview.py (UI-Button)

3.1. create_widgets

Im button_frame (innerhalb von right_info_frame), füge den neuen Wasserzeichen-Button neben dem qr_scan_button hinzu.

        # ... (in right_info_frame)
        button_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=0)
        button_frame.columnconfigure(3, weight=0) # NEUE Spalte

        self.delete_button = tk.Button(...)
        self.delete_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.clear_selection_button = tk.Button(...)
        self.clear_selection_button.grid(row=0, column=1, sticky="ew", padx=(5, 5))

        self.qr_scan_button = tk.Button(...)
        self.qr_scan_button.grid(row=0, column=2, sticky="ew", padx=(5, 0))
        
        # --- NEU: Wasserzeichen-Button ---
        self.wm_button = tk.Button(
            button_frame,
            text="💧",
            command=self._on_wm_button_click,
            bg="#f0f0f0",
            fg="black",
            font=("Arial", 9),
            width=3,
            state="disabled"
        )
        self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        # --- ENDE NEU ---


3.2. _update_button_states

Erweitere diese Methode, um den wm_button zu (de)aktivieren, wenn Clips vorhanden sind.

    def _update_button_states(self):
        """Aktualisiert den Status aller Buttons"""
        has_clips = bool(self.video_paths)

        if has_clips:
            self.delete_button.config(state="normal")
            self.qr_scan_button.config(state="normal")
            self.wm_button.config(state="normal") # NEU
        else:
            self.delete_button.config(state="disabled")
            self.qr_scan_button.config(state="disabled")
            self.wm_button.config(state="disabled") # NEU

        # Clear-Selection immer disabled (keine Mehrfachauswahl aktuell)
        self.clear_selection_button.config(state="disabled")


3.3. Status-Updates (WICHTIG)

Der Button muss seinen Status (Text, Farbe) ändern, wenn sich der aktive Clip ändert.

Modifiziere _update_info: Füge am Ende einen Aufruf hinzu:

# ... am Ende von _update_info
self.update_wm_button_state()


Modifiziere set_active_clip_by_time: Füge am Ende (innerhalb der if-Bedingung) einen Aufruf hinzu:

# ... am Ende von set_active_clip_by_time, nach _update_info()
self.update_wm_button_state()


3.4. Neue Methoden

Füge die folgenden neuen Methoden zur VideoPreview-Klasse hinzu:

    def _on_wm_button_click(self):
        """
        Wird aufgerufen, wenn der Wasserzeichen-Button geklickt wird.
        Leitet die Aktion an app.py weiter.
        """
        if self.app and hasattr(self.app, 'toggle_video_watermark') and self.current_active_clip is not None:
            if 0 <= self.current_active_clip < len(self.video_paths):
                self.app.toggle_video_watermark(self.current_active_clip)

    def set_wm_button_visibility(self, visible: bool):
        """Zeigt oder verbirgt den Wasserzeichen-Button (gesteuert von app.py)."""
        if visible:
            self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        else:
            self.wm_button.grid_remove()

    def update_wm_button_state(self):
        """
        Aktualisiert Text und Farbe des WM-Buttons basierend auf dem Status
        in drag_drop.py.
        """
        if not self.app or not hasattr(self.app, 'drag_drop') or self.current_active_clip < 0:
            self.wm_button.config(text="💧", state="disabled", bg="#f0f0f0")
            return
        
        # Lese den Status direkt von drag_drop (via app)
        is_marked = self.app.drag_drop.is_video_watermarked(self.current_active_clip)
        
        if is_marked:
            self.wm_button.config(text="Entf. 💧", state="normal", bg="#D32F2F", fg="white")
        else:
            self.wm_button.config(text="Mark. 💧", state="normal", bg="#FF9800", fg="black")


4. Änderungen an photo_preview.py (UI-Button)

Die Änderungen sind fast identisch zu video_preview.py.

4.1. create_widgets

Im button_frame (innerhalb von right_info_frame), füge den neuen Wasserzeichen-Button hinzu.

        # ... (in right_info_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=0)
        button_frame.columnconfigure(3, weight=0) # NEUE Spalte

        self.delete_button = tk.Button(...)
        self.delete_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.clear_selection_button = tk.Button(...)
        self.clear_selection_button.grid(row=0, column=1, sticky="ew", padx=(5, 5))

        self.qr_scan_button = tk.Button(...)
        self.qr_scan_button.grid(row=0, column=2, sticky="ew", padx=(5, 0))

        # --- NEU: Wasserzeichen-Button ---
        self.wm_button = tk.Button(
            button_frame,
            text="💧",
            command=self._on_wm_button_click,
            bg="#f0f0f0",
            fg="black",
            font=("Arial", 9),
            width=3,
            state="disabled"
        )
        self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        # --- ENDE NEU ---


4.2. _update_delete_button

Erweitere diese Methode, um den wm_button zu (de)aktivieren.

    def _update_delete_button(self):
        """Aktualisiert den Status und Text der Buttons..."""
        # ... (bestehende Logik für delete_button und clear_selection_button)

        # QR-Scan-Button und WM-Button
        if self.photo_paths and 0 <= self.current_photo_index < len(self.photo_paths):
            self.qr_scan_button.config(state="normal")
            self.wm_button.config(state="normal") # NEU
            self.update_wm_button_state() # NEU: Status aktualisieren
        else:
            self.qr_scan_button.config(state="disabled")
            self.wm_button.config(state="disabled") # NEU


4.3. Status-Updates (WICHTIG)

Der Button muss seinen Status ändern, wenn sich das aktive Foto ändert.

Modifiziere _update_info: Füge am Ende einen Aufruf hinzu:

# ... am Ende von _update_info
self.update_wm_button_state()


Modifiziere _on_thumbnail_click: Füge am Ende einen Aufruf hinzu:

# ... am Ende von _on_thumbnail_click, nach _update_delete_button()
self.update_wm_button_state()


Modifiziere _show_previous_photo: Füge am Ende einen Aufruf hinzu:

# ... am Ende von _show_previous_photo, nach _update_info()
self.update_wm_button_state()


Modifiziere _show_next_photo: Füge am Ende einen Aufruf hinzu:

# ... am Ende von _show_next_photo, nach _update_info()
self.update_wm_button_state()


4.4. Neue Methoden

Füge die folgenden neuen Methoden zur PhotoPreview-Klasse hinzu:

    def _on_wm_button_click(self):
        """
        Wird aufgerufen, wenn der Wasserzeichen-Button geklickt wird.
        Leitet die Aktion an app.py weiter.
        """
        if self.app and hasattr(self.app, 'toggle_photo_watermark') and self.current_photo_index is not None:
            if 0 <= self.current_photo_index < len(self.photo_paths):
                self.app.toggle_photo_watermark(self.current_photo_index)

    def set_wm_button_visibility(self, visible: bool):
        """Zeigt oder verbirgt den Wasserzeichen-Button (gesteuert von app.py)."""
        if visible:
            self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        else:
            self.wm_button.grid_remove()

    def update_wm_button_state(self):
        """
        Aktualisiert Text und Farbe des WM-Buttons basierend auf dem Status
        in drag_drop.py.
        """
        if (not self.app or not hasattr(self.app, 'drag_drop') or 
            self.current_photo_index < 0 or not self.photo_paths):
            self.wm_button.config(text="💧", state="disabled", bg="#f0f0f0")
            return

        # Lese den Status direkt von drag_drop (via app)
        is_marked = self.app.drag_drop.is_photo_watermarked(self.current_photo_index)
        
        if is_marked:
            self.wm_button.config(text="Entf. 💧", state="normal", bg="#D32F2F", fg="white")
        else:
            self.wm_button.config(text="Mark. 💧", state="normal", bg="#FF9800", fg="black")


5. Änderungen an app.py (Orchestrator)

5.1. update_watermark_column_visibility

Erweitere diese Methode, um die Sichtbarkeit und den Status der neuen Buttons in den Previews zu steuern.

    def update_watermark_column_visibility(self):
        """Aktualisiert die Sichtbarkeit der Wasserzeichen-Spalte UND der Preview-Buttons"""
        form_data = self.form_fields.get_form_data()

        # --- Video-Logik ---
        video_gewaehlt = form_data.get("handcam_video", False) or form_data.get("outside_video", False)
        video_bezahlt = form_data.get("ist_bezahlt_handcam_video", False) or form_data.get("ist_bezahlt_outside_video", False)
        video_wm_sichtbar = video_gewaehlt and not video_bezahlt
        
        # ... (Debug-Ausgaben für Video) ...
        
        # Spalte in DragDrop steuern
        self.drag_drop.set_watermark_column_visible(video_wm_sichtbar)
        if not video_wm_sichtbar:
            self.drag_drop.clear_watermark_selection()
        
        # NEU: Button in VideoPreview steuern
        if hasattr(self, 'video_preview'):
            self.video_preview.set_wm_button_visibility(video_wm_sichtbar)
            self.video_preview.update_wm_button_state() # Status aktualisieren
        
        # --- Foto-Logik ---
        foto_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)
        foto_bezahlt = form_data.get("ist_bezahlt_handcam_foto", False) or form_data.get("ist_bezahlt_outside_foto", False)
        foto_wm_sichtbar = foto_gewaehlt and not foto_bezahlt

        # ... (Debug-Ausgaben für Foto) ...

        # Spalte in DragDrop steuern
        self.drag_drop.set_photo_watermark_column_visible(foto_wm_sichtbar)
        if not foto_wm_sichtbar:
            self.drag_drop.clear_photo_watermark_selection()
            
        # NEU: Button in PhotoPreview steuern
        if hasattr(self, 'photo_preview'):
            self.photo_preview.set_wm_button_visibility(foto_wm_sichtbar)
            self.photo_preview.update_wm_button_state() # Status aktualisieren


5.2. Neue Proxy-Methoden

Füge der Klasse VideoGeneratorApp die folgenden zwei Methoden hinzu, die als Proxy dienen:

    # --- NEUE WASSERZEICHEN-PROXY-METHODEN ---

    def toggle_video_watermark(self, index):
        """Wird von VideoPreview aufgerufen, leitet an DragDrop weiter."""
        if not hasattr(self, 'drag_drop'):
            return
        
        # 1. Status in drag_drop ändern
        self.drag_drop.toggle_video_watermark_at_index(index)
        
        # 2. Button-Status in video_preview aktualisieren
        if hasattr(self, 'video_preview'):
            self.video_preview.update_wm_button_state()

    def toggle_photo_watermark(self, index):
        """Wird von PhotoPreview aufgerufen, leitet an DragDrop weiter."""
        if not hasattr(self, 'drag_drop'):
            return
        
        # 1. Status in drag_drop ändern
        self.drag_drop.toggle_photo_watermark_at_index(index)
        
        # 2. Button-Status in photo_preview aktualisieren
        if hasattr(self, 'photo_preview'):
            self.photo_preview.update_wm_button_state()
