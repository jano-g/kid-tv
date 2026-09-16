from kidtv.net import _split_terse, web_urls, NetStatus


def test_split_terse_unescapes_colons():
    assert _split_terse("wlan0:wifi:connected:Doma\\:5G") == ["wlan0", "wifi", "connected", "Doma:5G"]


def test_web_urls():
    assert web_urls(NetStatus(True, "wifi", "Doma", "192.168.1.20", False), host="kid") == [
        "http://kid.local", "http://192.168.1.20"]
    assert web_urls(NetStatus(False, "hotspot", None, "10.42.0.1", True), host="kid") == ["http://kid.tv"]
    assert web_urls(NetStatus(False, "none", None, None, False), host="kid") == []
