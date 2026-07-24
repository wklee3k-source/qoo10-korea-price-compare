import subprocess, sys

urls = [
    "https://www.amoremall.com/kr/ko/product/detail?onlineProdSn=69857",
    "https://smartstore.naver.com/main/products/10035737872",
    "https://link.musinsa.com/app/goods/6514927",
    "https://menokin.co.kr/product/detail.html?product_no=22&cate_no=29&display_group=1",
]
for url in urls:
    r = subprocess.run([sys.executable, "fetch_page_title.py", url], capture_output=True, text=True, timeout=15)
    print(f"{url[:60]}\n  -> {r.stdout.strip()!r}  (stderr: {r.stderr.strip()[:100]})")
