import hashlib
from pathlib import Path

import pytest

from scripts.preserve_public_downloads import install_downloads


def test_preserves_exact_download_bytes(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    payload = b'public installer fixture'
    (source / 'skill.sh').write_bytes(payload)
    destination = tmp_path / 'public'
    assert install_downloads(source, destination, {'skill.sh': hashlib.sha256(payload).hexdigest()}) == 1
    assert (destination / 'skill.sh').read_bytes() == payload


def test_mismatch_does_not_partially_populate_build(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'skill.sh').write_bytes(b'valid')
    (source / 'skill.ps1').write_bytes(b'changed')
    destination = tmp_path / 'public'
    with pytest.raises(ValueError, match='hash mismatch'):
        install_downloads(source, destination, {'skill.sh': hashlib.sha256(b'valid').hexdigest(), 'skill.ps1': '0' * 64})
    assert not destination.exists()


def test_rejects_paths_outside_public_downloads(tmp_path):
    with pytest.raises(ValueError, match='invalid public download path'):
        install_downloads(tmp_path, tmp_path / 'public', {'../secret': '0' * 64})
