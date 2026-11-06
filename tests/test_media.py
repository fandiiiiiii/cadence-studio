from cadence_studio.media import ALLOWED_EXTENSIONS, safe_filename


def test_common_video_containers_are_accepted_and_preserved():
    assert {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv"} <= ALLOWED_EXTENSIONS
    assert safe_filename("song.MP4") == "song.mp4"
    assert safe_filename("clip.mov") == "clip.mov"
