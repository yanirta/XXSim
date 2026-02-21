"""Tests for EventEmitter."""
import logging
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from event_emitter import EventEmitter


class TestEventEmitter:

    def test_register_and_emit_single_callback(self):
        emitter = EventEmitter()
        callback = MagicMock()

        emitter.on('fill', callback)
        emitter.emit('fill', 'arg1', 'arg2')

        callback.assert_called_once_with('arg1', 'arg2')

    def test_multiple_callbacks_on_same_event(self):
        emitter = EventEmitter()
        cb1 = MagicMock()
        cb2 = MagicMock()

        emitter.on('fill', cb1)
        emitter.on('fill', cb2)
        emitter.emit('fill', 'data')

        cb1.assert_called_once_with('data')
        cb2.assert_called_once_with('data')

    def test_different_events_are_independent(self):
        emitter = EventEmitter()
        fill_cb = MagicMock()
        cancel_cb = MagicMock()

        emitter.on('fill', fill_cb)
        emitter.on('cancel', cancel_cb)
        emitter.emit('fill', 'trade', 'fill_obj')

        fill_cb.assert_called_once_with('trade', 'fill_obj')
        cancel_cb.assert_not_called()

    def test_failing_callback_does_not_block_others(self):
        emitter = EventEmitter()
        bad_cb = MagicMock(side_effect=ValueError("boom"))
        good_cb = MagicMock()

        emitter.on('status', bad_cb)
        emitter.on('status', good_cb)
        emitter.emit('status', 'trade')

        bad_cb.assert_called_once_with('trade')
        good_cb.assert_called_once_with('trade')

    def test_emit_with_no_callbacks_is_noop(self):
        emitter = EventEmitter()
        emitter.emit('nonexistent', 'data')  # should not raise

    def test_emit_with_no_args(self):
        emitter = EventEmitter()
        callback = MagicMock()

        emitter.on('ping', callback)
        emitter.emit('ping')

        callback.assert_called_once_with()
