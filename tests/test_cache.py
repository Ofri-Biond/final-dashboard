from lib.cache import SYNC_STATE_FILENAME, load_sync_state


def test_corrupt_sync_state_file_reads_as_no_sync(tmp_path):
    (tmp_path / SYNC_STATE_FILENAME).write_text("{not json")
    assert load_sync_state(tmp_path) is None
