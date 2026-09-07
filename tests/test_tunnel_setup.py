import hashlib
import io
import zipfile
import pytest
from studio.tunnel_setup import unpack_verified


def archive(name):
    data = io.BytesIO()
    with zipfile.ZipFile(data,'w') as z: z.writestr(name,b'test executable')
    return data.getvalue()


def test_tunnel_zip_validation(tmp_path):
    data = archive('client/tunnel-client.exe')
    sums = hashlib.sha256(data).hexdigest()+'  client.zip'
    result = unpack_verified(data,sums,'client.zip',tmp_path)
    assert result.read_bytes()==b'test executable'
    with pytest.raises(ValueError,match='checksum'): unpack_verified(data,'bad','client.zip',tmp_path)
    data = archive('../tunnel-client.exe')
    sums = hashlib.sha256(data).hexdigest()+'  client.zip'
    with pytest.raises(ValueError,match='Invalid path'): unpack_verified(data,sums,'client.zip',tmp_path)
