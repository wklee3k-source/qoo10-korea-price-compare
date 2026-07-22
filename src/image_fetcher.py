"""
image_fetcher.py

자동화 영역: 상품 이미지 URL을 내려받아 정사각형 썸네일(JPEG)로 규격화한다.
webp/png 등 원본 포맷과 관계없이 RGB JPEG로 통일해서 엑셀 삽입에 바로 쓸 수 있게 한다.

사용법 (모듈로 import):
    from image_fetcher import download_and_normalize
    download_and_normalize(url, "output/imgs/0_qoo10.jpg")
"""

import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _safe_url(url: str) -> str:
    """비-ASCII(한글 등) 경로가 포함된 URL을 안전하게 인코딩한다."""
    parts = urllib.parse.urlsplit(url)
    path_q = urllib.parse.quote(parts.path)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path_q, parts.query, parts.fragment))


def download_original(url: str, out_path: str, retries: int = 3) -> bool:
    """리사이즈 없이 원본 그대로 저장한다 (고화질 보관용).
    한국 쪽(공식몰/브랜드스토어) 이미지를 대표이미지 후보로 쓸 때 사용한다."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_url = _safe_url(url)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(safe_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r, open(out_path, "wb") as f:
                f.write(r.read())
            return True
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"[WARN] failed to download original {url}: {e}")
                return False
    return False


def download_and_normalize(url: str, out_path: str, max_size: int = 300, retries: int = 3) -> bool:
    """URL의 이미지를 내려받아 RGB JPEG로 저장한다. 성공 시 True."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    safe_url = _safe_url(url)

    raw_path = out_path.with_suffix(".raw")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(safe_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r, open(raw_path, "wb") as f:
                f.write(r.read())
            break
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"[WARN] failed to download {url}: {e}")
                return False

    try:
        im = Image.open(raw_path)
        if im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        im.thumbnail((max_size, max_size))
        im.save(out_path, "JPEG", quality=85)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] failed to process image {url}: {e}")
        return False
    finally:
        raw_path.unlink(missing_ok=True)
