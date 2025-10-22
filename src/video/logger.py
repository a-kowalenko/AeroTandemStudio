from proglog import ProgressBarLogger


class CancellationError(Exception):
    """Eigene Exception, um einen sauberen Abbruch zu signalisieren."""
    pass


class CancellableProgressBarLogger(ProgressBarLogger):
    """
    Dieser Logger prüft bei jedem Fortschritts-Update, ob das
    cancel_event gesetzt wurde und wirft dann eine Exception.

    HINWEIS: In der aktuellen Implementierung wird der Abbruch manuell
    im VideoProcessor geprüft, nicht über diesen Logger-Callback.
    """

    def __init__(self, cancel_event):
        self.cancel_event = cancel_event
        super().__init__()

    def callback(self, **changes):
        # Every time the logger message is updated, this function is called with
        # the `changes` dictionary of the form `parameter: new value`.
        for (parameter, value) in changes.items():
            print('Parameter %s is now %s' % (parameter, value))

    def bars_callback(self, bar, attr, value, old_value=None):
        percentage = (value / self.bars[bar]['total']) * 100
        print(bar, attr, percentage)
        if self.cancel_event.is_set():
            raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
