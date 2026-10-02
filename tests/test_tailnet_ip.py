"""`_tailnet_ip` phải trả IP tailnet hoặc None, không bao giờ trả rác.

BUG GỐC
───────
Chạy dưới launchd, `tailscale ip -4` in ra STDOUT:

    The Tailscale GUI failed to start: The operation couldn't be completed.

và VẪN thoát mã 0 — bản Mac App Store cần nói chuyện với tiến trình GUI qua
sandbox, mà agent launchd không ở trong phiên đồ hoạ. Bản cũ chỉ kiểm
`returncode == 0` rồi lấy dòng đầu làm hostname, nên uvicorn nhận nguyên câu
tiếng Anh đó làm tên máy, đem đi phân giải DNS và chết với:

    UnicodeError: label empty or too long

Một lỗi ở tầng cách xa chỗ sai. Bản sửa hỏi `ifconfig` trước (không cần GUI,
chạy được cả với `env -i`) và chỉ nhận địa chỉ trong 100.64.0.0/10.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

GOC = Path(__file__).resolve().parents[1]

LOI_GUI = ("The Tailscale GUI failed to start: The operation couldn’t "
           "be completed. (Tailscale.CLIError error 3.)\n")

IFCONFIG_CO = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.1.20 netmask 0xffffff00 broadcast 192.168.1.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1280
\tinet 100.101.172.22 --> 100.101.172.22 netmask 0xffffffff
"""

IFCONFIG_KHONG = """\
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.1.20 netmask 0xffffff00 broadcast 192.168.1.255
"""


def _nap():
    """Nạp serve_review.py như module rời (nó là script, không phải package)."""
    spec = importlib.util.spec_from_file_location(
        "serve_review", GOC / "scripts" / "serve_review.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sr():
    return _nap()


def _gia_lap(monkeypatch, *, ifconfig: str, cli: str = "", cli_rc: int = 0,
             co_cli: bool = True):
    """Giả lập CẢ HAI nguồn riêng biệt, theo đúng thứ tự hàm thật gọi."""
    monkeypatch.setattr(Path, "exists", lambda self: co_cli)

    def chay(cmd, *_a, **_k):
        if "ifconfig" in str(cmd[0]):
            return subprocess.CompletedProcess(cmd, 0, ifconfig, "")
        return subprocess.CompletedProcess(cmd, cli_rc, cli, "")

    monkeypatch.setattr(subprocess, "run", chay)


def test_loi_gui_khong_bao_gio_thanh_hostname(monkeypatch, sr):
    """Chính xác chuỗi đã làm sập agent phải bị loại."""
    _gia_lap(monkeypatch, ifconfig=IFCONFIG_KHONG, cli=LOI_GUI)
    assert sr._tailnet_ip() is None


def test_card_mang_duoc_hoi_truoc_cli(monkeypatch, sr):
    """Dưới launchd CLI luôn hỏng — ifconfig phải đủ để tìm ra địa chỉ."""
    _gia_lap(monkeypatch, ifconfig=IFCONFIG_CO, cli=LOI_GUI)
    assert sr._tailnet_ip() == "100.101.172.22"


def test_khong_nham_ip_lan_thanh_tailnet(monkeypatch, sr):
    """192.168.x và 127.0.0.1 không phải tailnet — mở ra LAN là lỗi bảo mật."""
    _gia_lap(monkeypatch, ifconfig=IFCONFIG_KHONG, cli="")
    assert sr._tailnet_ip() is None


def test_ma_thoat_0_khong_du_de_tin(monkeypatch, sr):
    """Bất kỳ chữ nào không phải IP tailnet đều bị loại, kể cả khi CLI báo OK."""
    for rac in ("", "   ", "not an ip", "error: something",
                "100.101.172", "100.101.172.999", "fe80::1",
                "192.168.1.20", "10.0.0.5"):
        _gia_lap(monkeypatch, ifconfig=IFCONFIG_KHONG, cli=rac + "\n")
        assert sr._tailnet_ip() is None, f"lọt rác: {rac!r}"


def test_cli_lam_duong_lui_khi_khong_co_card(monkeypatch, sr):
    """Chạy tay trong terminal: CLI trả lời được thì vẫn dùng."""
    _gia_lap(monkeypatch, ifconfig=IFCONFIG_KHONG, cli="100.101.172.22\n")
    assert sr._tailnet_ip() == "100.101.172.22"


def test_cli_ma_thoat_khac_0_thi_bo(monkeypatch, sr):
    _gia_lap(monkeypatch, ifconfig=IFCONFIG_KHONG,
             cli="100.101.172.22\n", cli_rc=1)
    assert sr._tailnet_ip() is None


def test_ifconfig_chay_duoc_voi_moi_truong_rong():
    """Bất biến nền: ifconfig KHÔNG phụ thuộc biến môi trường hay phiên GUI.

    Đây chính là lý do nó thay được CLI dưới launchd. Nếu một ngày macOS đổi
    điều này, test đỏ ở đây rẻ hơn nhiều so với agent chết lúc đăng nhập.
    """
    r = subprocess.run(["/usr/bin/env", "-i", "/sbin/ifconfig"],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert "inet " in r.stdout


def test_plist_launchd_hop_le():
    """Agent phải là plist hợp lệ và trỏ đúng tệp có thật."""
    import plistlib

    p = Path.home() / "Library/LaunchAgents/ai.ocrlab.web.plist"
    if not p.exists():
        pytest.skip("chưa cài launchd agent trên máy này")

    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "ai.ocrlab.web"
    assert d["KeepAlive"] is True, "server phải tự sống lại"

    args = d["ProgramArguments"]
    assert Path(args[0]).exists(), f"trình thông dịch không tồn tại: {args[0]}"
    assert "--tailnet" in args, "thiếu --tailnet thì máy khác không xem được"

    wd = Path(d["WorkingDirectory"])
    assert (wd / args[1]).exists(), f"không thấy script: {wd / args[1]}"
