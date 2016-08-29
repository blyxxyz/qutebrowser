# Copyright 2014-2016 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <http://www.gnu.org/licenses/>.

"""Functions to receive commands through a FIFO."""

import os
import tempfile

from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject, QSocketNotifier

from qutebrowser.commands import runners
from qutebrowser.utils import standarddir, log, objreg, message
from qutebrowser.config import config

reader = None


class QtFIFOReader(QObject):

    """A FIFO reader based on a QSocketNotifier.

    Attributes:
        _filepath: The path to the opened FIFO.
        _fifo: The Python file object for the FIFO.
        _notifier: The QSocketNotifier used.

    Signals:
        got_line: Emitted when a whole line arrived.
    """

    got_line = pyqtSignal(str)

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self._filepath = filepath
        # We open as R/W so we never get EOF and have to reopen the pipe.
        # See http://www.outflux.net/blog/archives/2008/03/09/using-select-on-a-fifo/
        # We also use os.open and os.fdopen rather than built-in open so we
        # can add O_NONBLOCK.
        # pylint: disable=no-member,useless-suppression
        fd = os.open(filepath, os.O_RDWR | os.O_NONBLOCK)
        self._fifo = os.fdopen(fd, 'r')
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self.read_line)

    @pyqtSlot()
    def read_line(self):
        """(Try to) read a line from the FIFO."""
        log.procs.debug("QSocketNotifier triggered!")
        self._notifier.setEnabled(False)
        for line in self._fifo:
            self.got_line.emit(line.rstrip('\r\n'))
        self._notifier.setEnabled(True)

    def cleanup(self):
        """Clean up so the FIFO can be closed."""
        self._notifier.setEnabled(False)
        for line in self._fifo:
            self.got_line.emit(line.rstrip('\r\n'))
        self._fifo.close()


def make_temp_fifo():
    """Make a temporary FIFO for a userscript."""
    # tempfile.mktemp is deprecated and discouraged, but we use it here
    # to create a FIFO since the only other alternative would be to
    # create a directory and place the FIFO there, which sucks. Since
    # os.mkfifo will raise an exception anyways when the path doesn't
    # exist, it shouldn't be a big issue.
    filepath = tempfile.mktemp(prefix='qutebrowser-userscript-',
                               dir=standarddir.runtime())
    # pylint: disable=no-member,useless-suppression
    os.mkfifo(filepath)
    return filepath


def init():
    """Initialize the standard FIFO."""
    global reader
    filepath = os.path.join(standarddir.runtime(), 'fifo')
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError as e:
            message.error('current',
                          "Couldn't remove {}: {}".format(filepath, e))
    try:
        os.mkfifo(filepath)
    except OSError as e:
        message.error('current', "Couldn't create FIFO: {}".format(e))
    reader = QtFIFOReader(filepath)
    reader.got_line.connect(
        lambda cmd: log.commands.debug("Got FIFO command: {}".format(cmd)))
    reader.got_line.connect(run_command)


def run_command(cmd):
    """Run a FIFO command in the right window."""
    win_mode = config.get('general', 'new-instance-open-target.window')
    if win_mode == 'last-focused':
        window = objreg.last_focused_window()
    elif win_mode == 'last-opened':
        window = objreg.last_window()
    elif win_mode == 'last-visible':
        window = objreg.last_visible_window()
    runners.CommandRunner(window.win_id).run_safely(cmd)


def cleanup():
    """Clean up the standard FIFO when it's no longer needed."""
    if os.name != 'posix':
        return
    filepath = os.path.join(standarddir.runtime(), 'fifo')
    reader.cleanup()
    try:
        os.remove(filepath)
    except OSError as e:
        pass
