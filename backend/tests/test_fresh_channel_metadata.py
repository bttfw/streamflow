import copy
import threading
from unittest.mock import Mock

from apps.core.request_coalescing import SingleFlight
from apps.udi.manager import UDIManager


def manager():
    result = UDIManager.__new__(UDIManager)
    result._lock = threading.RLock()
    result._channel_reads = SingleFlight()
    result._metadata_reads = SingleFlight()
    channel = {'id': 77, 'name': 'Event', 'uuid': 'channel-77', 'channel_group_id': 1, 'streams': [9]}
    stream = {'id': 9, 'name': 'Old', 'url': 'http://provider.invalid/old', 'm3u_account_id': 1,
              'stream_stats': {'quality_score': 4}}
    result._channels_cache = [channel]
    result._channels_by_id = {77: channel}
    result._channels_by_group_id = {1: [channel]}
    result._streams_cache = [stream]
    result._streams_by_id = {9: stream}
    result._streams_by_url = {stream['url']: stream}
    result._streams_by_account_id = {1: [stream]}
    result._stream_account_id = {9: 1}
    result._valid_stream_ids = {9}
    result._has_custom_streams = False
    result.fetcher = Mock(base_url='http://dispatcharr.invalid')
    result.fetcher.fetch_channel_by_id.return_value = copy.deepcopy(channel)
    result.fetcher.fetch_streams_by_ids.return_value = [copy.deepcopy(stream)]
    return result


def test_stable_id_source_changes_replace_indexes_and_report_drift():
    udi = manager()
    original_record = udi._streams_cache[0]
    incoming = copy.deepcopy(original_record)
    incoming.update(name='New', url='http://provider.invalid/new', m3u_account_id=2)
    udi.fetcher.fetch_streams_by_ids.return_value = [incoming]
    report = udi.refresh_channel_metadata(77)
    assert report['success'] and report['changed_stream_ids'] == [9]
    assert udi._streams_cache[0] is original_record
    assert 'http://provider.invalid/old' not in udi._streams_by_url
    assert udi._streams_by_url[incoming['url']] is original_record
    assert udi._stream_account_id[9] == 2
    assert udi._streams_by_account_id[1] == []
    assert udi._streams_by_account_id[2] == [original_record]


def test_partial_response_never_publishes_channel_or_streams():
    udi = manager()
    before = copy.deepcopy(udi._channels_cache)
    udi.fetcher.fetch_channel_by_id.return_value['streams'] = [9, 10]
    assert not udi.refresh_channel_metadata(77)['success']
    assert udi._channels_cache == before
    assert set(udi._streams_by_id) == {9}


def test_acknowledged_stats_written_during_read_are_preserved():
    udi = manager()
    old_server_snapshot = copy.deepcopy(udi._streams_cache[0])

    def read_streams(ids):
        fresh = copy.deepcopy(udi._streams_cache[0])
        fresh['stream_stats'] = {'quality_score': 10, 'blank_detected': False}
        udi.update_stream(9, fresh)
        return [old_server_snapshot]

    udi.fetcher.fetch_streams_by_ids.side_effect = read_streams
    assert udi.refresh_channel_metadata(77)['success']
    assert udi._streams_by_id[9]['stream_stats']['quality_score'] == 10


def test_later_read_is_fresh_and_group_index_tracks_channel_changes():
    udi = manager()
    udi.fetcher.fetch_channel_by_id.return_value['channel_group_id'] = 2
    assert udi.refresh_channel_metadata(77)['success']
    assert udi._channels_by_group_id[1] == []
    assert udi._channels_by_group_id[2][0]['id'] == 77
    assert udi.refresh_channel_metadata(77)['changed_stream_ids'] == []
    assert udi.fetcher.fetch_channel_by_id.call_count == 2


def test_statistics_update_keeps_index_record_and_custom_flag():
    udi = manager()
    record = udi._streams_by_id[9]
    udi.update_stream(9, {**record, 'stream_stats': {'quality_score': 8}})
    assert udi._streams_cache[0] is udi._streams_by_account_id[1][0] is record
    udi.update_stream(10, {'id': 10, 'url': 'http://custom.invalid/live', 'm3u_account_id': None})
    assert udi._has_custom_streams
