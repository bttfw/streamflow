#!/usr/bin/env python3
"""OpenStream sessions must not be quarantined by ffmpeg-only heuristics.

An ``openstream`` session sources health from a swarm-health API, so its
``speed`` is a keep-up margin — not ffmpeg playback speed — and it has no decoded
frames. The slow-speed auto-quarantine and the screenshot/logo pipeline are
therefore ffmpeg-only and must be skipped, or live sources get evicted as
"non-working".
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.modules['dotenv'] = MagicMock()

from apps.stream.stream_monitoring_service import (
    SLOW_SPEED_DURATION,
    StreamMonitoringService,
)
from apps.stream.stream_session_manager import SessionInfo, StreamInfo


def _slow_monitor():
    """A monitor reporting a live source that is not keeping up (margin 0.5)."""
    stats = MagicMock()
    stats.is_alive = True
    stats.is_fatal = False
    stats.speed = 0.5  # below SLOW_SPEED_THRESHOLD (0.8)
    stats.width = 0
    stats.height = 0
    stats.fps = 0
    stats.bitrate = 3000
    stats.last_updated = time.time()  # fresh -> not a timeout
    stats.error_message = None

    monitor = MagicMock()
    monitor.get_stats.return_value = stats
    monitor.get_transport_health.return_value = {
        'status': 'degraded',
        'summary': 'openstream:draining',
        'error_density': 0.5,
    }
    monitor.is_buffering.return_value = True
    monitor.port_a = None
    monitor.port_b = None
    return monitor


class TestOpenStreamQuarantine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_config_dir = os.environ.get('CONFIG_DIR')
        os.environ['CONFIG_DIR'] = self.temp_dir
        self.config_dir_patcher = patch(
            'stream_session_manager.CONFIG_DIR', Path(self.temp_dir)
        )
        self.config_dir_patcher.start()

        with patch('stream_monitoring_service.get_session_manager'), \
             patch('stream_monitoring_service.get_screenshot_service'):
            self.service = StreamMonitoringService()
        self.service.session_manager = MagicMock()
        self.service.screenshot_service = MagicMock()
        self.service.monitors = {}
        # StreamMonitoringService is a process-wide singleton, so isolate the
        # ranking/Dispatcharr side effects with a patch that self-restores rather
        # than a bare attribute assignment that would leak into later tests.
        ranks_patcher = patch.object(self.service, '_update_monitoring_ranks')
        ranks_patcher.start()
        self.addCleanup(ranks_patcher.stop)

    def tearDown(self):
        self.config_dir_patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        if self.old_config_dir:
            os.environ['CONFIG_DIR'] = self.old_config_dir
        elif 'CONFIG_DIR' in os.environ:
            del os.environ['CONFIG_DIR']

    def _make_session(self, session_type):
        session = SessionInfo(
            session_id='sess1',
            channel_id=1,
            channel_name='chan',
            regex_filter='test',
            created_at=time.time(),
            is_active=True,
            streams={},
            session_type=session_type,
        )
        stream = StreamInfo(url='http://host:6878/ace/getstream?id=abc',
                            name='s1', stream_id=101, channel_id=1)
        stream.status = 'stable'
        # Slow speed already sustained past the quarantine window.
        stream.low_speed_start_time = time.time() - (SLOW_SPEED_DURATION + 10)
        session.streams = {101: stream}
        self.service.session_manager.get_session.return_value = session
        self.service.monitors = {'sess1': {101: _slow_monitor()}}
        return session, stream

    def test_openstream_slow_margin_does_not_quarantine(self):
        self._make_session('openstream')
        self.service._evaluate_session_streams('sess1')
        self.service.session_manager.quarantine_stream.assert_not_called()

    def test_ffmpeg_slow_speed_still_quarantines(self):
        """Guard is scoped to openstream: ffmpeg sessions keep the old behavior."""
        self._make_session('ffmpeg')
        self.service._evaluate_session_streams('sess1')
        self.service.session_manager.quarantine_stream.assert_called_once()

    def test_openstream_skips_screenshots(self):
        session, _ = self._make_session('openstream')
        session.logo_id = 5
        session.enable_logo_detection = True
        self.service._check_screenshots('sess1')
        self.service.screenshot_service.capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
