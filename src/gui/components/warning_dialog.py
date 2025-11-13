"""
Warning Dialog - Similar to Success and Error Dialogs
"""
import tkinter as tk


class WarningDialog:
    """Warning dialog for confirmation prompts"""

    def __init__(self, parent, title, message, confirm_text="Bestätigen", cancel_text="Abbrechen"):
        """
        Args:
            parent: Parent window
            title: Warning title
            message: Warning message
            confirm_text: Text for confirm button
            cancel_text: Text for cancel button
        """
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Warnung")
        self.dialog.transient(parent)

        # IMPORTANT: Hide dialog initially to avoid flickering
        self.dialog.withdraw()

        # Dialog size
        width = 450
        self.dialog.geometry(f"{width}x300")

        # Style
        self.dialog.configure(bg='#f0f0f0')

        # Result tracking
        self.result = False  # False = cancelled, True = confirmed

        self._create_widgets(title, message, confirm_text, cancel_text)

        # After widget creation: Update and calculate actual height
        self.dialog.update_idletasks()

        # Get actual required height
        required_height = self.dialog.winfo_reqheight()

        # Set final size with min/max bounds
        final_height = max(250, min(required_height + 20, 500))  # Min 250px, Max 500px
        self.dialog.geometry(f"{width}x{final_height}")

        # Center with final size
        self._center_window(parent)

        # Not resizable
        self.dialog.resizable(False, False)

        # Now show dialog (after positioning)
        self.dialog.deiconify()

        # Now grab_set (must be after deiconify)
        self.dialog.grab_set()

        # Handle window close
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_cancel)

        # Wait for dialog to close
        self.dialog.wait_window()

    def _center_window(self, parent):
        """Centers the dialog over the parent"""
        self.dialog.update_idletasks()

        try:
            parent_x = parent.winfo_x()
            parent_y = parent.winfo_y()
            parent_width = parent.winfo_width()
            parent_height = parent.winfo_height()
        except:
            # Fallback if parent not available
            parent_x = 0
            parent_y = 0
            parent_width = self.dialog.winfo_screenwidth()
            parent_height = self.dialog.winfo_screenheight()

        dialog_width = self.dialog.winfo_width()
        dialog_height = self.dialog.winfo_height()

        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2

        # Prevent negative coordinates
        x = max(0, x)
        y = max(0, y)

        self.dialog.geometry(f"+{x}+{y}")

    def _create_widgets(self, title, message, confirm_text, cancel_text):
        """Creates the dialog widgets"""

        # Header with orange warning symbol
        header_frame = tk.Frame(self.dialog, bg='#FF9800', height=80)
        header_frame.pack(fill='x', padx=0, pady=0)
        header_frame.pack_propagate(False)

        # Warning Icon (large !)
        warning_label = tk.Label(
            header_frame,
            text="⚠",
            font=('Arial', 48, 'bold'),
            fg='white',
            bg='#FF9800'
        )
        warning_label.pack(pady=10)

        # Content Frame
        content_frame = tk.Frame(self.dialog, bg='#f0f0f0')
        content_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Title
        title_label = tk.Label(
            content_frame,
            text=title,
            font=('Arial', 16, 'bold'),
            bg='#f0f0f0',
            fg='#333333'
        )
        title_label.pack(pady=(0, 10))

        # Main message
        message_label = tk.Label(
            content_frame,
            text=message,
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#555555',
            wraplength=400,
            justify='center'
        )
        message_label.pack(pady=(0, 20))

        # Button Frame
        button_frame = tk.Frame(content_frame, bg='#f0f0f0')
        button_frame.pack(fill='x', pady=(10, 0))

        # Cancel Button (left)
        cancel_button = tk.Button(
            button_frame,
            text=cancel_text,
            command=self.on_cancel,
            bg='#9E9E9E',
            fg='white',
            font=('Arial', 11),
            width=12,
            height=1,
            cursor='hand2',
            relief='flat',
            activebackground='#757575'
        )
        cancel_button.pack(side='left', padx=5)

        # Confirm Button (right)
        confirm_button = tk.Button(
            button_frame,
            text=confirm_text,
            command=self.on_confirm,
            bg='#FF9800',
            fg='white',
            font=('Arial', 11, 'bold'),
            width=12,
            height=1,
            cursor='hand2',
            relief='flat',
            activebackground='#F57C00'
        )
        confirm_button.pack(side='right', padx=5)

        # Bind Enter and Escape keys
        self.dialog.bind('<Return>', lambda e: self.on_confirm())
        self.dialog.bind('<Escape>', lambda e: self.on_cancel())

    def on_confirm(self):
        """Handle confirm button click"""
        self.result = True
        self.dialog.destroy()

    def on_cancel(self):
        """Handle cancel button click"""
        self.result = False
        self.dialog.destroy()

